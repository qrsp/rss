#!/usr/bin/env python3
"""
F-Droid & IzzyOnDroid New App RSS Feed Generator
Fetches updates using Index V2 entry.json diffs, detects new apps against known_apps.txt,
and produces a standard RSS 2.0 feed (feed.xml).
"""

import os
import sys
import re
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

DEFAULT_MAX_ITEMS = 500

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


def get_localized_text(field: any, default: str = "", fallback_to_any: bool = True) -> str:
    """Extract English localized string from index-v2 dictionary or string."""
    if not field:
        return default
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        for lang in ["en-US", "en", "en_US", "en-GB"]:
            if lang in field and field[lang]:
                return field[lang]
        if fallback_to_any:
            for val in field.values():
                if val:
                    return str(val)
    return default


def clean_text(text: str) -> str:
    """Clean markdown links, styling, and whitespace from text."""
    if not text:
        return ""
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'[*_`#]', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_summary(metadata: dict) -> tuple[str, bool]:
    """Extract summary, returning (summary_text, is_english)."""
    if not isinstance(metadata, dict):
        return "", False

    # Prefer English localization first
    summary_en = get_localized_text(metadata.get("summary"), fallback_to_any=False)
    if summary_en:
        return clean_text(summary_en), True

    desc_en = get_localized_text(metadata.get("description"), fallback_to_any=False)
    if desc_en:
        desc_clean = clean_text(desc_en)
        if desc_clean:
            sentences = re.split(r'(?<=[.!?])\s+', desc_clean)
            return (sentences[0].strip() if sentences else desc_clean), True

    # Fall back to any language if present, but mark as non-English
    any_summary = get_localized_text(metadata.get("summary"), fallback_to_any=True)
    if any_summary:
        return clean_text(any_summary), False

    any_desc = get_localized_text(metadata.get("description"), fallback_to_any=True)
    if any_desc:
        desc_clean = clean_text(any_desc)
        if desc_clean:
            sentences = re.split(r'(?<=[.!?])\s+', desc_clean)
            return (sentences[0].strip() if sentences else desc_clean), False

    return "", False


def fetch_fallback_metadata(repo_key: str, pkg_id: str, app_page_url: str) -> dict:
    """Fallback fetch for missing name, summary, and icon from repository web pages."""
    result = {}
    try:
        resp = fetch_with_retry(app_page_url, max_retries=2, base_delay=1.0, timeout=10)
        html = resp.text

        if repo_key == "fdroid":
            # Extract summary: check package-summary div, then meta description
            m_sum = re.search(r'<div class="package-summary">\s*(.*?)\s*</div>', html, re.DOTALL | re.IGNORECASE)
            if not m_sum:
                m_sum = re.search(r'<meta\s+(?:name|property)="description"\s+content="([^"]+)"', html, re.IGNORECASE)
            if m_sum:
                result["summary"] = clean_text(m_sum.group(1))

            # Extract name: package-name h3, then og:title
            m_name = re.search(r'<h3 class="package-name">\s*(.*?)\s*</h3>', html, re.DOTALL | re.IGNORECASE)
            if not m_name:
                m_name = re.search(r'<meta\s+property="og:title"\s+content="([^|"]+)', html, re.IGNORECASE)
            if m_name:
                result["name"] = clean_text(m_name.group(1))

            # Extract icon: og:image
            m_icon = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html, re.IGNORECASE)
            if m_icon:
                result["icon"] = m_icon.group(1).strip()

        elif repo_key == "izzy":
            # Extract summary: meta og:description
            m_sum = re.search(r'<meta\s+property="og:description"\s+content="([^"]+)"', html, re.IGNORECASE)
            if m_sum:
                sum_text = clean_text(m_sum.group(1))
                if sum_text and "App not found" not in sum_text:
                    result["summary"] = sum_text

            # Extract name: meta og:title e.g. „HeliBoard“ – IzzyOnDroid F-Droid Repository
            m_name = re.search(r'<meta\s+property="og:title"\s+content="([^–"—]+?)\s*–\s*IzzyOnDroid', html, re.IGNORECASE)
            if m_name:
                name_clean = clean_text(m_name.group(1)).strip(' \t\n\r"\'„”«»“”')
                if name_clean and "App not found" not in name_clean:
                    result["name"] = name_clean

            # Extract icon: meta og:image
            m_icon = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html, re.IGNORECASE)
            if m_icon:
                icon_path = m_icon.group(1).strip()
                if "izzy-on-droid.png" not in icon_path:
                    if icon_path.startswith("/"):
                        icon_path = f"https://apt.izzysoft.de{icon_path}"
                    result["icon"] = icon_path

        # Extract source code repository link (common to both repositories)
        m_src = re.search(r'<a[^>]+href=[\'"]([^\'"]+)[\'"][^>]*>\s*Source(?:\s+Code)?\s*</a>', html, re.IGNORECASE)
        if m_src:
            src_url = m_src.group(1).strip()
            if src_url and src_url != app_page_url:
                result["source_code"] = src_url

    except Exception as e:
        logger.warning(f"Failed to fetch web fallback metadata for {pkg_id} ({app_page_url}): {e}")

    return result


