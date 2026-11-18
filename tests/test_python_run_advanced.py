"""tests/test_python_run_advanced.py — 🐍 PYTHON RUN libraries: pip list,
one-click install of common libraries, name validation.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only. Real pip is never called — run_fn is injected everywhere.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import python_run as pr  # noqa: E402

_FAKE_PIP_LIST = json.dumps([
    {"name": "requests", "version": "2.32.3"},
    {"name": "Pillow", "version": "10.4.0"},
    {"name": "flask", "version": "3.0.3"},
])


def _fake_pip_list(cmd, cwd=None, timeout=30):
    assert "pip" in cmd and "list" in cmd, cmd
    return {"ok": True, "stdout": _FAKE_PIP_LIST, "stderr": ""}


class TestCommonLibraries(unittest.TestCase):
    def test_common_libraries_list(self):
        names = [lib["name"] for lib in pr.COMMON_LIBRARIES]
        for want in ("requests", "Pillow", "flask", "fastapi", "pandas",
                     "beautifulsoup4", "openpyxl"):
            self.assertIn(want, names)
        for lib in pr.COMMON_LIBRARIES:
            self.assertTrue(lib["name"] and lib["desc"])

    def test_valid_lib_name(self):
        self.assertTrue(pr._valid_lib_name("requests"))
        self.assertTrue(pr._valid_lib_name("beautifulsoup4"))
        self.assertTrue(pr._valid_lib_name("Pillow"))
        self.assertFalse(pr._valid_lib_name("requests; rm -rf /"))
        self.assertFalse(pr._valid_lib_name("requests && pip install x"))
        self.assertFalse(pr._valid_lib_name("../requests"))
        self.assertFalse(pr._valid_lib_name(""))
        self.assertFalse(pr._valid_lib_name("a b"))


class TestListPackages(unittest.TestCase):
    def test_list_installed_packages_fake(self):
        res = pr.list_installed_packages(run_fn=_fake_pip_list)
        self.assertTrue(res["ok"], res)
        pkgs = res["packages"]
        self.assertEqual(len(pkgs), 3)
        self.assertEqual(pkgs[0]["name"], "requests")
        self.assertEqual(pkgs[1]["version"], "10.4.0")

    def test_list_installed_packages_failed_run(self):
        res = pr.list_installed_packages(
            run_fn=lambda c, cwd=None, timeout=30: {"ok": False,
                                                    "stdout": "",
                                                    "stderr": ""})
        self.assertFalse(res["ok"])
        self.assertEqual(res["packages"], [])

    def test_libraries_text_fake(self):
        with mock.patch.object(
                pr, "list_installed_packages",
                return_value={"ok": True,
                              "packages": [
                                  {"name": "requests", "version": "2.32.3"},
                                  {"name": "flask", "version": "3.0.3"}],
                              "note": "2 ta package install ache"}):
            text = pr.libraries_text()
        self.assertIn("requests", text)
        self.assertIn("2.32.3", text)
        self.assertIn("Install korte", text)

    def test_libraries_text_empty(self):
        with mock.patch.object(
                pr, "list_installed_packages",
                return_value={"ok": True, "packages": [],
                              "note": "0 ta package install ache"}):
            text = pr.libraries_text()
        self.assertIn("0 ta package install ache", text)


class TestInstallLibrary(unittest.TestCase):
    def test_install_valid_mocked(self):
        calls = []

        def _fake_run(cmd, cwd=None, timeout=180):
            calls.append(cmd)
            return {"ok": True, "stdout": "Successfully installed",
                    "stderr": ""}

        ok, note = pr.install_library("requests", run_fn=_fake_run)
        self.assertTrue(ok, note)
        self.assertIn("requests", note)
        self.assertTrue(calls and "install" in calls[0]
                        and "requests" in calls[0])

    def test_install_invalid_name_rejected(self):
        ok, note = pr.install_library(
            "requests; rm -rf /",
            run_fn=lambda c, cwd=None, timeout=180: {"ok": True})
        self.assertFalse(ok)
        self.assertIn("naam", note)

    def test_install_failed_run(self):
        ok, note = pr.install_library(
            "flask",
            run_fn=lambda c, cwd=None, timeout=180: {"ok": False,
                                                     "stdout": "",
                                                     "stderr": "no net"})
        self.assertFalse(ok)
        self.assertIn("flask", note)


if __name__ == "__main__":
    unittest.main()
