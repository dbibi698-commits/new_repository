"""tests/test_ui_data_protection.py — Settings Memory box backend, assistant
logos, and the data-protection (never delete) scheme in
memory/config_manager.py.

Run from ~/workspace/mark-lvii:
    python3 tests/test_ui_data_protection.py
    python3 -m unittest discover -s tests -v

Stdlib only. The config paths are redirected at a scratch folder per test,
so the real config/api_keys.json is never touched. The Qt overlays that
USE this backend (gui/overlays.py) cannot be instantiated here — PyQt6 is
not installed on this Linux VM — so they are verified with py_compile +
AST checks, not imported.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memory import config_manager as cm  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._orig_dir = cm.CONFIG_DIR
        self._orig_file = cm.CONFIG_FILE
        cm.CONFIG_DIR = Path(self.tmp.name) / "config"
        cm.CONFIG_FILE = cm.CONFIG_DIR / "api_keys.json"
        cm.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._seed({"gemini_api_key": "AIza-test-key-1234567890",
                    "assistant_name": "JARVIS"})

    def tearDown(self):
        cm.CONFIG_DIR = self._orig_dir
        cm.CONFIG_FILE = self._orig_file
        self.tmp.cleanup()

    def _seed(self, data: dict):
        """Write `data` as the config, with no backup of a previous state."""
        cm.CONFIG_FILE.write_text(json.dumps(data, indent=4),
                                  encoding="utf-8")

    def _read_raw(self) -> dict:
        return json.loads(cm.CONFIG_FILE.read_text(encoding="utf-8"))

    def _backups(self):
        d = cm.CONFIG_DIR / "backups"
        if not d.exists():
            return []
        return sorted(d.glob("config-*.json"))


class TestBackupOnSave(_Base):
    def test_backup_created_on_save(self):
        self.assertEqual(self._backups(), [])
        cm.update_config(user_name="Boss")
        backs = self._backups()
        self.assertEqual(len(backs), 1, backs)
        saved = json.loads(backs[0].read_text(encoding="utf-8"))
        self.assertEqual(saved["assistant_name"], "JARVIS")
        self.assertNotIn("user_name", saved)  # backup is the PRE-save state
        self.assertEqual(self._read_raw()["user_name"], "Boss")

    def test_corrupt_current_file_is_not_backed_up(self):
        cm.CONFIG_FILE.write_text("{not json", encoding="utf-8")
        cm.update_config(user_name="Boss")  # _read_for_write restores/empties
        self.assertEqual(self._backups(), [])


class TestAutoRestore(_Base):
    def _make_backup(self):
        cm.update_config(user_name="Boss")  # backs up the seeded config
        self.assertEqual(len(self._backups()), 1)

    def test_corrupt_config_auto_restores(self):
        self._make_backup()
        cm.CONFIG_FILE.write_text("{broken json,,,", encoding="utf-8")
        data = cm.load_api_keys()
        self.assertEqual(data.get("assistant_name"), "JARVIS")
        self.assertEqual(data.get("gemini_api_key"),
                         "AIza-test-key-1234567890")
        self.assertEqual(self._read_raw(), data)  # file itself is valid again

    def test_empty_config_auto_restores(self):
        self._make_backup()
        cm.CONFIG_FILE.write_text("", encoding="utf-8")
        data = cm.load_api_keys()
        self.assertEqual(data.get("assistant_name"), "JARVIS")

    def test_empty_dict_config_auto_restores(self):
        self._make_backup()
        cm.CONFIG_FILE.write_text("{}", encoding="utf-8")
        data = cm.load_api_keys()
        self.assertEqual(data.get("assistant_name"), "JARVIS")

    def test_corrupt_config_without_backup_returns_empty(self):
        cm.CONFIG_FILE.write_text("{broken", encoding="utf-8")
        self.assertEqual(cm.load_api_keys(), {})

    def test_restore_skips_corrupt_backup(self):
        # Two saves -> two backups; corrupt the newest, the older must win.
        cm.update_config(user_name="Boss")
        cm.update_config(user_name="Boss2")
        backs = sorted((cm.CONFIG_DIR / "backups").glob("config-*.json"),
                       key=lambda p: p.stat().st_mtime)
        self.assertEqual(len(backs), 2)
        backs[-1].write_text("{broken", encoding="utf-8")
        cm.CONFIG_FILE.write_text("{also broken", encoding="utf-8")
        data = cm.load_api_keys()
        # The older backup holds the seeded config (no user_name yet).
        self.assertEqual(data.get("assistant_name"), "JARVIS")
        self.assertNotIn("user_name", data)


class TestBackupPruning(_Base):
    def test_pruning_keeps_20(self):
        for i in range(25):
            cm.update_config(user_name=f"Boss{i}")
            time.sleep(0.01)  # distinct mtimes, so "newest" is well-defined
        backs = self._backups()
        self.assertEqual(len(backs), 20, [b.name for b in backs])
        newest = max(backs, key=lambda p: p.stat().st_mtime)
        saved = json.loads(newest.read_text(encoding="utf-8"))
        # The newest backup holds the state before the LAST save (Boss23).
        self.assertEqual(saved.get("user_name"), "Boss23")
        self.assertEqual(cm.list_config_backups()[0], newest.name)


class TestMemories(_Base):
    def test_add_search_delete_round_trip(self):
        self.assertEqual(cm.get_memories(), [])
        a = cm.add_memory("Boss likes tea at 7am")
        b = cm.add_memory("Call Amma on Sunday")
        c = cm.add_memory("Tea is best with ginger")
        self.assertEqual(len(cm.get_memories()), 3)
        self.assertEqual(cm.search_memories("tea"), [a, c])
        self.assertEqual(cm.search_memories("TEA"), [a, c])
        self.assertEqual(cm.search_memories("sunday"), [b])
        self.assertEqual(cm.search_memories(""), cm.get_memories())
        self.assertTrue(cm.delete_memory(a["id"]))
        self.assertEqual([m["id"] for m in cm.get_memories()],
                         [b["id"], c["id"]])
        self.assertTrue(cm.delete_memory(0))  # delete by index
        self.assertEqual([m["id"] for m in cm.get_memories()], [c["id"]])
        self.assertFalse(cm.delete_memory("no-such-id"))
        self.assertFalse(cm.delete_memory(99))

    def test_add_blank_memory_is_ignored(self):
        self.assertIsNone(cm.add_memory("   "))
        self.assertEqual(cm.get_memories(), [])

    def test_memories_survive_other_saves(self):
        cm.add_memory("Never forget this")
        cm.update_config(user_name="Boss")
        self.assertEqual(len(cm.get_memories()), 1)


class TestProtectionToggle(_Base):
    def test_protection_defaults_on(self):
        self.assertTrue(cm.get_data_protection())

    def test_bulk_clear_blocked_without_confirm(self):
        cm.add_memory("one")
        cm.add_memory("two")
        self.assertFalse(cm.clear_memories())
        self.assertEqual(len(cm.get_memories()), 2)
        self.assertFalse(cm.clear_memories(confirm=False))
        self.assertEqual(len(cm.get_memories()), 2)

    def test_bulk_clear_allowed_with_confirm(self):
        cm.add_memory("one")
        self.assertTrue(cm.clear_memories(confirm=True))
        self.assertEqual(cm.get_memories(), [])

    def test_bulk_clear_allowed_when_toggle_off(self):
        cm.add_memory("one")
        cm.save_data_protection(False)
        self.assertFalse(cm.get_data_protection())
        self.assertTrue(cm.clear_memories())
        self.assertEqual(cm.get_memories(), [])
        cm.save_data_protection(True)  # leave the guard on again

    def test_bulk_clear_guard_helper(self):
        self.assertFalse(cm.bulk_clear_guard("todos", confirm=False))
        self.assertTrue(cm.bulk_clear_guard("todos", confirm=True))
        cm.save_data_protection(False)
        self.assertTrue(cm.bulk_clear_guard("todos", confirm=False))


class TestAssistantLogo(_Base):
    def test_logo_save_get_round_trip(self):
        self.assertEqual(cm.get_assistant_logo(), "")
        self.assertTrue(cm.save_assistant_logo("logo_03_gold_bolt.png"))
        self.assertEqual(cm.get_assistant_logo(), "logo_03_gold_bolt.png")
        self.assertTrue(cm.save_assistant_logo(""))  # back to default look
        self.assertEqual(cm.get_assistant_logo(), "")

    def test_unknown_logo_rejected(self):
        cm.save_assistant_logo("logo_01_cyan_star.png")
        self.assertFalse(cm.save_assistant_logo("logo_99_nope.png"))
        self.assertEqual(cm.get_assistant_logo(), "logo_01_cyan_star.png")

    def test_logo_list_has_12(self):
        self.assertEqual(len(cm.ASSISTANT_LOGOS), 12)
        self.assertEqual(len(set(cm.ASSISTANT_LOGOS)), 12)

    def test_logo_path_resolves(self):
        # Logos live in the real assets/logos/ folder, not the scratch dir.
        real = Path(cm.BASE_DIR) / "assets" / "logos"
        for name in cm.ASSISTANT_LOGOS:
            p = real / name
            self.assertTrue(p.is_file(), str(p))
        cm.save_assistant_logo("logo_07_blue_circle.png")
        self.assertEqual(cm.assistant_logo_path(),
                         real / "logo_07_blue_circle.png")
        cm.save_assistant_logo("")
        self.assertIsNone(cm.assistant_logo_path())


if __name__ == "__main__":
    unittest.main()
