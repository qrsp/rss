#!/usr/bin/env python3
import os
import sys
import json
import xml.etree.ElementTree as ET
from xml.dom import minidom
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime

BUCKETS = [
    {"name": "Main", "owner": "ScoopInstaller", "repo": "Main"},
    {"name": "Extras", "owner": "ScoopInstaller", "repo": "Extras"},
    {"name": "Nonportable", "owner": "ScoopInstaller", "repo": "Nonportable"},
    {"name": "Nirsoft", "owner": "ScoopInstaller", "repo": "Nirsoft"},
]

KNOWN_APPS_FILE = "known_apps.txt"
FEED_FILE = "feed.xml"

def get_headers():
    headers = {"User-Agent": "Scoop-RSS-Generator/1.0"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

def make_request(url):
    req = urllib.request.Request(url, headers=get_headers())
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def fetch_raw_content(url):
    req = urllib.request.Request(url, headers=get_headers())
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode("utf-8")

def parse_commit_title_app(title):
    """Extract candidate app name from commit title (e.g., 'telegram: Update...' -> 'telegram')."""
    if not title:
        return None
    first_part = title.split(":")[0].strip()
    if not first_part or " " in first_part or first_part.startswith("(") or first_part.lower() in ("ci", "chore", "merge", "fix"):
        return None
    return first_part

def parse_license(license_field):
    if not license_field:
        return "Unknown"
    if isinstance(license_field, str):
        return license_field
    if isinstance(license_field, dict):
        return license_field.get("identifier") or license_field.get("url") or str(license_field)
    return str(license_field)

def parse_homepage(homepage_field, fallback_url):
    if not homepage_field:
        return fallback_url
    if isinstance(homepage_field, list) and len(homepage_field) > 0:
        return homepage_field[0]
    if isinstance(homepage_field, str) and homepage_field.strip():
        return homepage_field.strip()
    return fallback_url

def parse_iso_date(date_str):
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return format_datetime(dt)
    except Exception:
        return format_datetime(datetime.now(timezone.utc))

def load_known_apps(filepath):
    if not os.path.exists(filepath):
        return set(), []
    with open(filepath, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    return set(lines), lines

def process_buckets(known_apps_set, hours_back=25):
    since_dt = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    iso_since = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    new_rss_items = []
    new_apps_added = []

    for bucket in BUCKETS:
        bucket_name = bucket["name"]
        owner = bucket["owner"]
        repo = bucket["repo"]
        print(f"Checking bucket: {bucket_name}...", flush=True)

        commits_url = f"https://api.github.com/repos/{owner}/{repo}/commits?since={iso_since}&per_page=100"
        try:
            commits = make_request(commits_url)
        except Exception as e:
            print(f"Error fetching commits for {bucket_name}: {e}", file=sys.stderr)
            continue

        for commit_obj in commits:
            sha = commit_obj.get("sha")
            commit_info = commit_obj.get("commit", {})
            message = commit_info.get("message", "")
            title = message.splitlines()[0] if message else ""
            commit_date_str = commit_info.get("committer", {}).get("date") or commit_info.get("author", {}).get("date") or ""

            candidate_app = parse_commit_title_app(title)

            # Fast check: if candidate app name is already known, skip commit detail request
            if candidate_app and candidate_app in known_apps_set:
                continue

            # Candidate app is unknown or couldn't be unambiguously extracted; fetch commit details
            detail_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}"
            try:
                detail = make_request(detail_url)
            except Exception as e:
                print(f"Error fetching commit detail {sha} for {bucket_name}: {e}", file=sys.stderr)
                continue

            files = detail.get("files", [])
            for file_info in files:
                filename = file_info.get("filename", "")
                status = file_info.get("status", "")

                # Only check json files in bucket/ or root
                if status in ("added", "modified") and filename.endswith(".json") and not filename.startswith("."):
                    app_name = os.path.basename(filename)[:-5]

                    if app_name in known_apps_set:
                        continue

                    # Download raw manifest
                    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{sha}/{filename}"
                    github_blob_url = f"https://github.com/{owner}/{repo}/blob/master/{filename}"

                    try:
                        raw_json_str = fetch_raw_content(raw_url)
                        manifest = json.loads(raw_json_str)
                    except Exception as e:
                        print(f"Error downloading/parsing manifest {raw_url}: {e}", file=sys.stderr)
                        manifest = {}

                    version = manifest.get("version", "Unknown")
                    description = manifest.get("description", "No description available.")
                    homepage = parse_homepage(manifest.get("homepage"), github_blob_url)
                    license_info = parse_license(manifest.get("license"))

                    pub_date = parse_iso_date(commit_date_str) if commit_date_str else format_datetime(datetime.now(timezone.utc))

                    item = {
                        "title": f"[{bucket_name}] {app_name} v{version}",
                        "link": homepage,
                        "description": (
                            f"<p><strong>App:</strong> {app_name}</p>"
                            f"<p><strong>Bucket:</strong> {bucket_name}</p>"
                            f"<p><strong>Version:</strong> {version}</p>"
                            f"<p><strong>License:</strong> {license_info}</p>"
                            f"<p><strong>Description:</strong> {description}</p>"
                            f'<p><a href="{github_blob_url}">View Manifest on GitHub</a></p>'
                        ),
                        "pubDate": pub_date,
                        "guid": f"scoop-{bucket_name}-{app_name}-{version}",
                    }

                    new_rss_items.append(item)
                    new_apps_added.append(app_name)
                    known_apps_set.add(app_name)

    return new_rss_items, new_apps_added

def update_feed_xml(new_items, feed_path=FEED_FILE):
    existing_items = []

    if os.path.exists(feed_path) and os.path.getsize(feed_path) > 0:
        try:
            tree = ET.parse(feed_path)
            root = tree.getroot()
            channel = root.find("channel")
            if channel is not None:
                for item_node in channel.findall("item"):
                    title = item_node.findtext("title", "")
                    link = item_node.findtext("link", "")
                    description = item_node.findtext("description", "")
                    pubDate = item_node.findtext("pubDate", "")
                    guid = item_node.findtext("guid", "")
                    existing_items.append({
                        "title": title,
                        "link": link,
                        "description": description,
                        "pubDate": pubDate,
                        "guid": guid,
                    })
        except Exception as e:
            print(f"Error parsing existing feed.xml: {e}", file=sys.stderr)

    # Determine max items cap based on rule: default 200, 500 if new_items > 200
    new_apps_count = len(new_items)
    max_limit = 500 if new_apps_count > 200 else 200

    combined_items = new_items + existing_items

    # De-duplicate items by guid if necessary, while preserving order
    seen_guids = set()
    unique_items = []
    for item in combined_items:
        guid = item.get("guid") or item.get("title")
        if guid not in seen_guids:
            seen_guids.add(guid)
            unique_items.append(item)

    final_items = unique_items[:max_limit]

    # Generate XML
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    c_title = ET.SubElement(channel, "title")
    c_title.text = "Scoop Official Buckets - New Apps"

    c_link = ET.SubElement(channel, "link")
    c_link.text = "https://github.com/ScoopInstaller"

    c_desc = ET.SubElement(channel, "description")
    c_desc.text = "RSS feed for newly added software applications in official Scoop buckets."

    c_build = ET.SubElement(channel, "lastBuildDate")
    c_build.text = format_datetime(datetime.now(timezone.utc))

    for item_data in final_items:
        i_node = ET.SubElement(channel, "item")

        t_node = ET.SubElement(i_node, "title")
        t_node.text = item_data.get("title", "")

        l_node = ET.SubElement(i_node, "link")
        l_node.text = item_data.get("link", "")

        d_node = ET.SubElement(i_node, "description")
        d_node.text = item_data.get("description", "")

        p_node = ET.SubElement(i_node, "pubDate")
        p_node.text = item_data.get("pubDate", "")

        g_node = ET.SubElement(i_node, "guid", isPermaLink="false")
        g_node.text = item_data.get("guid", "")

    # Pretty print XML
    rough_string = ET.tostring(rss, encoding="utf-8")
    reparsed = minidom.parseString(rough_string)
    pretty_xml = reparsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")

    # Clean up empty lines created by minidom
    clean_xml_lines = [line for line in pretty_xml.splitlines() if line.strip()]
    formatted_xml = "\n".join(clean_xml_lines) + "\n"

    with open(feed_path, "w", encoding="utf-8") as f:
        f.write(formatted_xml)

def append_known_apps(new_apps, filepath=KNOWN_APPS_FILE):
    if not new_apps:
        return
    with open(filepath, "a", encoding="utf-8") as f:
        for app in new_apps:
            f.write(f"{app}\n")

def main():
    print("Loading known apps...")
    known_apps_set, known_apps_list = load_known_apps(KNOWN_APPS_FILE)
    print(f"Loaded {len(known_apps_set)} known apps.")

    print("Checking official Scoop buckets for new apps...")
    new_rss_items, new_apps_added = process_buckets(known_apps_set)

    print(f"Found {len(new_apps_added)} new app(s).")
    if new_apps_added:
        print("New apps:", ", ".join(new_apps_added))

    print("Updating feed.xml...")
    update_feed_xml(new_rss_items)

    print("Appending new apps to known_apps.txt...")
    append_known_apps(new_apps_added)

    print("Done!")

if __name__ == "__main__":
    main()
