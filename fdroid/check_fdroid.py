#!/usr/bin/env python3
"""
F-Droid & IzzyOnDroid New App RSS Feed Generator
Fetches updates using Index V2 entry.json diffs, detects new apps against known_apps.txt,
and produces a standard RSS 2.0 feed (feed.xml).
"""

import os
import sys
import json
import time
import hashlib
import logging
import argparse
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
import xml.etree.ElementTree as ET
from xml.dom import minidom
import requests

# Configure logging
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fdroid-rss")

# Repository Configurations
REPOS = {
    "fdroid": {
        "name": "F-Droid",
        "base_url": "https://f-droid.org/repo",
        "entry_url": "https://f-droid.org/repo/entry.json",
        "index_url": "https://f-droid.org/repo/index-v2.json",
        "app_url_pattern": "https://f-droid.org/packages/{pkg}/",
        "timestamp_file": "last_timestamp_fdroid.txt",
    },
    "izzy": {
        "name": "IzzyOnDroid",
        "base_url": "https://apt.izzysoft.de/fdroid/repo",
        "entry_url": "https://apt.izzysoft.de/fdroid/repo/entry.json",
        "index_url": "https://apt.izzysoft.de/fdroid/repo/index-v2.json",
        "app_url_pattern": "https://apt.izzysoft.de/fdroid/index/apk/{pkg}",
        "timestamp_file": "last_timestamp_izzy.txt",
    },
}

KNOWN_APPS_FILE = "known_apps.txt"
FEED_FILE = "feed.xml"
FEED_TITLE = "F-Droid & IzzyOnDroid New Apps"
FEED_DESCRIPTION = "New apps discovered on F-Droid and IzzyOnDroid repositories"
FEED_LINK = os.environ.get("FEED_LINK", "https://qrsp.github.io/rss/fdroid/feed.xml")

DEFAULT_MAX_ITEMS = 200
EXPANDED_MAX_ITEMS = 500
BATCH_EXPAND_THRESHOLD = 200

USER_AGENT = "FDroid-RSS-Bot/1.0 (+https://github.com/qrsp/rss)"


def fetch_with_retry(url: str, max_retries: int = 3, base_delay: float = 5.0, timeout: int = 60) -> requests.Response:
    """Fetch URL with exponential backoff retry."""
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(max_retries):
        try:
            logger.debug(f"Fetching URL (attempt {attempt + 1}/{max_retries}): {url}")
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response
        except (requests.RequestException, Exception) as e:
            if attempt == max_retries - 1:
                logger.error(f"Failed to fetch {url} after {max_retries} attempts: {e}")
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(f"Error fetching {url}: {e}. Retrying in {delay:.1f}s...")
            time.sleep(delay)


def verify_sha256(content: bytes, expected_hash: str) -> bool:
    """Verify SHA-256 hash of downloaded bytes."""
    if not expected_hash:
        return True
    actual_hash = hashlib.sha256(content).hexdigest().lower()
    if actual_hash != expected_hash.lower():
        logger.error(f"SHA-256 mismatch: expected {expected_hash}, got {actual_hash}")
        return False
    return True


def get_localized_text(field: any, default: str = "") -> str:
    """Extract English localized string from index-v2 dictionary or string."""
    if not field:
        return default
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        for lang in ["en-US", "en", "en_US", "en-GB"]:
            if lang in field and field[lang]:
                return field[lang]
        for val in field.values():
            if val:
                return str(val)
    return default


def load_known_apps(filepath: str = KNOWN_APPS_FILE) -> set:
    """Load known package IDs from file."""
    if not os.path.exists(filepath):
        return set()
    with open(filepath, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_known_apps(known_apps: set, filepath: str = KNOWN_APPS_FILE):
    """Save known package IDs to file sorted."""
    with open(filepath, "w", encoding="utf-8") as f:
        for pkg in sorted(known_apps):
            f.write(f"{pkg}\n")
    logger.info(f"Saved {len(known_apps)} package IDs to {filepath}")


def read_timestamp(filepath: str) -> int | None:
    """Read stored timestamp integer from file."""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return int(content) if content else None
    except Exception as e:
        logger.warning(f"Failed to read timestamp from {filepath}: {e}")
        return None


def save_timestamp(timestamp: int, filepath: str):
    """Save timestamp integer to file."""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"{timestamp}\n")
    logger.info(f"Updated {filepath} to {timestamp}")


