"""tests/test_browser_setup.py — 🧪 Browser Setup wizard (Playwright round).

Mocked tests for the wizard steps: Python detection incl. not-found,
pip-install command building + output handling, playwright-install
command + progress parsing, verify logic, sample code content, and its
mocked run. No real Python installs, no network, no Qt.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import browser_setup as bs


def _runner_factory(script):
    """Fake runner: returns scripted (rc, stdout, stderr) per call."""
    calls = []

    def run(cmd, timeout):
        calls.append((list(cmd), timeout))
        rc, out, err = script.pop(0)
        return rc, out, err

    run.calls = calls
    return run


class TestPythonDetection(unittest.TestCase):
    def test_found_python_reports_version(self):
        runner = _runner_factory([
            (0, "Python 3.12.8\n", ""),
        ])
        exe, version = bs.find_system_python(
            runner=runner, which_fn=lambda name: "C:\\Python312\\python.exe")
        self.assertEqual(exe, "C:\\Python312\\python.exe")
        self.assertEqual(version, "3.12.8")

    def test_no_system_python_says_so_plainly(self):
        res = bs.check_python(
            runner=_runner_factory([]),
            which_fn=lambda name: None)
        self.assertFalse(res["ok"])
        self.assertIn("Python install nei", res["message"])
        self.assertIn("python.org", res["message"])
        self.assertIn("Add Python to PATH", res["message"])

    def test_version_parsing(self):
        self.assertEqual(bs._version_of("Python 3.11.4\n"), "3.11.4")
        self.assertEqual(bs._version_of("Python 3.12.8 (tags/v3.12.8)"), "3.12.8")
        self.assertEqual(bs._version_of("garbage"), "")

    def test_py_launcher_is_tried(self):
        seen = []

        def which_fn(name):
            seen.append(name)
            return "py" if name == "py" else None

        exe, _ = bs.find_system_python(
            runner=_runner_factory([(0, "Python 3.13.1\n", "")]),
            which_fn=which_fn)
        self.assertEqual(exe, "py")
        self.assertIn("python", seen)
        self.assertIn("py", seen)


class TestPipInstall(unittest.TestCase):
    def test_command_is_pip_install_playwright(self):
        runner = _runner_factory([(0, "Successfully installed playwright\n", "")])
        ok, msg, _out = bs.pip_install_playwright("python", runner=runner)
        self.assertTrue(ok)
        cmd = runner.calls[0][0]
        self.assertEqual(cmd, ["python", "-m", "pip", "install", "playwright"])
        self.assertGreaterEqual(runner.calls[0][1], 300)

    def test_pip_missing_says_how_to_fix(self):
        runner = _runner_factory([
            (1, "", "No module named pip"),
        ])
        ok, msg, _out = bs.pip_install_playwright("python", runner=runner)
        self.assertFalse(ok)
        self.assertIn("pip", msg.lower())

    def test_no_internet_is_honest(self):
        runner = _runner_factory([
            (1, "", "Could not fetch URL https://pypi.org: Name or service not known"),
        ])
        ok, msg, _out = bs.pip_install_playwright("python", runner=runner)
        self.assertFalse(ok)
        self.assertIn("internet", msg.lower())


class TestPlaywrightInstall(unittest.TestCase):
    def test_command_and_progress(self):
        logs = []
        runner = _runner_factory([
            (0, "Downloading Chromium 140.0 (150 MB)\n  45%\n  100%\n", ""),
        ])
        ok, msg, out = bs.playwright_install(
            "python", browsers=("chromium",), runner=runner,
            log_fn=logs.append)
        self.assertTrue(ok)
        cmd = runner.calls[0][0]
        self.assertEqual(cmd[:4], ["python", "-m", "playwright", "install"])
        self.assertIn("chromium", cmd)
        self.assertTrue(any("45%" in l or "100%" in l for l in logs))

    def test_multiple_browsers(self):
        runner = _runner_factory([(0, "ok", "")])
        bs.playwright_install("python", browsers=("chromium", "firefox"),
                              runner=runner)
        cmd = runner.calls[0][0]
        self.assertIn("chromium", cmd)
        self.assertIn("firefox", cmd)

    def test_installed_browsers_lists_cache(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "chromium-1181"))
            os.makedirs(os.path.join(d, "firefox-1490"))
            os.makedirs(os.path.join(d, "not-a-browser"))
            found = bs.installed_browsers(cache_dir=d)
        # Full cache dir names, as playwright names them.
        self.assertIn("chromium-1181", found)
        self.assertIn("firefox-1490", found)
        self.assertEqual(len(found), 3)


class TestVerify(unittest.TestCase):
    def test_verify_success_on_launch_ok(self):
        runner = _runner_factory([(0, "LAUNCH-OK\n", "")])
        ok, msg = bs.verify_playwright("python", runner=runner)
        self.assertTrue(ok)

    def test_verify_failure_is_plain(self):
        runner = _runner_factory([(1, "", "Executable doesn't exist")])
        ok, msg = bs.verify_playwright("python", runner=runner)
        self.assertFalse(ok)
        self.assertTrue(msg.strip())


class TestSampleCode(unittest.TestCase):
    def test_sample_is_real_runnable_code(self):
        code = bs.sample_code("https://example.com", "a")
        for needle in ("sync_playwright", "chromium.launch",
                       "page.goto", "page.click", "screenshot",
                       "channel", "chrome"):
            self.assertIn(needle, code, needle)

    def test_sample_substitutes_url_and_selector(self):
        code = bs.sample_code("https://github.com", "input[name='q']")
        self.assertIn("https://github.com", code)
        self.assertIn("input[name='q']", code)

    def test_sample_file_exists_and_parses(self):
        import ast
        path = bs.sample_path()
        self.assertTrue(os.path.exists(path), path)
        ast.parse(open(path, encoding="utf-8").read())

    def test_run_sample_mocked(self):
        logs = []
        runner = _runner_factory([
            (0, "Sample cholche: https://example.com\nScreenshot: browser_sample.png\n", ""),
        ])
        ok, msg, _out = bs.run_sample("python", runner=runner,
                                      log_fn=logs.append)
        self.assertTrue(ok)
        cmd = runner.calls[0][0]
        self.assertIn("browser_sample.py", " ".join(cmd))

    def test_run_all_steps_stops_at_first_failure(self):
        # Step 1 fails (no Python) -> steps 2-4 never run.
        from unittest import mock
        with mock.patch.object(
                bs, "check_python",
                return_value={"ok": False, "path": "", "version": "",
                              "message": "❌ PC-te Python install nei"}):
            state = bs.run_all_steps(python_exe="",
                                     runner=_runner_factory([]),
                                     log_fn=lambda t: None)
        self.assertEqual(state["python"]["status"], "failed")
        self.assertEqual(state["pip"]["status"], "pending")
        self.assertEqual(state["install"]["status"], "pending")
        self.assertEqual(state["verify"]["status"], "pending")

    def test_run_all_steps_stops_when_pip_fails(self):
        from unittest import mock
        with mock.patch.object(
                bs, "check_python",
                return_value={"ok": True, "path": "python",
                              "version": "3.12.8", "message": "ok"}):
            state = bs.run_all_steps(
                python_exe="python",
                runner=_runner_factory([
                    (1, "", "No module named pip"),
                ]),
                log_fn=lambda t: None)
        self.assertEqual(state["python"]["status"], "done")
        self.assertEqual(state["pip"]["status"], "failed")
        self.assertEqual(state["install"]["status"], "pending")
        self.assertEqual(state["verify"]["status"], "pending")

    def test_status_text_mentions_system_python(self):
        text = bs.status_text()
        self.assertIn("Browser Setup", text)
        self.assertIn("Python", text)


if __name__ == "__main__":
    unittest.main()
