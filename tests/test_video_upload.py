"""tests/test_video_upload.py — browser video upload (IG/FB/YT) + manual mode.

Stdlib only. The browser is faked at the Playwright Page level and driven
through the REAL core.browser_driver.Driver — no real browser, no network,
no real upload ever happens. Config is patched in-memory (no real
config file is touched).

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import browser_driver as drv  # noqa: E402
from core import video_upload as vu  # noqa: E402


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

    def set_input_files(self, files, timeout=None):
        self._page.calls.append(("set_input_files_locator", self._selector,
                                 files))


class FakeKeyboard:
    def __init__(self, page):
        self._page = page

    def press(self, key):
        self._page.calls.append(("key_press", key))

    def type(self, text, delay=None):
        self._page.calls.append(("keyboard_type", text))


class FakePage:
    """Playwright Page stand-in: records calls, serves scripted text/url."""

    def __init__(self, text: str = "home feed create posted published shared"):
        self.url = "about:blank"
        self.text = text
        self.elements = {}
        self.calls = []
        self.files_set = []
        self.fail_click = set()

    def goto(self, url, timeout=None, wait_until=None):
        self.calls.append(("goto", url))
        self.url = url

    def click(self, selector, timeout=None):
        self.calls.append(("click", selector))
        if selector in self.fail_click:
            raise RuntimeError(f"locator.click: Timeout {selector} not found")

    def fill(self, selector, text, timeout=None):
        self.calls.append(("fill", selector, text))

    def wait_for_selector(self, selector, timeout=None):
        self.calls.append(("wait_for_selector", selector))

    def locator(self, selector):
        return FakeLocator(self, selector)

    def set_input_files(self, selector, files, timeout=None):
        self.calls.append(("set_file", selector, files))
        self.files_set.append((selector, files))

    @property
    def keyboard(self):
        return FakeKeyboard(self)

    def screenshot(self, path=None):
        self.calls.append(("screenshot", path))

    def evaluate(self, js):
        self.calls.append(("evaluate", js))
        return "ok"


def make_driver(page):
    d = drv.Driver(backend=drv.BACKEND_PLAYWRIGHT)
    d._page = page
    return d


def fake_driver_fn(driver):
    return lambda: (driver, "playwright", "ok")


class VideoUploadTest(unittest.TestCase):
    def setUp(self):
        self._store = {}
        self._orig_read = vu._read_ns
        self._orig_save = vu._save_ns
        store = self._store
        vu._read_ns = lambda: dict(store)
        vu._save_ns = lambda values: store.update(values or {})
        self._sleep_patch = mock.patch("time.sleep")
        self._sleep_patch.start()
        fd, self.video = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)

    def tearDown(self):
        self._sleep_patch.stop()
        vu._read_ns = self._orig_read
        vu._save_ns = self._orig_save
        try:
            os.unlink(self.video)
        except OSError:
            pass

    # ── step lists ───────────────────────────────────────────────────────
    def test_instagram_steps(self):
        steps = vu.upload_steps("instagram", self.video, caption="darun!")
        actions = [s["action"] for s in steps]
        self.assertIn("navigate", actions)
        self.assertIn("set_file", actions)
        self.assertIn("fill", actions)  # caption goes through fill
        self.assertEqual(steps[0]["url"], vu.SITES["instagram"]["upload_url"])
        self.assertIn("instagram.com", steps[0]["verify"]["url_contains"])
        file_step = [s for s in steps if s["action"] == "set_file"][0]
        self.assertEqual(file_step["path"], self.video)
        self.assertEqual(file_step["selector"], "input[type='file']")

    def test_facebook_steps(self):
        steps = vu.upload_steps("facebook", self.video, caption="hello")
        self.assertTrue(steps)
        self.assertIn("facebook.com", steps[0]["url"])
        self.assertIn("set_file", [s["action"] for s in steps])

    def test_youtube_steps(self):
        steps = vu.upload_steps("youtube", self.video, title="Test",
                                description="desc")
        self.assertIn("studio.youtube.com", steps[0]["url"])
        self.assertIn("set_file", [s["action"] for s in steps])
        self.assertTrue(any(s.get("text") == "Test" for s in steps
                            if s["action"] == "type"))
        self.assertTrue(any("Publish" in str(s.get("selectors"))
                            for s in steps if s["action"] == "click"))

    def test_unknown_site_falls_back_to_youtube(self):
        steps = vu.upload_steps("myspace", self.video)
        self.assertTrue(steps)
        self.assertIn("studio.youtube.com", steps[0]["url"])

    def test_site_limits_shown(self):
        self.assertIn("90", vu.site_limit("instagram"))
        self.assertIn("240", vu.site_limit("facebook"))
        self.assertIn("12", vu.site_limit("youtube"))
        self.assertEqual(vu.site_limit("myspace"), "")

    # ── file + login gates ───────────────────────────────────────────────
    def test_file_ok(self):
        self.assertEqual(vu.file_ok(self.video), "")
        self.assertIn("pelam na", vu.file_ok("/tmp/no-such-video.mp4"))
        self.assertIn("dao", vu.file_ok(""))
        fd, txt = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            self.assertIn("video mone hocche na", vu.file_ok(txt))
        finally:
            os.unlink(txt)

    def test_login_needed(self):
        self.assertTrue(vu.login_needed(
            "instagram", "Log in to Instagram — sign in with your password"))
        self.assertFalse(vu.login_needed("instagram", "home feed create"))
        self.assertFalse(vu.login_needed("youtube", "studio dashboard"))
        self.assertFalse(vu.login_needed("instagram", ""))

    # ── auto upload (mocked driver) ──────────────────────────────────────
    def test_upload_video_happy_path(self):
        page = FakePage()
        driver = make_driver(page)
        ok, msg = vu.upload_video("instagram", self.video, caption="hi",
                                  driver_fn=fake_driver_fn(driver))
        self.assertTrue(ok, msg)
        self.assertTrue(page.files_set)
        self.assertEqual(page.files_set[0][1], self.video)

    def test_upload_video_login_missing(self):
        page = FakePage(text="Log in to Instagram — sign in now")
        driver = make_driver(page)
        ok, msg = vu.upload_video("instagram", self.video,
                                  driver_fn=fake_driver_fn(driver))
        self.assertFalse(ok)
        self.assertIn("login lagbe", msg)

    def test_upload_video_missing_file(self):
        page = FakePage()
        driver = make_driver(page)
        ok, msg = vu.upload_video("instagram", "/tmp/no-such-video.mp4",
                                  driver_fn=fake_driver_fn(driver))
        self.assertFalse(ok)
        self.assertIn("pelam na", msg)

    def test_upload_video_no_driver(self):
        ok, msg = vu.upload_video(
            "instagram", self.video,
            driver_fn=lambda: (None, "", "browser khulche na"))
        self.assertFalse(ok)
        self.assertIn("driver", msg.lower())

    # ── manual mode handoff (both ways) ──────────────────────────────────
    def test_manual_mode_open_and_hand_back(self):
        page = FakePage()
        driver = make_driver(page)
        ok, msg = vu.open_upload_page("instagram",
                                      driver_fn=fake_driver_fn(driver))
        self.assertTrue(ok, msg)
        self.assertEqual(vu.get_mode(), "manual")
        self.assertIn("instagram.com", page.url)
        back = vu.hand_back()
        self.assertIn("tumi koro", back)
        self.assertEqual(vu.get_mode(), "manual")

    def test_take_over_from_manual_page(self):
        page = FakePage()
        driver = make_driver(page)
        vu.set_mode("manual")
        ok, msg = vu.take_over("instagram", self.video, caption="hi",
                               driver_fn=fake_driver_fn(driver))
        self.assertTrue(ok, msg)
        self.assertTrue(page.files_set)

    def test_open_upload_page_unknown_site(self):
        page = FakePage()
        driver = make_driver(page)
        ok, msg = vu.open_upload_page("myspace",
                                      driver_fn=fake_driver_fn(driver))
        self.assertFalse(ok)

    def test_mode_defaults_auto(self):
        self.assertEqual(vu.get_mode(), "auto")
        vu.set_mode("manual")
        self.assertEqual(vu.get_mode(), "manual")
        vu.set_mode("auto")
        self.assertEqual(vu.get_mode(), "auto")


if __name__ == "__main__":
    unittest.main()
