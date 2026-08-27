#!/usr/bin/env python3
"""
Morphe Patch RSS Feed Generator
Fetches whats-new.json & bundles.json from Morphe API,
detects new apps (repo/bundle:package_name) in the top 2 date groups,
updates known_apps.txt and generates/updates feed.xml with RSS 2.0 specs.
"""

import os
import json
import urllib.request
import html
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from xml.dom import minidom
from email.utils import formatdate

WHATS_NEW_URL = "https://awesome-morphe.vercel.app/whats-new.json"
BUNDLES_URL = "https://awesome-morphe.vercel.app/bundles.json"
KNOWN_APPS_FILE = "known_apps.txt"
FEED_FILE = "feed.xml"

DEFAULT_MAX_ITEMS = 200
EXPANDED_MAX_ITEMS = 500


def fetch_json(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "MorpheRSSFeedGenerator/1.0"}
    )
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_date_to_rfc822(date_str):
    """
    Parses date strings like 'August 24, 2026' into RFC 822 formatted string.
    """
    if not date_str:
        return formatdate(usegmt=True)
    try:
        dt = datetime.strptime(date_str, "%B %d, %Y").replace(tzinfo=timezone.utc)
        return formatdate(dt.timestamp(), usegmt=True)
    except Exception:
        return formatdate(usegmt=True)


