"""tests/test_software_builder_advanced.py — 🛠️ SOFTWARE BUILDER templates:
Flask dashboard, FastAPI+SQLite, PyQt desktop, static site, Telegram bot,
file organizer. Each template scaffolds + its main.py compiles.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only. No network, no Gemini (ask_fn is mocked where needed).
"""
from __future__ import annotations

import os
import py_compile
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import software_builder as sb  # noqa: E402


def _compile_all(project: dict, test: unittest.TestCase):
    """Every .py file in a generated project must compile."""
    for name, content in project.items():
        if not name.endswith(".py"):
            continue
        with tempfile.NamedTemporaryFile(
                "w", suffix=".py", delete=False, encoding="utf-8") as fh:
            fh.write(content)
            path = fh.name
        try:
            py_compile.compile(path, doraise=True)
        finally:
            os.unlink(path)


class TestTemplates(unittest.TestCase):
    def test_list_templates_six(self):
        templates = sb.list_templates()
        self.assertEqual(len(templates), 6)
        ids = [t["id"] for t in templates]
        self.assertEqual(ids, ["flask_dashboard", "fastapi_sqlite",
                               "pyqt_desktop", "static_site",
                               "telegram_bot", "file_organizer"])
        for t in templates:
            self.assertTrue(t["name"] and t["desc"])
            self.assertIn(t["kind"], ("web", "desktop", "tool"))

    def test_each_template_scaffolds_and_compiles(self):
        for tmpl in sb.list_templates():
            with self.subTest(template=tmpl["id"]):
                project = sb.generate_project(
                    "test project", kind=tmpl["kind"],
                    template=tmpl["id"], ask_fn=lambda p: "")
                self.assertIn("main.py", project, project)
                self.assertIn("README.md", project)
                self.assertIn("requirements.txt", project)
                self.assertIn("Chalao", project["README.md"])
                _compile_all(project, self)

    def test_generate_project_template_wins_over_ask(self):
        def _ask(prompt):
            raise AssertionError("ask_fn must not be called when a "
                                 "template is given")
        project = sb.generate_project("ekta dashboard", kind="web",
                                      template="flask_dashboard", ask_fn=_ask)
        self.assertIn("Flask", project["main.py"])

    def test_classify_template(self):
        cases = {
            "flask dashboard banao": "flask_dashboard",
            "ekta flask site banao": "flask_dashboard",
            "fastapi api banao": "fastapi_sqlite",
            "fastapi sqlite rest api": "fastapi_sqlite",
            "pyqt desktop app": "pyqt_desktop",
            "pyqt6 window app banao": "pyqt_desktop",
            "static html site banao": "static_site",
            "telegram bot banao": "telegram_bot",
            "file organizer banao": "file_organizer",
            "ekta todo dashboard banao": "",
            "ekta website banao": "",
            "": "",
        }
        for spec, want in cases.items():
            with self.subTest(spec=spec):
                self.assertEqual(sb.classify_template(spec), want)

    def test_build_project_writes_files(self):
        folder = tempfile.mkdtemp(prefix="mark-sb-test-")
        try:
            result = sb.build_project("ekta dashboard", kind="web",
                                      template="flask_dashboard")
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["template"], "flask_dashboard")
            for name in ("main.py", "README.md", "requirements.txt"):
                self.assertTrue(os.path.exists(os.path.join(
                    result["folder"], name)), name)
            # Flask template inlines its HTML in main.py (no templates/
            # dir on disk).
            with open(os.path.join(result["folder"], "main.py"),
                      encoding="utf-8") as fh:
                self.assertIn("Flask", fh.read())
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_install_requirements_mocked(self):
        calls = []

        def _fake_run(cmd, cwd=None, timeout=120):
            calls.append(cmd)
            return {"ok": True, "output": "ok"}

        folder = tempfile.mkdtemp(prefix="mark-sb-req-")
        try:
            with open(os.path.join(folder, "requirements.txt"),
                      "w", encoding="utf-8") as fh:
                fh.write("flask>=3.0\n")
            ok, note = sb._install_requirements(folder, run_fn=_fake_run)
            self.assertTrue(ok)
            self.assertIn("flask", note.lower())
            self.assertTrue(calls and "install" in " ".join(calls[0]))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class TestKindAwareRun(unittest.TestCase):
    def test_desktop_compile_check_no_localhost_line(self):
        # PyQt6 install is mocked — only the compile check runs for real.
        with mock.patch.object(
                sb, "_install_requirements", return_value=(True, "")):
            text = sb.build_and_run_text(
                "ekta pyqt app banao", kind="desktop",
                template="pyqt_desktop", open_browser=False)
        self.assertIn("GUI app", text)
        self.assertNotIn("Localhost:", text)

    def test_tool_smoke_run_real_organizer(self):
        # file_organizer template runs a real dry-run preview on
        # ~/Downloads; it never moves files without --go. Its
        # requirements.txt is empty, so no pip install runs.
        text = sb.build_and_run_text(
            "ekta file organizer banao", kind="tool",
            template="file_organizer", open_browser=False)
        self.assertIn("File Organizer", text)
        self.assertIn("Tool ekbar chollo", text)

    def test_web_template_with_mocked_server(self):
        def _fake_start(folder, entry="main.py"):
            return {"ok": True, "url": "http://localhost:5000",
                    "port": 5000, "server_id": "mock",
                    "note": "Server cholche (mocked)"}

        with mock.patch.object(
                sb, "_install_requirements", return_value=(True, "")):
            res = sb.build_and_run(
                "ekta flask dashboard banao", kind="web",
                template="flask_dashboard", open_browser=False,
                start_fn=_fake_start)
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(res.get("url"), "http://localhost:5000")
        self.assertEqual(res.get("template"), "flask_dashboard")


if __name__ == "__main__":
    unittest.main()
