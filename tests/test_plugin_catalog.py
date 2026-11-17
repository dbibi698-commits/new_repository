"""tests/test_plugin_catalog.py — the 500-plugin catalog (core/plugin_catalog.py)
and its loader API (core/plugin_loader.list_catalog).

Run from ~/workspace/mark-lvii:
    python3 tests/test_plugin_catalog.py
    python3 -m unittest discover -s tests -v

Stdlib only. No network, no Qt, no config writes: the "tool exists" check
re-derives the real tool inventory from the codebase itself (plugin PLUGIN
names, actions/ TOOL names, main.py TOOL_DECLARATIONS, public service
functions in core/connectors.py), so a catalog entry pointing at a tool that
does not exist fails here instead of silently shipping a dead Plugin
Settings row. The enable-state test monkeypatches get_plugin_enabled rather
than touching config/api_keys.json.
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import plugin_loader  # noqa: E402
from core.plugin_catalog import (  # noqa: E402
    CATEGORIES,
    CATALOG,
    catalog_key,
    catalog_stats,
    search_catalog,
)

ROOT = Path(__file__).resolve().parent.parent

_REQUIRED_KEYS = {"name", "description", "trigger", "tool", "category"}


def _real_tools() -> set[str]:
    """Every real tool/plugin/connector-function name in this codebase.

    Sources (mirrors how the catalog was built):
      * plugins/*.py PLUGIN["name"] (skips _-prefixed helpers/templates)
      * actions/*.py TOOL["name"]
      * main.py TOOL_DECLARATIONS ("name" fields)
      * core/connectors.py public service functions (github_*/whatsapp_*/
        youtube_*/facebook_*/instagram_*/drive_* + connectors_status).
    Private helpers (_-prefixed) and the config accessor get_token are NOT
    tools and are deliberately excluded.
    """
    tools: set[str] = set()
    for path in (ROOT / "plugins").glob("*.py"):
        if path.name.startswith("_"):
            continue
        m = re.search(r'"name":\s*"([^"]+)"', path.read_text(errors="ignore"))
        if m:
            tools.add(m.group(1))
    for path in (ROOT / "actions").glob("*.py"):
        m = re.search(r'"name":\s*"([^"]+)"', path.read_text(errors="ignore"))
        if m:
            tools.add(m.group(1))
    tools.update(re.findall(r'"name":\s*"([a-z_0-9]+)"',
                            (ROOT / "main.py").read_text(errors="ignore")))
    conn = (ROOT / "core" / "connectors.py").read_text(errors="ignore")
    for m in re.findall(r"^def ([a-z_0-9]+)\(", conn, re.M):
        if (m.startswith(("github_", "whatsapp_", "youtube_", "facebook_",
                          "instagram_", "drive_"))
                or m == "connectors_status"):
            tools.add(m)
    return tools


class TestCatalogShape(unittest.TestCase):
    def test_exactly_500_entries(self):
        self.assertEqual(len(CATALOG), 500, len(CATALOG))

    def test_required_keys_and_non_empty_values(self):
        for e in CATALOG:
            self.assertEqual(set(e.keys()), _REQUIRED_KEYS, e)
            for k in _REQUIRED_KEYS:
                self.assertIsInstance(e[k], str, e)
                self.assertTrue(e[k].strip(), e)

    def test_names_unique(self):
        names = [e["name"] for e in CATALOG]
        self.assertEqual(len(set(names)), 500)

    def test_triggers_unique(self):
        triggers = [e["trigger"] for e in CATALOG]
        self.assertEqual(len(set(triggers)), 500)

    def test_categories_known(self):
        for e in CATALOG:
            self.assertIn(e["category"], CATEGORIES, e)

    def test_every_tool_exists_in_codebase(self):
        allowed = _real_tools()
        self.assertGreater(len(allowed), 50, "tool inventory looks empty")
        unmapped = [e for e in CATALOG if e["tool"] not in allowed]
        self.assertEqual(unmapped, [],
                         f"{len(unmapped)} entries map to no real tool: "
                         f"{unmapped[:5]}")

    def test_every_category_has_entries(self):
        stats = catalog_stats()
        for cat in CATEGORIES:
            self.assertGreater(stats["categories"].get(cat, 0), 0, cat)


class TestSearchAndStats(unittest.TestCase):
    def test_empty_query_returns_all_500(self):
        self.assertEqual(len(search_catalog("")), 500)
        self.assertEqual(len(search_catalog("   ")), 500)
        self.assertEqual(len(search_catalog(None)), 500)

    def test_nonsense_query_returns_zero(self):
        self.assertEqual(search_catalog("zxqvkj"), [])

    def test_search_is_case_insensitive_substring(self):
        hits = search_catalog("YOUTUBE")
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits, search_catalog("youtube"))
        for e in hits:
            hay = f"{e['name']} {e['description']} {e['trigger']}".lower()
            self.assertIn("youtube", hay, e)

    def test_search_returns_correct_subset(self):
        hits = search_catalog("voice play music")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["name"], "Voice Play music")

    def test_stats_add_up(self):
        stats = catalog_stats()
        self.assertEqual(stats["total"], 500)
        self.assertEqual(sum(stats["categories"].values()), 500)
        self.assertEqual(sum(stats["tools"].values()), 500)
        self.assertEqual(set(stats["categories"]), set(CATEGORIES))


class TestCatalogKey(unittest.TestCase):
    def test_key_scheme(self):
        self.assertEqual(catalog_key("Voice Play music"),
                         "catalog_voice_play_music")
        self.assertTrue(catalog_key("Muse Bridge Ask Muse task")
                        .startswith("catalog_"))

    def test_keys_unique(self):
        keys = [catalog_key(e["name"]) for e in CATALOG]
        self.assertEqual(len(set(keys)), 500)


class TestListCatalog(unittest.TestCase):
    def test_module_level_returns_all_with_enable_state(self):
        rows = plugin_loader.list_catalog("")
        self.assertEqual(len(rows), 500)
        for row in rows:
            self.assertEqual(set(row.keys()),
                             _REQUIRED_KEYS | {"key", "enabled"}, row)
            self.assertTrue(row["key"].startswith("catalog_"), row)
            self.assertIs(row["enabled"], True, row)  # default ON (opt-out)

    def test_module_level_search_filters(self):
        self.assertEqual(len(plugin_loader.list_catalog("zxqvkj")), 0)
        hits = plugin_loader.list_catalog("github")
        self.assertGreater(len(hits), 0)
        self.assertLess(len(hits), 500)

    def test_registry_method_matches_module_level(self):
        registry = plugin_loader.PluginRegistry({}, print)
        self.assertEqual(registry.list_catalog(""),
                         plugin_loader.list_catalog(""))
        self.assertEqual(registry.list_catalog("mood"),
                         plugin_loader.list_catalog("mood"))

    def test_enable_state_is_live(self):
        # Flip one entry off via the same lookup list_catalog uses, without
        # touching the real config file.
        target = CATALOG[0]
        key = catalog_key(target["name"])
        orig = plugin_loader.get_plugin_enabled
        try:
            plugin_loader.get_plugin_enabled = (
                lambda name: False if name == key else orig(name))
            rows = {r["key"]: r for r in plugin_loader.list_catalog("")}
            self.assertIs(rows[key]["enabled"], False)
            self.assertEqual(sum(1 for r in rows.values() if r["enabled"]),
                             499)
        finally:
            plugin_loader.get_plugin_enabled = orig


if __name__ == "__main__":
    unittest.main()
