# RSS Feeds Monorepo

Automated RSS feed generators for software updates across various platforms and package ecosystems.

## Feeds

| Directory | Name | Target Ecosystem | Feed URL | Update Schedule |
|---|---|---|---|---|
| [`fdroid/`](fdroid/) | **F-Droid & IzzyOnDroid** | Open-source Android apps | `https://qrsp.github.io/rss/fdroid/feed.xml` | Daily at 20:00, 22:00 UTC |
| [`morphe/`](morphe/) | **Morphe** | Morphe Android patches & apps | `https://qrsp.github.io/rss/morphe/feed.xml` | Daily at 20:10, 22:10 UTC |
| [`scoop/`](scoop/) | **Scoop Buckets** | Scoop Windows packages (`Main`, `Extras`, `Nonportable`, `Nirsoft`) | `https://qrsp.github.io/rss/scoop/feed.xml` | Daily at 20:20, 22:20 UTC |

---

## Directory Structure

```
rss/
├── .github/
│   └── workflows/
│       ├── fdroid.yml          # Automated run for F-Droid / IzzyOnDroid
│       ├── morphe.yml          # Automated run for Morphe
│       └── scoop.yml           # Automated run for Scoop
├── .gitignore
├── fdroid/
│   ├── check_fdroid.py
│   ├── requirements.txt
│   ├── feed.xml
│   ├── known_apps.txt
│   ├── last_timestamp_fdroid.txt
│   └── last_timestamp_izzy.txt
├── morphe/
│   ├── generate_rss.py
│   ├── feed.xml
│   └── known_apps.txt
├── scoop/
│   ├── generate_rss.py
│   ├── test_generate_rss.py
│   ├── feed.xml
│   └── known_apps.txt
└── README.md
```

---

## Local Development & Testing

### F-Droid RSS
```bash
cd fdroid
pip install -r requirements.txt
python check_fdroid.py
```

### Morphe RSS
```bash
cd morphe
python generate_rss.py
```

### Scoop RSS
```bash
cd scoop
python -m unittest test_generate_rss.py
python generate_rss.py
```
