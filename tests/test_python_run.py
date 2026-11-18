"""tests/test_python_run.py — 🐍 Python Run: snippet + project + relay.

Run from ~/workspace/mark-lvii:
    python3 tests/test_python_run.py
    python3 -m unittest discover -s tests -v

Stdlib only. Real subprocess runs (this PC's Python) for snippets and for
a real project folder — no network: pip is mocked where requirements.txt
is involved, and the venv is a real local venv. No Qt, no real phone.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import python_run as pr  # noqa: E402


class TestSnippet(unittest.TestCase):
    def test_print_output(self):
        res = pr.run_snippet('print("hello mark")\nprint(2 + 3)')
        self.assertTrue(res["ok"])
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("hello mark", res["stdout"])
        self.assertIn("5", res["stdout"])
        self.assertFalse(res["timed_out"])

    def test_text_wrapper(self):
        out = pr.run_snippet_text('print("x")')
        self.assertIn("Output:", out)
        self.assertIn("x", out)
        self.assertIn("exit code 0", out)

    def test_error_output_and_exit_code(self):
        res = pr.run_snippet('import sys\nprint("out")\nprint("boom", file=sys.stderr)\nraise SystemExit(3)')
        self.assertFalse(res["ok"])
        self.assertEqual(res["exit_code"], 3)
        self.assertIn("out", res["stdout"])
        self.assertIn("boom", res["stderr"])

    def test_empty_code(self):
        self.assertIn("Code dao", pr.run_snippet_text("   "))
        res = pr.run_snippet("")
        self.assertIn("code_error", res)

    def test_timeout(self):
        res = pr.run_snippet("import time\ntime.sleep(10)", timeout=1)
        self.assertTrue(res["timed_out"])
        self.assertIn("timeout", pr.run_snippet_text(
            "import time\ntime.sleep(10)", timeout=1))

    def test_output_cap(self):
        out = pr.run_snippet_text('print("A" * 20000)')
        self.assertIn("kata holo", out)
        self.assertLess(len(out), 20000)

    def test_syntax_error_is_reported_not_raised(self):
        out = pr.run_snippet_text("def broken(:")
        self.assertIn("Error", out)
        self.assertIn("exit code", out)


class TestProject(unittest.TestCase):
    def _project(self, tmp, files):
        root = Path(tmp) / "proj"
        root.mkdir()
        for name, content in files.items():
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return root

    def test_project_main_py(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp, {"main.py": 'print("project ok")\n'})
            out = pr.run_project(str(root), timeout=120)
            self.assertIn("project ok", out)
            self.assertIn("Project Run", out)

    def test_project_single_py_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp, {"app.py": 'print("single")\n'})
            out = pr.run_project(str(root), timeout=120)
            self.assertIn("single", out)

    def test_project_requirements_pip_mocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp, {
                "main.py": 'print("with reqs")\n',
                "requirements.txt": "requests>=2.31,<3\n",
            })
            with mock.patch.object(pr, "_pip_install",
                                  return_value=(True, "mocked install")) as pip:
                out = pr.run_project(str(root), timeout=120)
            self.assertTrue(pip.called)
            self.assertIn("with reqs", out)

    def test_project_pip_failure_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._project(tmp, {
                "main.py": 'print("still runs")\n',
                "requirements.txt": "no-such-package-xyz==9.9.9\n",
            })
            with mock.patch.object(pr, "_pip_install",
                                  return_value=(False, "mocked pip fail")):
                out = pr.run_project(str(root), timeout=120)
            self.assertIn("still runs", out)

    def test_project_missing_folder_and_entry(self):
        self.assertIn("pelam na", pr.run_project("/no/such/folder-xyz"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "empty"
            root.mkdir()
            self.assertIn("Entry file pelam na",
                          pr.run_project(str(root), timeout=60))


class TestPhoneRequest(unittest.TestCase):
    def test_prefix_and_raw_code(self):
        self.assertTrue(pr.is_phone_request("PYTHON_RUN::print(1)"))
        self.assertFalse(pr.is_phone_request("hello"))
        self.assertIn("42", pr.handle_phone_request("PYTHON_RUN::print(6*7)"))
        self.assertIn("42", pr.handle_phone_request("print(6*7)"))

    def test_empty_phone_request(self):
        self.assertIn("pelam na", pr.handle_phone_request("PYTHON_RUN::  "))


class TestPluginContract(unittest.TestCase):
    def test_plugin_snippet_and_project(self):
        from plugins import python_run as plugin
        self.assertEqual(plugin.PLUGIN["name"], "python_run")
        self.assertEqual(plugin.PLUGIN_SETTINGS.get("widget"), "python_run")
        out = plugin.run({"code": 'print("plugin ok")'})
        self.assertIn("plugin ok", out)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "p"
            root.mkdir()
            (root / "main.py").write_text('print("proj plugin")\n', encoding="utf-8")
            out = plugin.run({"mode": "project", "folder": str(root)})
            self.assertIn("proj plugin", out)

    def test_plugin_never_raises(self):
        from plugins import python_run as plugin
        self.assertIn("Code dao", plugin.run({}))
        self.assertIn("pelam na", plugin.run({"mode": "project", "folder": ""}))


class TestRelayHandling(unittest.TestCase):
    # Relay handling now goes through the Commander, which persists its
    # command log in plugin_config — keep that in memory here so tests
    # never touch the real config file.
    def setUp(self):
        self._store: dict = {}
        self._get = mock.patch(
            "memory.config_manager.get_plugin_config",
            side_effect=lambda ns: dict(self._store.get(ns, {})))
        self._save = mock.patch(
            "memory.config_manager.save_plugin_config",
            side_effect=lambda ns, values: self._store.setdefault(
                ns, {}).update(values))
        self._get.start()
        self._save.start()

    def tearDown(self):
        self._get.stop()
        self._save.stop()

    def _link(self):
        from core import jarvis_link as jl
        link = jl.JarvisLink.__new__(jl.JarvisLink)
        link.e2e_on = False
        link.log = lambda _t: None
        link.on_text = lambda _t: "on_text reply"
        link.sent = []
        link.send_result = lambda text: link.sent.append(text)
        return link

    def test_python_run_kind(self):
        link = self._link()
        link._handle_message({"kind": "python_run",
                              "text": 'print("relay ok")'})
        self.assertEqual(len(link.sent), 1)
        self.assertIn("relay ok", link.sent[0])

    def test_text_prefix_fallback(self):
        link = self._link()
        link._handle_message({"kind": "text",
                              "text": "PYTHON_RUN::print(7*6)"})
        self.assertEqual(len(link.sent), 1)
        self.assertIn("42", link.sent[0])

    def test_plain_text_still_goes_to_on_text(self):
        link = self._link()
        link._handle_message({"kind": "text", "text": "hello mark"})
        self.assertEqual(link.sent, ["on_text reply"])


if __name__ == "__main__":
    unittest.main()
