# F-Droid & IzzyOnDroid New App RSS Feed — Implementation Plan

利用 GitHub Actions 與 Python 打造 F-Droid / IzzyOnDroid 新軟體上架 RSS Feed

## Repositories Monitored

| Repo | Base URL | Entry Point |
|------|----------|-------------|
| F-Droid Official | `https://f-droid.org/repo/` | `entry.json` |
| IzzyOnDroid | `https://apt.izzysoft.de/fdroid/repo/` | `entry.json` |

## Architecture Overview

```
entry.json (per repo)
    │
    ├─ Has diff since last_timestamp? ──▶ Download diff(s)
    │                                       │
    └─ No matching diff (first run / stale)  │
         │                                   │
         └─ Use oldest available diff ◀──────┘
                    │
                    ▼
           Extract package IDs from diff
                    │
                    ▼
           Compare against known_apps.txt
                    │
        ┌───────────┴───────────┐
        │                       │
    New apps found         No new apps
        │                       │
        ▼                       ▼
  Add to feed.xml        Log "no new apps"
  Update known_apps.txt       │
        │                       │
        └───────┬───────────────┘
                ▼
     Always update timestamp files
     Commit & push changed files
```

## Data Flow & State

### State Files (all committed to `main` branch)

| File | Purpose | Format |
|------|---------|--------|
| `known_apps.txt` | Shared exclusion list | One **package ID** per line (e.g. `com.vrem.wifianalyzer`) |
| `last_timestamp_fdroid.txt` | Last-processed diff timestamp for F-Droid | Single integer (epoch ms) |
| `last_timestamp_izzy.txt` | Last-processed diff timestamp for IzzyOnDroid | Single integer (epoch ms) |
| `feed.xml` | RSS 2.0 output feed | XML |

### App Identification

- Apps are identified by **package ID** (e.g. `org.example.app`), not display name.
- Package IDs are immutable and unique — prevents duplicates from app renames.

### Migration (One-time Bootstrap)

The existing `known_apps.txt` contains ~4,311 display names. On the first run:
1. Download the full `index-v2.json` from both repos.
2. Map all display names → package IDs.
3. Rewrite `known_apps.txt` with package IDs.
4. Save the current timestamp from `entry.json` to both timestamp files.
5. Use the oldest available diff from `entry.json` as the starting point for diff processing.

## Diff Processing Logic

1. Fetch `entry.json` from each repo.
2. Read the corresponding `last_timestamp_*.txt`.
3. Find all diffs with timestamps **greater than** the last-seen timestamp.
   - If no matching diffs (timestamp too old or first run): use the **oldest available diff**.
4. Download **all** matching diffs (process multiple if the script hasn't run for several days).
5. **Verify SHA-256 hash** of each downloaded file against `entry.json`.
6. Extract all package IDs present in the diff's `packages` section.
7. Filter out any package IDs already in `known_apps.txt`.
8. Remaining package IDs = **new apps** for the RSS feed.

## RSS Feed (`feed.xml`)

### Format
- **RSS 2.0** standard
- Generated using Python's built-in `xml.etree.ElementTree` (no external XML library)
- Language: **English** (prefer `en-US` localization from index, fall back to first available)

### Channel Metadata
- Title: "F-Droid & IzzyOnDroid New Apps"
- Link: GitHub Pages URL
- Description: "New apps discovered on F-Droid and IzzyOnDroid repositories"

### Item Fields

| RSS Element | Source |
|-------------|--------|
| `<title>` | `{Name} — {Summary} [{Repo}] [{Category}]` (English preferred) |
| `<link>` | Source code URL |
| `<category>` | App categories (e.g. `System`, `Multimedia`) |
| `<enclosure>` | App icon URL (`image/png`) for rich reader thumbnail previews |
| `<description>` | HTML formatted: Top-level bold summary (optimized for reader snippet previews) + icon + package info + category/license + links |
| `<pubDate>` | Timestamp of discovery (current run time) |
| `<guid>` | Package ID (isPermaLink=false) |

### Retention Policy (Dynamic)
- Default: keep last **200 items**
- If a single run adds **>200 new apps**: auto-expand to **500 items**
- Oldest items are trimmed from the bottom of the feed
- New items are **prepended** (newest first)

### Combined Feed
- Single `feed.xml` for both repos
- Each item's description indicates which repo it came from (F-Droid vs IzzyOnDroid)

## Python Script (`check_fdroid.py`)

### Dependencies
- `requests` (pinned in `requirements.txt`)
- Standard library only otherwise: `xml.etree.ElementTree`, `json`, `hashlib`, `logging`, `datetime`, `os`, `sys`

### Logging
- Uses Python's `logging` module
- Configurable log levels via environment variable or argument
- Logs: repos checked, diffs downloaded, new apps found, items added to feed

### Error Handling
- HTTP requests: **retry with exponential backoff** (3 attempts)
- SHA-256 mismatch: log error, skip that diff, continue with others
- JSON parse errors: log error, skip, continue

### Commit & Push Behavior
- **Always** update and commit timestamp files (even when no new apps found)
- Only commit `feed.xml` and `known_apps.txt` when they have changes
- Skip push entirely if no files changed (all timestamps were already current)

## GitHub Actions Workflow

### Schedule
- **Cron**: `0 22 * * *`
- **Manual trigger**: `workflow_dispatch`

### Steps
1. Checkout `main` branch
2. Set up Python 3
3. `pip install -r requirements.txt`
4. Run `python check_fdroid.py`
5. Commit & push changed files using `GITHUB_TOKEN`

### Hosting
- `feed.xml` served via **GitHub Pages** from `main` branch

## File Structure

```
fdroid-rss/
├── .github/
│   └── workflows/
│       └── check_fdroid.yml
├── check_fdroid.py
├── requirements.txt
├── known_apps.txt          # Package IDs (one per line)
├── last_timestamp_fdroid.txt
├── last_timestamp_izzy.txt
├── feed.xml
├── Plan.md
└── README.md
```