def needs_migration(known_apps: set) -> bool:
    """Detect if known_apps contains display names rather than package IDs."""
    if not known_apps:
        return False
    # If more than 5% of lines contain spaces or don't have dots, it's display names
    invalid_count = sum(1 for name in known_apps if " " in name or "." not in name)
    return (invalid_count / len(known_apps)) > 0.05


def migrate_known_apps():
    """Migrate display names in known_apps.txt to package IDs using full index-v2."""
    logger.info("Migrating known_apps.txt display names to package IDs...")
    known_lines = load_known_apps()
    all_packages = set()

    for key, repo in REPOS.items():
        try:
            logger.info(f"Downloading full index-v2 for migration from {repo['name']}...")
            resp = fetch_with_retry(repo["index_url"], timeout=120)
            data = resp.json()
            packages = data.get("packages", {})
            for pkg, val in packages.items():
                all_packages.add(pkg)
            # Also save latest repo timestamp
            entry_resp = fetch_with_retry(repo["entry_url"])
            entry_data = entry_resp.json()
            entry_ts = entry_data.get("timestamp")
            if entry_ts:
                save_timestamp(entry_ts, repo["timestamp_file"])
        except Exception as e:
            logger.error(f"Migration error for {repo['name']}: {e}")

    logger.info(f"Migration mapped {len(all_packages)} active packages from repositories.")
    save_known_apps(all_packages)
    return all_packages


def parse_diff_packages(repo_key: str, repo_info: dict, diff_data: dict, known_apps: set, current_time_str: str) -> list:
    """Extract new app items from diff packages."""
    new_apps = []
    packages = diff_data.get("packages", {})

    for pkg_id, pkg_data in packages.items():
        if pkg_data is None:  # RFC 7396 deletion
            continue
        if pkg_id in known_apps:
            continue

        metadata = pkg_data.get("metadata", {}) if isinstance(pkg_data, dict) else {}
        name = get_localized_text(metadata.get("name"), default=pkg_id)
        summary = get_localized_text(metadata.get("summary"), default="")
        source_code = metadata.get("sourceCode") or metadata.get("issueTracker") or repo_info["app_url_pattern"].format(pkg=pkg_id)
        app_page_url = repo_info["app_url_pattern"].format(pkg=pkg_id)

        # Extract icon URL if present
        icon_url = None
        icon_meta = metadata.get("icon")
        if isinstance(icon_meta, dict):
            for locale in ["en-US", "en", "en_US"]:
                if locale in icon_meta and isinstance(icon_meta[locale], dict) and "name" in icon_meta[locale]:
                    icon_path = icon_meta[locale]["name"].lstrip("/")
                    icon_url = f"{repo_info['base_url']}/{icon_path}"
                    break
            if not icon_url:
                for locale_val in icon_meta.values():
                    if isinstance(locale_val, dict) and "name" in locale_val:
                        icon_path = locale_val["name"].lstrip("/")
                        icon_url = f"{repo_info['base_url']}/{icon_path}"
                        break

        # Build HTML description
        icon_html = f'<img src="{icon_url}" alt="{name} icon" width="64" height="64" style="float:left; margin-right:12px; border-radius:12px;" />\n' if icon_url else ""
        summary_html = f"<p>{summary}</p>" if summary else ""
        desc_html = (
            f"<div>\n"
            f"{icon_html}"
            f"<p><strong>{name}</strong> (<code>{pkg_id}</code>) — <em>{repo_info['name']}</em></p>\n"
            f"{summary_html}\n"
            f'<p><a href="{source_code}">Source Code</a> | <a href="{app_page_url}">{repo_info["name"]} Page</a></p>\n'
            f"</div>"
        )

        app_item = {
            "title": f"[{repo_info['name']}] {name}",
            "link": source_code,
            "guid": f"{pkg_id}@{repo_key}",
            "pubDate": current_time_str,
            "description": desc_html,
            "pkg_id": pkg_id,
        }
        new_apps.append(app_item)
        known_apps.add(pkg_id)

    return new_apps


