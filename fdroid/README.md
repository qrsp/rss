# F-Droid & IzzyOnDroid New App RSS Feed

[![Check F-Droid & IzzyOnDroid Updates](https://github.com/qrspncpr/fdroid-rss/actions/workflows/check_fdroid.yml/badge.svg)](https://github.com/qrspncpr/fdroid-rss/actions/workflows/check_fdroid.yml)

Automated RSS 2.0 Feed generator monitoring new applications and updates on **F-Droid** and **IzzyOnDroid** repositories using the efficient **F-Droid Index V2** diff format.

---

## 📡 RSS Feed URL

Subscribe to the feed in your favorite RSS reader:
```
https://qrspncpr.github.io/fdroid-rss/feed.xml
```

---

## 🚀 Features

- **Multi-Repository Monitoring**: Tracks both the official [F-Droid repository](https://f-droid.org) and [IzzyOnDroid repository](https://apt.izzysoft.de/fdroid/repo).
- **Index V2 Diff-Based**: Leverages F-Droid `entry.json` and incremental delta diffs (`/diff/<timestamp>.json`) to minimize bandwidth usage.
- **Accurate App Tracking**: Uses immutable **Package IDs** (e.g. `com.vrem.wifianalyzer`) to prevent duplicate notifications and handle app renames seamlessly.
- **Rich RSS Items**: Includes app icons, English summaries, source code links, repository tags, and direct repository app page links.
- **Dynamic Retention Policy**: Retains the last 200 entries by default, automatically expanding to 500 entries if a single batch exceeds 200 new apps.
- **Automated Execution**: Runs daily at **20:00 and 22:00** via GitHub Actions, and supports manual triggering (`workflow_dispatch`).
- **Resilient & Secure**: Includes exponential backoff retry on HTTP failures and SHA-256 integrity verification.

---

## 📁 Repository Structure

```
fdroid-rss/
├── .github/
│   └── workflows/
│       └── check_fdroid.yml    # GitHub Actions workflow
├── check_fdroid.py             # Main Python generator script
├── requirements.txt            # Python dependencies (requests)
├── known_apps.txt              # Known package IDs (one per line)
├── last_timestamp_fdroid.txt   # Last processed timestamp for F-Droid
├── last_timestamp_izzy.txt     # Last processed timestamp for IzzyOnDroid
├── feed.xml                    # Output RSS 2.0 feed
├── Plan.md                     # Architecture and implementation plan
└── README.md                   # Project documentation
```

---

## 🛠️ Local Development & Testing

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the check script**:
   ```bash
   python check_fdroid.py
   ```

3. **Optional arguments & environment variables**:
   ```bash
   # Enable debug logging
   LOG_LEVEL=DEBUG python check_fdroid.py

   # Force re-migration / bootstrap of known_apps.txt
   python check_fdroid.py --migrate
   ```

---

## ⚙️ GitHub Pages Setup

To serve `feed.xml` directly via GitHub Pages:
1. Go to your GitHub repository **Settings** > **Pages**.
2. Under **Build and deployment** > **Source**, choose **Deploy from a branch**.
3. Select branch **`main`** and folder **`/ (root)`**.
4. Click **Save**. Your RSS feed will be live at `https://<username>.github.io/<repo>/feed.xml`.

---

## 📄 License

MIT License
