"""tests/test_social_auto.py — Social Auto-engagement: permission-first
gating, safe limits, warning-stop, escalation, toggle defaults.

Stdlib only. The browser is faked at the Playwright Page level and driven
through the REAL core.browser_driver.Driver — no real browser, no network,
nothing is ever liked/commented for real. Config is patched in-memory.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import random
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import browser_driver as drv  # noqa: E402
from core import social_auto as sa  # noqa: E402


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
    """Playwright Page stand-in: records calls, serves scripted text/url."""

    def __init__(self, text: str = ""):
        self.url = "about:blank"
        self.text = text
        self.elements = {}
        self.calls = []
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

    @property
    def keyboard(self):
        return FakeKeyboard(self)

    def screenshot(self, path=None):
        self.calls.append(("screenshot", path))


def make_driver(page):
    d = drv.Driver(backend=drv.BACKEND_PLAYWRIGHT)
    d._page = page
    return d


def fake_driver_fn(driver):
    return lambda: (driver, "playwright", "ok")


class SocialAutoTest(unittest.TestCase):
    def setUp(self):
        self._store = {}
        self._orig_read = sa._read_ns
        self._orig_save = sa._save_ns
        store = self._store
        sa._read_ns = lambda: dict(store)
        sa._save_ns = lambda values: store.update(values or {})
        self._sleep_patch = mock.patch("time.sleep")
        self._sleep_patch.start()

    def tearDown(self):
        self._sleep_patch.stop()
        sa._read_ns = self._orig_read
        sa._save_ns = self._orig_save

    # ── toggles: ALL OFF by default ──────────────────────────────────────
    def test_toggle_defaults_all_off(self):
        t = sa.toggles()
        for name in sa.TOGGLES:
            self.assertIn(name, t)
            self.assertFalse(t[name], name)

    def test_set_toggle_roundtrip(self):
        self.assertTrue(sa.set_toggle("auto_like", True))
        self.assertTrue(sa.toggles()["auto_like"])
        self.assertFalse(sa.toggles()["auto_comment"])
        self.assertFalse(sa.set_toggle("no_such_toggle", True))

    def test_limits_text(self):
        text = sa.limits_text()
        self.assertIn("30", text)
        self.assertIn("150", text)
        self.assertIn("20", text)
        self.assertIn("60", text)

    def test_delay_in_range(self):
        rng = random.Random(7)
        for _ in range(20):
            d = sa.delay_seconds(rng)
            self.assertGreaterEqual(d, 20)
            self.assertLessEqual(d, 60)

    # ── permission gating ────────────────────────────────────────────────
    def test_like_needs_approval(self):
        page = FakePage()
        ok, msg = sa.run_like("https://instagram.com/p/xyz",
                              driver_fn=fake_driver_fn(make_driver(page)))
        self.assertFalse(ok)
        self.assertIn("permission", msg)

    def test_like_with_approval(self):
        sa.approve_like_session()
        page = FakePage()
        driver = make_driver(page)
        ok, msg = sa.run_like("https://instagram.com/p/xyz",
                              driver_fn=fake_driver_fn(driver),
                              delay_fn=lambda: None)
        self.assertTrue(ok, msg)
        self.assertTrue(any(c[0] == "goto" for c in page.calls))

    def test_comment_needs_toggle_and_approved_text(self):
        # Toggle OFF -> refused even with approved text.
        sa.approve_text("darun!")
        page = FakePage()
        ok, msg = sa.run_comment("https://instagram.com/p/xyz", "darun!",
                                 driver_fn=fake_driver_fn(make_driver(page)))
        self.assertFalse(ok)
        self.assertIn("OFF", msg)
        # Toggle ON but text NOT approved -> refused.
        sa.set_toggle("auto_comment", True)
        ok, msg = sa.run_comment("https://instagram.com/p/xyz", "onno text",
                                 driver_fn=fake_driver_fn(make_driver(page)))
        self.assertFalse(ok)
        self.assertIn("approve", msg)
        # Toggle ON + exact approved text -> sent.
        ok, msg = sa.run_comment("https://instagram.com/p/xyz", "darun!",
                                 driver_fn=fake_driver_fn(make_driver(page)),
                                 delay_fn=lambda: None)
        self.assertTrue(ok, msg)

    def test_can_send_gate(self):
        ok, _ = sa.can_send("comment", "darun!")
        self.assertFalse(ok)
        sa.set_toggle("auto_comment", True)
        ok, _ = sa.can_send("comment", "darun!")
        self.assertFalse(ok)  # text not approved yet
        sa.approve_text("darun!")
        ok, _ = sa.can_send("comment", "darun!")
        self.assertTrue(ok)
        ok, _ = sa.can_send("comment", "darun")
        self.assertFalse(ok)  # exact text only — no near-miss
        ok, _ = sa.can_send("bogus", "darun!")
        self.assertFalse(ok)

    def test_approve_text_rejects_empty(self):
        self.assertFalse(sa.approve_text(""))
        self.assertFalse(sa.approve_text("   "))
        self.assertTrue(sa.approve_text("dhonnobad!"))
        self.assertTrue(sa.text_approved("dhonnobad!"))

    # ── caps ─────────────────────────────────────────────────────────────
    def test_like_hour_cap(self):
        ok, _ = sa.can_like()
        self.assertTrue(ok)
        for _ in range(30):
            sa._bump_like()
        ok, msg = sa.can_like()
        self.assertFalse(ok)
        self.assertIn("ghontay", msg)

    def test_like_day_cap(self):
        # Day cap only (hour counter reset): set the counters directly.
        self._store["counters"] = {
            "hour": 0, "day": 150,
            "hour_key": time.strftime("%Y-%m-%d %H"),
            "day_key": time.strftime("%Y-%m-%d")}
        ok, msg = sa.can_like()
        self.assertFalse(ok)
        self.assertIn("ajke", msg)

    # ── warning-stop + conflict guard ────────────────────────────────────
    def test_warning_detection(self):
        self.assertTrue(sa.detect_warning("action blocked — try again later"))
        self.assertTrue(sa.detect_warning("please complete the captcha"))
        self.assertFalse(sa.detect_warning("home feed reels"))
        self.assertFalse(sa.detect_warning(""))

    def test_like_stops_on_warning(self):
        sa.approve_like_session()
        page = FakePage(text="action blocked — try again later")
        ok, msg = sa.run_like("https://instagram.com/p/xyz",
                              driver_fn=fake_driver_fn(make_driver(page)),
                              delay_fn=lambda: None)
        self.assertFalse(ok)
        self.assertIn("blocked", msg.lower())

    def test_manual_pause_blocks_like(self):
        sa.approve_like_session()
        sa.set_manual_pause(True)
        try:
            page = FakePage()
            ok, msg = sa.run_like(
                "https://instagram.com/p/xyz",
                driver_fn=fake_driver_fn(make_driver(page)))
            self.assertFalse(ok)
            self.assertIn("pause", msg.lower())
        finally:
            sa.set_manual_pause(False)

    # ── escalation + templates ───────────────────────────────────────────
    def test_needs_escalation(self):
        self.assertTrue(sa.needs_escalation("price koto?"))
        self.assertTrue(sa.needs_escalation("amar password ta ki?"))
        self.assertTrue(sa.needs_escalation("upi diye payment korbo"))
        self.assertFalse(sa.needs_escalation("hello, kemon acho?"))
        self.assertFalse(sa.needs_escalation(""))

    def test_templates_default(self):
        tpls = sa.templates()
        self.assertTrue(tpls)
        names = [t.get("name", "").lower() for t in tpls]
        self.assertTrue(any("hello" in n or "thanks" in n or "price" in n
                            for n in names))

    def test_pick_reply_matches_and_misses(self):
        tpl = sa.pick_reply("hello bondhu")
        self.assertIsNotNone(tpl)
        self.assertTrue(tpl.get("text"))
        self.assertIsNone(sa.pick_reply("zqxw jibberish kotha 12345"))

    def test_auto_reply_escalates_money(self):
        sa.set_toggle("auto_reply", True)
        page = FakePage()
        ok, msg = sa.run_auto_reply(
            "price koto?", "https://instagram.com/direct/t/1",
            driver_fn=fake_driver_fn(make_driver(page)))
        self.assertFalse(ok)
        self.assertIn("🆘", msg)

    def test_auto_reply_escalates_unknown(self):
        sa.set_toggle("auto_reply", True)
        page = FakePage()
        ok, msg = sa.run_auto_reply(
            "zqxw jibberish kotha 12345", "https://instagram.com/direct/t/1",
            driver_fn=fake_driver_fn(make_driver(page)))
        self.assertFalse(ok)
        self.assertIn("🆘", msg)

    def test_auto_reply_off(self):
        page = FakePage()
        ok, msg = sa.run_auto_reply(
            "hello", "https://instagram.com/direct/t/1",
            driver_fn=fake_driver_fn(make_driver(page)))
        self.assertFalse(ok)
        self.assertIn("OFF", msg)

    def test_auto_reply_template_sent(self):
        sa.set_toggle("auto_reply", True)
        page = FakePage()
        ok, msg = sa.run_auto_reply(
            "hello", "https://instagram.com/direct/t/1",
            driver_fn=fake_driver_fn(make_driver(page)))
        self.assertTrue(ok, msg)

    # ── read-only flow + log ─────────────────────────────────────────────
    def test_open_profile(self):
        page = FakePage()
        ok, msg = sa.open_profile("https://instagram.com/someone",
                                  driver_fn=fake_driver_fn(make_driver(page)))
        self.assertTrue(ok, msg)
        self.assertIn("instagram.com/someone", page.url)

    def test_activity_log(self):
        sa.log_action("Mark", "❤️ Like korlam: test")
        text = sa.log_text()
        self.assertIn("Like korlam", text)
        self.assertEqual(len(sa.list_log()), 1)


if __name__ == "__main__":
    unittest.main()
