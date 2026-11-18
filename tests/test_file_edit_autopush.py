"""tests/test_file_edit_autopush.py — ✏️ FILE EDIT + 🚀 AUTO-PUSH:
diff preview, .bak backup, protected files refused, ambiguous matches
refused, and GitHub auto-push with the connector mocked (token present /
missing / 401 / repo exists).

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only. No real files outside tmp dirs, no real GitHub calls.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import auto_push as ap  # noqa: E402
from core import file_edit as fe  # noqa: E402


class TestFileEdit(unittest.TestCase):
    def _file(self, tmp, name="a.py", content="x = 1\nprint(x)\n"):
        p = Path(tmp) / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_preview_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._file(tmp)
            out = fe.preview_diff(str(p), "x = 1", "x = 2")
            self.assertIn("-x = 1", out)
            self.assertIn("+x = 2", out)
            self.assertEqual(p.read_text(), "x = 1\nprint(x)\n")

    def test_edit_needs_confirm(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._file(tmp)
            out = fe.edit_file(str(p), "x = 1", "x = 2", confirmed=False)
            self.assertIn("Confirm", out)
            self.assertEqual(p.read_text(), "x = 1\nprint(x)\n")

    def test_edit_writes_and_backs_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._file(tmp)
            out = fe.edit_file(str(p), "x = 1", "x = 2", confirmed=True)
            self.assertIn("Edit holo", out)
            self.assertEqual(p.read_text(), "x = 2\nprint(x)\n")
            bak = Path(str(p) + ".bak")
            self.assertTrue(bak.is_file())
            self.assertEqual(bak.read_text(), "x = 1\nprint(x)\n")

    def test_edit_missing_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._file(tmp)
            out = fe.edit_file(str(p), "nope", "x", confirmed=True)
            self.assertIn("pelam na", out)

    def test_edit_ambiguous_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._file(tmp, content="a = 1\na = 1\n")
            out = fe.edit_file(str(p), "a = 1", "a = 2", confirmed=True)
            self.assertIn("2 bar", out)
            self.assertEqual(p.read_text(), "a = 1\na = 1\n")

    def test_protected_files_refused(self):
        self.assertIn("edit kora jabe na",
                      fe.edit_file("/tmp/api_keys.json", "a", "b",
                                   confirmed=True))
        self.assertIn("edit kora jabe na",
                      fe.edit_file("/tmp/jarvis_link.json", "a", "b",
                                   confirmed=True))

    def test_binary_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "bin.dat"
            p.write_bytes(b"\x00\x01\x02binary")
            self.assertIn("Binary", fe.edit_file(str(p), "a", "b",
                                                 confirmed=True))

    def test_append_with_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._file(tmp)
            out = fe.append_file(str(p), "y = 2", confirmed=True)
            self.assertIn("Append holo", out)
            self.assertIn("y = 2", p.read_text())
            self.assertTrue(Path(str(p) + ".bak").is_file())

    def test_read_snippet(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._file(tmp, content="\n".join(f"line {i}" for i in range(1, 11)))
            out = fe.read_snippet(str(p), start=3, lines=2)
            self.assertIn("line 3", out)
            self.assertIn("line 4", out)
            self.assertNotIn("line 5", out)


class TestAutoPush(unittest.TestCase):
    def _project(self, tmp):
        root = Path(tmp) / "my-app"
        root.mkdir()
        (root / "main.py").write_text("print('hi')\n")
        (root / "README.md").write_text("# My App\n")
        (root / "config").mkdir()
        (root / "config" / "api_keys.json").write_text("{}")
        (root / ".env").write_text("SECRET=x")
        return root

    def test_no_token_honest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp)
            with mock.patch("core.connectors._token", return_value=""):
                out = ap.auto_push_project(str(root))
            self.assertIn("token set kora nei", out)

    def test_push_skips_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp)
            pushed = []

            def fake_push(token, owner, repo, path, content, message):
                pushed.append(path)
                return f"✅ GitHub-e {owner}/{repo}/{path} banano holo — https://github.com/{owner}/{repo}"

            with mock.patch("core.connectors._token",
                            return_value="tok"), \
                    mock.patch("core.connectors._req",
                               return_value=(200, {"login": "me"}, "")), \
                    mock.patch("core.connectors.github_create_repo",
                               return_value="✅ Repo banalam: me/my-app — https://github.com/me/my-app"), \
                    mock.patch("core.connectors.github_push_file",
                               side_effect=fake_push):
                out = ap.auto_push_project(str(root), repo_name="my-app")
            self.assertIn("GitHub-e push holo", out)
            self.assertIn("https://github.com/me/my-app", out)
            self.assertIn("main.py", pushed)
            self.assertIn("README.md", pushed)
            self.assertNotIn("config/api_keys.json", pushed)
            self.assertNotIn(".env", pushed)

    def test_repo_already_exists_pushes_anyway(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp)
            with mock.patch("core.connectors._token",
                            return_value="tok"), \
                    mock.patch("core.connectors._req",
                               return_value=(200, {"login": "me"}, "")), \
                    mock.patch("core.connectors.github_create_repo",
                               return_value="⚠️ GitHub: repo banano gelo na — naam 'my-app' hoyto already ache"), \
                    mock.patch("core.connectors.github_push_file",
                               return_value="✅ GitHub-e me/my-app/main.py banano holo — https://x"):
                out = ap.auto_push_project(str(root), repo_name="my-app")
            self.assertIn("GitHub-e push holo", out)

    def test_bad_token_honest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp)
            with mock.patch("core.connectors._token",
                            return_value="tok"), \
                    mock.patch("core.connectors._req",
                               return_value=(401, None, "Bad credentials")):
                out = ap.auto_push_project(str(root))
            self.assertIn("kaj korche na", out)

    def test_toggle(self):
        store = {}
        with mock.patch("memory.config_manager.get_plugin_config",
                        lambda ns: dict(store.get(ns) or {})), \
                mock.patch("memory.config_manager.save_plugin_config",
                           lambda ns, v: store.__setitem__(ns, dict(v))):
            self.assertFalse(ap.auto_push_enabled())
            self.assertIn("ON", ap.set_auto_push(True))
            self.assertTrue(ap.auto_push_enabled())
            self.assertIn("OFF", ap.set_auto_push(False))
            self.assertFalse(ap.auto_push_enabled())

    def test_slug(self):
        self.assertEqual(ap._slug("My Cool App!"), "My-Cool-App")
        self.assertEqual(ap._slug(""), "mark-project")


if __name__ == "__main__":
    unittest.main()
