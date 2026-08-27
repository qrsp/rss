import os
import sys
import unittest
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generate_rss import (
    parse_commit_title_app,
    parse_license,
    parse_homepage,
    load_known_apps,
    append_known_apps,
    update_feed_xml,
)

class TestGenerateRSS(unittest.TestCase):

    def test_parse_commit_title_app(self):
        self.assertEqual(parse_commit_title_app("telegram: Update to version 7.1.2"), "telegram")
        self.assertEqual(parse_commit_title_app("host-editor@1.6: Fix hash"), "host-editor@1.6")
        self.assertEqual(parse_commit_title_app("newapp: Add version 1.0.0"), "newapp")
        self.assertIsNone(parse_commit_title_app("ci: add lint-pr workflow"))
        self.assertIsNone(parse_commit_title_app("(chore): revert endings change"))
        self.assertIsNone(parse_commit_title_app(""))

    def test_parse_license(self):
        self.assertEqual(parse_license("MIT"), "MIT")
        self.assertEqual(parse_license({"identifier": "Apache-2.0", "url": "https://..."}), "Apache-2.0")
        self.assertEqual(parse_license(None), "Unknown")

    def test_parse_homepage(self):
        self.assertEqual(parse_homepage("https://example.com", "fallback"), "https://example.com")
        self.assertEqual(parse_homepage(["https://example.com"], "fallback"), "https://example.com")
        self.assertEqual(parse_homepage("", "https://fallback.com"), "https://fallback.com")

    def test_known_apps_load_and_append(self):
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
            f.write("app1\napp2\n")
            temp_path = f.name

        try:
            apps_set, apps_list = load_known_apps(temp_path)
            self.assertIn("app1", apps_set)
            self.assertIn("app2", apps_set)
            self.assertEqual(len(apps_set), 2)

            append_known_apps(["app3", "app4"], temp_path)
            apps_set2, _ = load_known_apps(temp_path)
            self.assertIn("app3", apps_set2)
            self.assertIn("app4", apps_set2)
            self.assertEqual(len(apps_set2), 4)
        finally:
            os.remove(temp_path)

    def test_update_feed_xml_limit(self):
        with tempfile.NamedTemporaryFile("w+", delete=False, encoding="utf-8") as f:
            temp_path = f.name

        try:
            # Case 1: new_items <= 200 (e.g. 50 new, limit = 200)
            items_50 = [{"title": f"App {i}", "link": f"http://{i}", "description": "", "pubDate": "", "guid": f"g-{i}"} for i in range(50)]
            update_feed_xml(items_50, temp_path)

            tree = ET.parse(temp_path)
            root = tree.getroot()
            channel = root.find("channel")
            self.assertEqual(len(channel.findall("item")), 50)

            # Case 2: new_items > 200 (e.g. 250 new -> limit should be 500)
            items_250 = [{"title": f"NewApp {i}", "link": f"http://{i}", "description": "", "pubDate": "", "guid": f"new-g-{i}"} for i in range(250)]
            update_feed_xml(items_250, temp_path)

            tree = ET.parse(temp_path)
            root = tree.getroot()
            channel = root.find("channel")
            # Combined 250 + 50 = 300, cap is 500, so all 300 items kept
            self.assertEqual(len(channel.findall("item")), 300)

            # Case 3: 600 items -> cap 500
            items_600 = [{"title": f"BigApp {i}", "link": f"http://{i}", "description": "", "pubDate": "", "guid": f"big-g-{i}"} for i in range(250)]
            update_feed_xml(items_600, temp_path)

            tree = ET.parse(temp_path)
            root = tree.getroot()
            channel = root.find("channel")
            self.assertEqual(len(channel.findall("item")), 500)

        finally:
            os.remove(temp_path)

if __name__ == "__main__":
    unittest.main()