def process_repo(repo_key: str, repo_info: dict, known_apps: set, current_time_str: str) -> list:
    """Process a single repository diffs and return newly discovered apps."""
    logger.info(f"--- Checking repository: {repo_info['name']} ---")
    new_apps = []

    try:
        entry_resp = fetch_with_retry(repo_info["entry_url"])
        entry_data = entry_resp.json()
    except Exception as e:
        logger.error(f"Could not fetch entry.json for {repo_info['name']}: {e}")
        return new_apps

    current_repo_timestamp = entry_data.get("timestamp")
    last_timestamp = read_timestamp(repo_info["timestamp_file"])
    diffs = entry_data.get("diffs", {})

    if not diffs:
        logger.info(f"No diffs available for {repo_info['name']}.")
        if current_repo_timestamp:
            save_timestamp(current_repo_timestamp, repo_info["timestamp_file"])
        return new_apps

    available_timestamps = sorted(int(ts) for ts in diffs.keys())
    logger.info(f"Available diff timestamps: {available_timestamps}")
    logger.info(f"Last recorded timestamp: {last_timestamp}")

    # Determine which diffs to download
    if last_timestamp is None:
        logger.info(f"No previous timestamp found for {repo_info['name']}. Using oldest available diff.")
        target_timestamps = [available_timestamps[0]]
    elif last_timestamp < available_timestamps[0]:
        logger.info(f"Last timestamp {last_timestamp} is older than oldest diff {available_timestamps[0]}. Processing all available diffs.")
        target_timestamps = available_timestamps
    else:
        target_timestamps = [ts for ts in available_timestamps if ts > last_timestamp]

    if not target_timestamps:
        logger.info(f"Repository {repo_info['name']} is already up to date.")
        if current_repo_timestamp and (last_timestamp is None or current_repo_timestamp > last_timestamp):
            save_timestamp(current_repo_timestamp, repo_info["timestamp_file"])
        return new_apps

    logger.info(f"Processing {len(target_timestamps)} diff(s) for {repo_info['name']}: {target_timestamps}")

    latest_processed_ts = last_timestamp or target_timestamps[-1]

    for ts in target_timestamps:
        diff_info = diffs.get(str(ts))
        if not diff_info:
            continue

        diff_name = diff_info.get("name", f"/diff/{ts}.json")
        diff_url = f"{repo_info['base_url']}{diff_name}"
        expected_sha256 = diff_info.get("sha256")

        try:
            logger.info(f"Downloading diff: {diff_url}")
            resp = fetch_with_retry(diff_url)
            if expected_sha256 and not verify_sha256(resp.content, expected_sha256):
                logger.error(f"Skipping diff {diff_url} due to SHA-256 mismatch")
                continue

            diff_data = resp.json()
            apps_from_diff = parse_diff_packages(repo_key, repo_info, diff_data, known_apps, current_time_str)
            logger.info(f"Found {len(apps_from_diff)} new app(s) in diff {ts}")
            new_apps.extend(apps_from_diff)
            latest_processed_ts = max(latest_processed_ts or 0, ts)
        except Exception as e:
            logger.error(f"Error processing diff {diff_url}: {e}")

    # Update timestamp file to latest processed diff or current entry timestamp
    final_timestamp = current_repo_timestamp if current_repo_timestamp else latest_processed_ts
    if final_timestamp:
        save_timestamp(final_timestamp, repo_info["timestamp_file"])

    return new_apps


