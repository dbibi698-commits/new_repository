"""tests/test_browser_advanced.py — 🌐 BROWSER ADVANCED: form fill,
multi-tab, wait-for-selector, scroll-to-element, screenshot, run_steps
new actions. All with a fake Playwright page/context — no real Chrome.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import browser_automation as ba  # noqa: E402
from core.browser_driver import Driver  # noqa: E402


class _FakeLocator:
    def __init__(self, page, selector):
        self._page = page
        self.selector = selector

    def scroll_into_view_if_needed(self, timeout=None):
        self._page.scrolled.append(self.selector)

    def inner_text(self, timeout=None):
        return self._page.text


class _FakePage:
    def __init__(self, url="https://example.com", title="Example"):
        self.url = url
        self._title = title
        self.filled = {}
        self.clicked = []
        self.waited = []
        self.scrolled = []
        self.text = "Hello fake page"
        self.closed = False
        self.shots = []

    def title(self):
        return self._title

    def fill(self, selector, text, timeout=None):
        self.filled[selector] = text

    def click(self, selector, timeout=None):
        self.clicked.append(selector)

    def wait_for_selector(self, selector, timeout=None):
        self.waited.append(selector)

    def locator(self, selector):
        return _FakeLocator(self, selector)

    def goto(self, url, timeout=None, wait_until=None):
        self.url = url

    def screenshot(self, path=None):
        self.shots.append(path)

    def bring_to_front(self):
        pass

    def close(self):
        self.closed = True


class _FakeContext:
    def __init__(self):
        self.pages = [_FakePage("https://example.com", "Example")]

    def new_page(self):
        page = _FakePage("about:blank", "Blank")
        self.pages.append(page)
        return page


def _driver_with_fake() -> tuple[Driver, _FakePage, _FakeContext]:
    drv = Driver("playwright")
    ctx = _FakeContext()
    page = ctx.pages[0]
    drv._context = ctx
    drv._page = page
    return drv, page, ctx


class TestFillForm(unittest.TestCase):
    def test_fill_form_records_all_fields(self):
        drv, page, _ = _driver_with_fake()
        ok, msg = drv.fill_form({"#name": "Jan", "#email": "jan@x.com"})
        self.assertTrue(ok, msg)
        self.assertEqual(page.filled, {"#name": "Jan",
                                       "#email": "jan@x.com"})
        self.assertIn("2 ta field", msg)

    def test_fill_form_with_submit_clicks(self):
        drv, page, _ = _driver_with_fake()
        ok, msg = drv.fill_form({"#name": "Jan"}, submit_selector="#go")
        self.assertTrue(ok, msg)
        self.assertIn("#go", page.clicked)
        self.assertIn("submit", msg)

    def test_fill_form_empty_rejected(self):
        drv, _, _ = _driver_with_fake()
        ok, msg = drv.fill_form({})
        self.assertFalse(ok)
        self.assertIn("field dao", msg)

    def test_fill_form_no_page_blocked(self):
        drv = Driver("playwright")
        ok, _ = drv.fill_form({"#a": "b"})
        self.assertFalse(ok)

    def test_wait_for_selector(self):
        drv, page, _ = _driver_with_fake()
        ok, msg = drv.wait_for_selector("#repo-name")
        self.assertTrue(ok, msg)
        self.assertIn("#repo-name", page.waited)

    def test_scroll_to_element(self):
        drv, page, _ = _driver_with_fake()
        ok, msg = drv.scroll_to_element("#footer")
        self.assertTrue(ok, msg)
        self.assertIn("#footer", page.scrolled)

    def test_screenshot_records_path(self):
        drv, page, _ = _driver_with_fake()
        ok, msg = drv.screenshot("/tmp/mark-shot.png")
        self.assertTrue(ok, msg)
        self.assertIn("/tmp/mark-shot.png", page.shots)


class TestTabs(unittest.TestCase):
    def test_new_tab_and_list(self):
        drv, _, ctx = _driver_with_fake()
        ok, msg = drv.new_tab()
        self.assertTrue(ok, msg)
        ok, tabs = drv.list_tabs()
        self.assertTrue(ok)
        self.assertEqual(len(tabs), 2)
        self.assertEqual(tabs[0]["url"], "https://example.com")
        self.assertEqual(tabs[1]["title"], "Blank")
        self.assertTrue(tabs[1]["current"])

    def test_new_tab_with_url_navigates(self):
        drv, _, _ = _driver_with_fake()
        ok, _ = drv.new_tab("https://github.com/new")
        self.assertTrue(ok)
        self.assertEqual(drv.current_url(), "https://github.com/new")

    def test_switch_tab(self):
        drv, _, _ = _driver_with_fake()
        drv.new_tab()
        ok, msg = drv.switch_tab(0)
        self.assertTrue(ok, msg)
        self.assertEqual(drv.current_url(), "https://example.com")

    def test_switch_tab_out_of_range(self):
        drv, _, _ = _driver_with_fake()
        ok, msg = drv.switch_tab(9)
        self.assertFalse(ok)
        self.assertIn("nei", msg)

    def test_close_tab_refuses_last(self):
        drv, _, _ = _driver_with_fake()
        ok, msg = drv.close_tab()
        self.assertFalse(ok)
        self.assertIn("Shesh tab", msg)

    def test_close_tab_removes_page(self):
        drv, _, ctx = _driver_with_fake()
        drv.new_tab()
        ok, msg = drv.close_tab(1)
        self.assertTrue(ok, msg)
        # The fake page's close() was called; the context still holds it
        # (a fake does not prune), so assert on the close flag instead.
        self.assertTrue(ctx.pages[1].closed)
        self.assertIn("baki", msg)


class TestRunStepsNewActions(unittest.TestCase):
    def test_fill_form_step(self):
        drv, page, _ = _driver_with_fake()
        ok, msg = ba.run_steps([
            {"label": "Form", "action": "fill_form",
             "fields": {"#a": "1", "#b": "2"}, "submit": "#go"}], drv)
        self.assertTrue(ok, msg)
        self.assertEqual(page.filled["#a"], "1")
        self.assertIn("#go", page.clicked)

    def test_tab_steps(self):
        drv, _, _ = _driver_with_fake()
        ok, msg = ba.run_steps([
            {"label": "Tab kholo", "action": "new_tab",
             "url": "https://example.org"},
            {"label": "Ageer tab", "action": "switch_tab", "index": 0},
            {"label": "Scroll", "action": "scroll_to",
             "selector": "#top"},
            {"label": "Shot", "action": "screenshot",
             "path": "/tmp/mark-run-steps.png"}], drv)
        self.assertTrue(ok, msg)
        ok, tabs = drv.list_tabs()
        self.assertEqual(len(tabs), 2)

    def test_form_fill_helper(self):
        drv, page, _ = _driver_with_fake()
        ok, msg = ba.form_fill("https://example.com",
                               {"#a": "x"}, submit="#go", driver=drv)
        self.assertTrue(ok, msg)
        self.assertEqual(page.filled["#a"], "x")
        self.assertIn("#go", page.clicked)

    def test_list_open_tabs_helper(self):
        drv, _, _ = _driver_with_fake()
        drv.new_tab()
        ok, text = ba.list_open_tabs(driver=drv)
        self.assertTrue(ok, text)
        self.assertIn("2 ta tab", text)


if __name__ == "__main__":
    unittest.main()