def load_known_apps():
    if not os.path.exists(KNOWN_APPS_FILE):
        return set()
    with open(KNOWN_APPS_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_known_apps(new_apps, existing_apps):
    # Append new apps preserving order
    with open(KNOWN_APPS_FILE, "a", encoding="utf-8") as f:
        for app_id in new_apps:
            f.write(f"{app_id}\n")


def build_item_html(repo_name, package_name, app_data, bundle_info, app_info):
    app_name = app_info.get("name") or package_name
    icon_url = app_info.get("iconUrl", "")
    category = app_info.get("category", "")
    app_desc = app_info.get("description", "")
    patches = app_data.get("patches", [])
    
    html_parts = ['<div style="font-family: sans-serif;">']
    
    # 1. Lead with App Description first for quick preview in RSS readers
    if app_desc:
        html_parts.append(f'<p style="font-size: 1.05em; font-weight: 500;">{html.escape(app_desc)}</p>')
    
    # 2. App Icon & Header
    if icon_url:
        html_parts.append(f'<img src="{html.escape(icon_url)}" width="48" height="48" style="float: left; margin-right: 12px; border-radius: 8px;" alt="{html.escape(app_name)}" />')
    
    html_parts.append(f'<h2><a href="https://awesome-morphe.vercel.app/?app={html.escape(package_name)}#whats-new">{html.escape(app_name)}</a></h2>')
    
    # 3. Package Name & Category
    meta_info = [f'<strong>Package:</strong> <code>{html.escape(package_name)}</code>']
    if category:
        meta_info.append(f'<strong>Category:</strong> {html.escape(category)}')
    html_parts.append(f'<p>{" | ".join(meta_info)}</p>')
    
    html_parts.append('<hr />')
    
    # 4. Patches List (without bundle title or stars)
    html_parts.append(f'<h4>Patches ({len(patches)}):</h4>')
    if patches:
        html_parts.append('<ul>')
        for patch in patches:
            html_parts.append(f'<li>{html.escape(patch)}</li>')
        html_parts.append('</ul>')
    else:
        html_parts.append('<p>No specific patch names listed.</p>')
        
    html_parts.append('</div>')
    
    return "".join(html_parts)


def parse_existing_feed():
    if not os.path.exists(FEED_FILE):
        return []
    try:
        tree = ET.parse(FEED_FILE)
        root = tree.getroot()
        channel = root.find("channel")
        if channel is None:
            return []
        items = channel.findall("item")
        return items
    except Exception as e:
        print(f"Warning: Failed to parse existing feed.xml: {e}")
        return []


def create_item_element(repo_name, package_name, pub_date_rfc, app_data, bundle_info, app_info):
    app_name = app_info.get("name") or package_name
    unique_id = f"{repo_name}:{package_name}"
    
    item = ET.Element("item")
    
    title_elem = ET.SubElement(item, "title")
    title_elem.text = app_name
    
    link_elem = ET.SubElement(item, "link")
    link_elem.text = f"https://awesome-morphe.vercel.app/?app={package_name}#whats-new"
    
    guid_elem = ET.SubElement(item, "guid", attrib={"isPermaLink": "false"})
    guid_elem.text = unique_id
    
    pub_date_elem = ET.SubElement(item, "pubDate")
    pub_date_elem.text = pub_date_rfc
    
    desc_elem = ET.SubElement(item, "description")
    desc_elem.text = build_item_html(repo_name, package_name, app_data, bundle_info, app_info)
    
    return item


def save_feed(items):
    rss = ET.Element("rss", attrib={"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    
    title = ET.SubElement(channel, "title")
    title.text = "Morphe Patch RSS Feed"
    
    link = ET.SubElement(channel, "link")
    link.text = "https://awesome-morphe.vercel.app/"
    
    description = ET.SubElement(channel, "description")
    description.text = "RSS feed for newly listed apps and patches on Morphe"
    
    language = ET.SubElement(channel, "language")
    language.text = "en-us"
    
    last_build = ET.SubElement(channel, "lastBuildDate")
    last_build.text = formatdate(usegmt=True)
    
    for item in items:
        channel.append(item)
        
    xml_str = ET.tostring(rss, encoding="utf-8")
    parsed = minidom.parseString(xml_str)
    pretty_xml = parsed.toprettyxml(indent="  ", encoding="utf-8")
    
    with open(FEED_FILE, "wb") as f:
        f.write(pretty_xml)


def main():
    print("Fetching whats-new.json & bundles.json...")
    whats_new_data = fetch_json(WHATS_NEW_URL)
    bundles_data = fetch_json(BUNDLES_URL)
    
    bundles_dict = {b["repo"]: b for b in bundles_data.get("bundles", []) if isinstance(b, dict) and "repo" in b}
    store_dict = bundles_data.get("store", {})
    
    known_apps = load_known_apps()
    new_apps_list = []
    new_items = []
    
    # Process top 2 date groups
    top_date_groups = whats_new_data[:2] if isinstance(whats_new_data, list) else []
    
    for group in top_date_groups:
        date_str = group.get("date", "")
        pub_date_rfc = parse_date_to_rfc822(date_str)
        bundles_in_group = group.get("bundles", {})
        
        for repo_name, bundle_data in bundles_in_group.items():
            bundle_info = bundles_dict.get(repo_name, {"name": repo_name, "repoDescription": ""})
            apps_dict = bundle_data.get("apps", {})
            
            for package_name, app_data in apps_dict.items():
                unique_id = f"{repo_name}:{package_name}"
                if unique_id in known_apps or unique_id in new_apps_list:
                    continue
                
                app_info = store_dict.get(package_name, {})
                item_elem = create_item_element(repo_name, package_name, pub_date_rfc, app_data, bundle_info, app_info)
                
                new_apps_list.append(unique_id)
                new_items.append(item_elem)
                
    print(f"Found {len(new_items)} new app entries.")
    
    if not new_items and os.path.exists(FEED_FILE):
        print("No new apps found. Feed is up to date.")
        return
        
    existing_items = parse_existing_feed()
    all_items = new_items + existing_items
    
    # Determine max retention limit
    max_limit = EXPANDED_MAX_ITEMS if len(new_items) > DEFAULT_MAX_ITEMS else DEFAULT_MAX_ITEMS
    print(f"Max retention limit set to {max_limit}. Total items before pruning: {len(all_items)}")
    
    retained_items = all_items[:max_limit]
    
    save_feed(retained_items)
    save_known_apps(new_apps_list, known_apps)
    
    print(f"Successfully generated {FEED_FILE} with {len(retained_items)} items and updated {KNOWN_APPS_FILE}.")


if __name__ == "__main__":
    main()
