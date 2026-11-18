"""tests/test_advanced_browser.py — Advanced Browser Control: driver
eval_js / play_video / press_key, run_steps play/key/type/set_file
actions, login-wall detection, and the live step report.

Stdlib only. Playwright/CDP are faked at the Page level and driven
through the REAL core.browser_driver.Driver — no real browser, no network.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import browser_automation as auto  # noqa: E402
from core import browser_driver as drv  # noqa: E402


class FakeLocator:
    def __init__(self, page, selector):
        self._page = page
        self._selector = selector

    def inner_text(self, timeout=None):
        if self._selector == "body":
            return self._page.text
        return self._page.elements.get(self._selector, "")

    def scroll_into_view_if_needed(self, timeout=None):
        self._page.calls.append(("scroll_into_view", self._selector))


class FakeKeyboard:
    def __init__(self, page):
        self._page = page

    def press(self, key):
        self._page.calls.append(("key_press", key))

    def type(self, text, delay=None):
        self._page.calls.append(("keyboard_type", text))


class FakePage:
    """Playwright Page stand-in with evaluate + keyboard + locator."""

    def __init__(self, video_state: str = "playing",
                 text: str = "home feed posted published"):
        self.url = "about:blank"
        self.text = text
        self.elements = {}
        self.video_state = video_state
        self.calls = []
        self.fail_click = set()
        self.files_set = []

    def goto(self, url, timeout=None, wait_until=None):
        self.calls.append(("goto", url))
        self.url = url

    def click(self, selector, timeout=None):
        self.calls.append(("click", selector))
        if selector in self.fail_click:
            raise RuntimeError(f"locator.click: Timeout {selector} not found")

    def fill(self, selector, text, timeout=None):
        self.calls.append(("fill", selector, text))

    def evaluate(self, js):
        self.calls.append(("evaluate", js))
        if "querySelector('video')" in js or 'querySelector("video")' in js:
            return self.video_state
        return "ok"

    @property
    def keyboard(self):
        return FakeKeyboard(self)

    def wait_for_selector(self, selector, timeout=None):
        self.calls.append(("wait_for_selector", selector))

    def locator(self, selector):
        return FakeLocator(self, selector)

    def set_input_files(self, selector, files, timeout=None):
        self.calls.append(("set_file", selector, files))
        self.files_set.append((selector, files))

    def screenshot(self, path=None):
        self.calls.append(("screenshot", path))
        return b"fake-png"


def real_driver(page):
    d = drv.Driver(backend=drv.BACKEND_PLAYWRIGHT)
    d._page = page
    return d


class AdvancedBrowserTest(unittest.TestCase):
    def setUp(self):
        self._sleep_patch = mock.patch("time.sleep")
        self._sleep_patch.start()

    def tearDown(self):
        self._sleep_patch.stop()

    # ── driver: eval_js / press_key / play_video ─────────────────────────
    def test_eval_js(self):
        d = real_driver(FakePage())
        ok, result = d.eval_js("document.title")
        self.assertTrue(ok)
        self.assertEqual(result, "ok")

    def test_eval_js_empty(self):
        d = real_driver(FakePage())
        ok, _ = d.eval_js("   ")
        self.assertFalse(ok)

    def test_press_key(self):
        page = FakePage()
        d = real_driver(page)
        ok, msg = d.press_key("k")
        self.assertTrue(ok, msg)
        self.assertIn(("key_press", "k"), page.calls)

    def test_press_key_empty(self):
        d = real_driver(FakePage())
        ok, _ = d.press_key("")
        self.assertFalse(ok)

    def test_play_video_playing(self):
        d = real_driver(FakePage(video_state="playing"))
        ok, msg = d.play_video()
        self.assertTrue(ok, msg)
        self.assertIn("cholche", msg)

    def test_play_video_paused(self):
        d = real_driver(FakePage(video_state="paused"))
        ok, msg = d.play_video()
        self.assertFalse(ok)
        self.assertIn("play holo na", msg)

    def test_play_video_no_video(self):
        d = real_driver(FakePage(video_state="no-video"))
        ok, msg = d.play_video()
        self.assertFalse(ok)
        self.assertIn("kono video", msg)

    def test_play_video_click_fails_falls_back_to_k(self):
        page = FakePage(video_state="playing")
        page.fail_click.add("video")
        d = real_driver(page)
        ok, msg = d.play_video()
        self.assertTrue(ok, msg)
        self.assertIn(("key_press", "k"), page.calls)

    # ── run_steps: new actions ───────────────────────────────────────────
    def test_run_steps_play_and_key(self):
        page = FakePage()
        driver = real_driver(page)
        ok, msg = auto.run_steps([
            {"label": "Video chalalam", "action": "play"},
            {"label": "k chaplam", "action": "key", "key": "k"},
        ], driver)
        self.assertTrue(ok, msg)
        self.assertIn(("key_press", "k"), page.calls)

    def test_run_steps_type_and_set_file(self):
        page = FakePage()
        driver = real_driver(page)
        ok, msg = auto.run_steps([
            {"label": "Search likhlam", "action": "type",
             "selector": "input[name=q]", "text": "sheru"},
            {"label": "File dilam", "action": "set_file",
             "selector": "input[type='file']", "path": "/tmp/v.mp4"},
        ], driver)
        self.assertTrue(ok, msg)
        self.assertIn(("keyboard_type", "sheru"), page.calls)
        self.assertEqual(page.files_set[0], ("input[type='file']",
                                             "/tmp/v.mp4"))

    def test_run_steps_full_human_flow(self):
        page = FakePage()
        driver = real_driver(page)
        ok, msg = auto.run_steps([
            {"label": "Google khullam", "action": "navigate",
             "url": "https://www.google.com",
             "verify": {"url_contains": "google.com"}},
            {"label": "Search likhlam", "action": "type",
             "selector": "input[name=q]", "text": "sheru"},
            {"label": "Search chaplam", "action": "key", "key": "Enter"},
            {"label": "Scroll korlam", "action": "scroll_to",
             "selector": "text=Videos"},
            {"label": "Screenshot nilam", "action": "screenshot"},
        ], driver)
        self.assertTrue(ok, msg)
        self.assertEqual(page.url, "https://www.google.com")
        self.assertIn(("scroll_into_view", "text=Videos"), page.calls)
        self.assertIn(("screenshot", "browser-shot.png"), page.calls)

    def test_run_steps_failed_step_names_itself(self):
        page = FakePage()
        page.fail_click.add("text=Sheru")
        driver = real_driver(page)
        ok, msg = auto.run_steps([
            {"label": "Google khullam", "action": "navigate",
             "url": "https://www.google.com"},
            {"label": "Result chaplam", "action": "click",
             "selector": "text=Sheru"},
            {"label": "Scroll korlam", "action": "scroll_to",
             "selector": "text=Videos"},
        ], driver)
        self.assertFalse(ok)
        self.assertIn("Result chaplam", msg)

    def test_run_steps_verify_blocks_wrong_page(self):
        page = FakePage()
        driver = real_driver(page)
        ok, msg = auto.run_steps([
            {"label": "Google khullam", "action": "navigate",
             "url": "https://www.google.com",
             "verify": {"url_contains": "bing.com"}},
        ], driver)
        self.assertFalse(ok)

    # ── login wall ───────────────────────────────────────────────────────
    def test_login_wall_detected(self):
        self.assertTrue(auto.login_wall_detected("Please log in to continue"))
        self.assertTrue(auto.login_wall_detected("Sign in with your password"))
        self.assertFalse(auto.login_wall_detected("home feed reels"))
        self.assertFalse(auto.login_wall_detected(""))
        self.assertFalse(auto.login_wall_detected(None))

    def test_login_status_text(self):
        self.assertIn("login kora nei", auto.login_status_text(
            real_driver(FakePage(text="Log in — sign in with your password"))))
        self.assertIn("login ache", auto.login_status_text(
            real_driver(FakePage(text="home feed reels"))))

    # ── live step report ─────────────────────────────────────────────────
    def test_run_human_actions_reports_every_step(self):
        page = FakePage()
        driver = real_driver(page)
        seen = []
        ok, report = auto.run_human_actions([
            {"label": "Site khullam", "action": "navigate",
             "url": "https://example.com"},
            {"label": "Video chalalam", "action": "play"},
        ], driver=driver, report_fn=seen.append)
        self.assertTrue(ok, report)
        self.assertIn("Step 1/2", report)
        self.assertIn("Step 2/2", report)
        self.assertEqual(len(seen), 3)  # 2 steps + final line
        self.assertTrue(all("✅" in line for line in seen))

    def test_run_human_actions_stops_at_failed_step(self):
        page = FakePage()
        page.fail_click.add("text=Go")
        driver = real_driver(page)
        seen = []
        ok, report = auto.run_human_actions([
            {"label": "Site khullam", "action": "navigate",
             "url": "https://example.com"},
            {"label": "Button chaplam", "action": "click",
             "selector": "text=Go"},
            {"label": "Scroll korlam", "action": "scroll_to",
             "selector": "text=More"},
        ], driver=driver, report_fn=seen.append)
        self.assertFalse(ok)
        self.assertIn("Step 2/3", report)
        self.assertIn("Button chaplam", report)
        self.assertNotIn("Step 3/3", report)

    def test_run_human_actions_no_driver(self):
        ok, msg = auto.run_human_actions(
            [{"label": "x", "action": "navigate", "url": "https://example.com"}],
            driver=None)
        # In this VM there is no Chrome/Playwright — the failure must be
        # honest, never a crash, never a fake success.
        self.assertFalse(ok)
        self.assertTrue(msg)


if __name__ == "__main__":
    unittest.main()