def load_existing_feed_items(feed_file: str = FEED_FILE) -> list:
    """Parse existing items from feed.xml if present."""
    if not os.path.exists(feed_file):
        return []

    items = []
    try:
        tree = ET.parse(feed_file)
        root = tree.getroot()
        channel = root.find("channel")
        if channel is None:
            return []

        for item_elem in channel.findall("item"):
            title = item_elem.findtext("title", "")
            link = item_elem.findtext("link", "")
            guid = item_elem.findtext("guid", "")
            pub_date = item_elem.findtext("pubDate", "")
            description = item_elem.findtext("description", "")

            items.append({
                "title": title,
                "link": link,
                "guid": guid,
                "pubDate": pub_date,
                "description": description,
            })
    except Exception as e:
        logger.warning(f"Could not parse existing feed.xml: {e}")
    return items


def generate_feed_xml(items: list, output_file: str = FEED_FILE):
    """Generate RSS 2.0 feed.xml using xml.etree.ElementTree."""
    ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
    rss = ET.Element("rss", {
        "version": "2.0",
    })
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = FEED_TITLE
    ET.SubElement(channel, "link").text = FEED_LINK
    ET.SubElement(channel, "description").text = FEED_DESCRIPTION
    ET.SubElement(channel, "language").text = "en-us"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))

    ET.SubElement(channel, "{http://www.w3.org/2005/Atom}link", {
        "href": FEED_LINK,
        "rel": "self",
        "type": "application/rss+xml"
    })

    for item in items:
        item_elem = ET.SubElement(channel, "item")
        ET.SubElement(item_elem, "title").text = item.get("title", "")
        ET.SubElement(item_elem, "link").text = item.get("link", "")
        guid_elem = ET.SubElement(item_elem, "guid", {"isPermaLink": "false"})
        guid_elem.text = item.get("guid", "")
        ET.SubElement(item_elem, "pubDate").text = item.get("pubDate", "")
        
        desc_elem = ET.SubElement(item_elem, "description")
        desc_elem.text = item.get("description", "")

    # Format with indentation
    xml_str = ET.tostring(rss, encoding="utf-8")
    parsed_xml = minidom.parseString(xml_str)
    pretty_xml = parsed_xml.toprettyxml(indent="  ", encoding="utf-8")

    with open(output_file, "wb") as f:
        f.write(pretty_xml)

    logger.info(f"Generated {output_file} with {len(items)} items.")


def main():
    parser = argparse.ArgumentParser(description="Generate RSS feed for new F-Droid and IzzyOnDroid apps")
    parser.add_argument("--migrate", action="store_true", help="Force one-time migration of known_apps.txt to package IDs")
    args = parser.parse_args()

    current_time_str = format_datetime(datetime.now(timezone.utc))
    known_apps = load_known_apps()

    # Check if migration is needed
    if args.migrate or needs_migration(known_apps):
        known_apps = migrate_known_apps()

    new_apps_all = []
    for repo_key, repo_info in REPOS.items():
        new_apps = process_repo(repo_key, repo_info, known_apps, current_time_str)
        new_apps_all.extend(new_apps)

    logger.info(f"Total new apps found across all repos: {len(new_apps_all)}")

    # Update known_apps.txt if new apps were found
    if new_apps_all:
        save_known_apps(known_apps)

    # Dynamic retention policy
    existing_items = load_existing_feed_items()
    # Filter out any duplicates based on guid
    seen_guids = set()
    combined_items = []
    for item in new_apps_all + existing_items:
        guid = item.get("guid")
        if guid and guid not in seen_guids:
            seen_guids.add(guid)
            combined_items.append(item)

    max_items = EXPANDED_MAX_ITEMS if len(new_apps_all) > BATCH_EXPAND_THRESHOLD else DEFAULT_MAX_ITEMS
    final_items = combined_items[:max_items]

    if new_apps_all or not os.path.exists(FEED_FILE):
        generate_feed_xml(final_items)
    else:
        logger.info("No new apps found and feed.xml exists; skipping feed regeneration.")


if __name__ == "__main__":
    main()