def format_app_title(repo_name: str, name: str, summary: str, categories: list) -> str:
    """Format app title as: {Name} — {Summary} [{Repo}] [{Category}]"""
    cat_tag = f" [{categories[0]}]" if categories and categories[0] else ""
    if summary:
        return f"{name} — {summary} [{repo_name}]{cat_tag}"
    return f"{name} [{repo_name}]{cat_tag}"


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
            # Also save latest diff timestamp
            entry_resp = fetch_with_retry(repo["entry_url"])
            entry_data = entry_resp.json()
            diffs = entry_data.get("diffs", {})
            if diffs:
                latest_diff_ts = max(int(ts) for ts in diffs.keys())
                save_timestamp(latest_diff_ts, repo["timestamp_file"])
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
        name = get_localized_text(metadata.get("name"), default="", fallback_to_any=False)
        summary, is_en_summary = extract_summary(metadata)
        
        categories = metadata.get("categories", [])
        if isinstance(categories, str):
            categories = [categories]
        elif not isinstance(categories, list):
            categories = []

        license_name = metadata.get("license", "")
        source_code = metadata.get("sourceCode") or metadata.get("issueTracker")
        app_page_url = repo_info["app_url_pattern"].format(pkg=pkg_id)
        if source_code == app_page_url:
            source_code = None

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

        # Fallback to web scraping if critical metadata (English name/summary, icon, source) is missing
        if not is_en_summary or not name or name == pkg_id or not icon_url or not source_code:
            fallback = fetch_fallback_metadata(repo_key, pkg_id, app_page_url)
            if (not is_en_summary or not summary) and fallback.get("summary"):
                summary = fallback["summary"]
            if (not name or name == pkg_id) and fallback.get("name"):
                name = fallback["name"]
            if not icon_url and fallback.get("icon"):
                icon_url = fallback["icon"]
            if not source_code and fallback.get("source_code"):
                source_code = fallback["source_code"]

        # Final fallback for name if still missing
        if not name or name == pkg_id:
            name = get_localized_text(metadata.get("name"), default=pkg_id, fallback_to_any=True)

        # Build HTML description - Clean, no duplicate content from Title
        icon_html = f'<img src="{icon_url}" alt="{name} icon" width="64" height="64" style="float:left; margin-right:12px; margin-bottom:8px; border-radius:12px;" />\n' if icon_url else ""
        license_info = f"<br/>\n⚖️ <strong>License:</strong> {license_name}" if license_name else ""

        if source_code and source_code != app_page_url:
            links_html = f'<p><a href="{source_code}">Source Code</a> | <a href="{app_page_url}">{repo_info["name"]} Page</a></p>'
            rss_link = source_code
        else:
            links_html = f'<p><a href="{app_page_url}">{repo_info["name"]} Page</a></p>'
            rss_link = app_page_url

        desc_html = (
            f"<div>\n"
            f"{icon_html}"
            f"<p><strong>Package:</strong> <code>{pkg_id}</code>"
            f"{license_info}</p>\n"
            f"{links_html}\n"
            f"</div>"
        )

        app_item = {
            "title": format_app_title(repo_info["name"], name, summary, categories),
            "link": rss_link,
            "guid": f"{pkg_id}@{repo_key}",
            "pubDate": current_time_str,
            "description": desc_html,
            "pkg_id": pkg_id,
            "categories": categories,
            "enclosure": icon_url,
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

    last_timestamp = read_timestamp(repo_info["timestamp_file"])
    diffs = entry_data.get("diffs", {})

    if not diffs:
        logger.info(f"No diffs available for {repo_info['name']}.")
        return new_apps

    available_timestamps = sorted(int(ts) for ts in diffs.keys())
    logger.info(f"Available diff timestamps: {available_timestamps}")
    logger.info(f"Last recorded timestamp: {last_timestamp}")

    oldest_available_ts = available_timestamps[0]
    latest_available_ts = available_timestamps[-1]

    # Check if already up to date
    if last_timestamp is not None and last_timestamp >= latest_available_ts:
        logger.info(f"Repository {repo_info['name']} is already up to date.")
        return new_apps

    # Determine target diff to download.
    # In F-Droid Index V2, each /diff/{ts}.json contains all cumulative changes from {ts} to current.
    if last_timestamp is None or last_timestamp <= oldest_available_ts:
        logger.info(f"Using oldest available diff {oldest_available_ts} for backfill (last recorded: {last_timestamp}).")
        target_ts = oldest_available_ts
    else:
        # Since available_timestamps is sorted ascending, iterate in reverse to find the largest ts <= last_timestamp
        target_ts = next(ts for ts in reversed(available_timestamps) if ts <= last_timestamp)
        logger.info(f"Target diff base timestamp: {target_ts} (last recorded: {last_timestamp})")

    diff_info = diffs.get(str(target_ts))
    if not diff_info:
        logger.warning(f"Diff metadata for timestamp {target_ts} not found.")
        return new_apps

    diff_name = diff_info.get("name", f"/diff/{target_ts}.json")
    diff_url = f"{repo_info['base_url']}{diff_name}"
    expected_sha256 = diff_info.get("sha256")

    try:
        logger.info(f"Downloading diff: {diff_url}")
        resp = fetch_with_retry(diff_url)
        if expected_sha256 and not verify_sha256(resp.content, expected_sha256):
            logger.error(f"Skipping diff {diff_url} due to SHA-256 mismatch")
            return new_apps

        diff_data = resp.json()
        apps_from_diff = parse_diff_packages(repo_key, repo_info, diff_data, known_apps, current_time_str)
        logger.info(f"Found {len(apps_from_diff)} new app(s) in diff {target_ts}")
        new_apps.extend(apps_from_diff)

        # Successfully applied cumulative diff to latest index; advance timestamp to latest available
        save_timestamp(latest_available_ts, repo_info["timestamp_file"])
    except Exception as e:
        logger.error(f"Error processing diff {diff_url}: {e}")

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
            categories = [cat.text for cat in item_elem.findall("category") if cat.text]
            enclosure_elem = item_elem.find("enclosure")
            enclosure = enclosure_elem.get("url") if enclosure_elem is not None else None

            items.append({
                "title": title,
                "link": link,
                "guid": guid,
                "pubDate": pub_date,
                "description": description,
                "categories": categories,
                "enclosure": enclosure,
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

        for cat in item.get("categories", []):
            if cat:
                ET.SubElement(item_elem, "category").text = cat

        if item.get("enclosure"):
            ET.SubElement(item_elem, "enclosure", {
                "url": item["enclosure"],
                "length": "0",
                "type": "image/png",
            })

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

    max_items = max(DEFAULT_MAX_ITEMS, len(new_apps_all))
    if len(new_apps_all) > DEFAULT_MAX_ITEMS:
        logger.info(f"Batch new apps ({len(new_apps_all)}) exceeds default limit ({DEFAULT_MAX_ITEMS}). Expanding feed retention to {max_items} items.")
    final_items = combined_items[:max_items]

    if new_apps_all or not os.path.exists(FEED_FILE):
        generate_feed_xml(final_items)
    else:
        logger.info("No new apps found and feed.xml exists; skipping feed regeneration.")


if __name__ == "__main__":
    main()
