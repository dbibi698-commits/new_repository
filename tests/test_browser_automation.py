"""tests/test_browser_automation.py — no-extension browser driver + flows.

Covers core/browser_driver.py, core/browser_automation.py and the two
plugins (plugins/github_browser.py, plugins/render_browser.py).

Stdlib only. The Playwright/CDP layer is faked — no real browser, no
network, no real GitHub repo and no real Render service is ever created.
One test uses the REAL installed Playwright import (no browser launch) on
machines without Chrome; it skips itself when Chrome is present.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import browser_automation as auto  # noqa: E402
from core import browser_driver as drv  # noqa: E402


# ── fakes ───────────────────────────────────────────────────────────────────

class FakeLocator:
    def __init__(self, page, selector):
        self._page = page
        self._selector = selector

    def inner_text(self, timeout=None):
        if self._selector == "body":
            return self._page.text
        return self._page.elements.get(self._selector, "")


class FakePage:
    """A Playwright Page stand-in: records calls, serves scripted text/url."""

    def __init__(self):
        self.url = "about:blank"
        self.text = ""
        self.elements = {}
        self.calls = []
        self.fail_click = set()
        self.fail_fill = set()
        self.goto_urls = []

    def goto(self, url, timeout=None, wait_until=None):
        self.calls.append(("goto", url))
        self.goto_urls.append(url)
        self.url = url

    def click(self, selector, timeout=None):
        self.calls.append(("click", selector))
        if selector in self.fail_click:
            raise RuntimeError(f"locator.click: Timeout {selector} not found")
        if "Create repository" in selector:
            self.url = "https://github.com/someuser/my-repo"
        if "Create Web Service" in selector:
            self.url = "https://dashboard.render.com/web/srv-abc123"

    def fill(self, selector, text, timeout=None):
        self.calls.append(("fill", selector, text))
        if selector in self.fail_fill:
            raise RuntimeError(f"locator.fill: Timeout {selector} not found")

    def wait_for_selector(self, selector, timeout=None):
        self.calls.append(("wait_for_selector", selector))

    def locator(self, selector):
        return FakeLocator(self, selector)

    def screenshot(self, path=None):
        self.calls.append(("screenshot", path))

    @property
    def mouse(self):
        page = self

        class _Mouse:
            def move(self, x, y):
                page.calls.append(("mouse_move", x, y))

            def click(self, x, y):
                page.calls.append(("mouse_click", x, y))

        return _Mouse()


class FakeContext:
    def __init__(self, page):
        self.pages = [page]
        self.closed = False

    def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page

    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, context):
        self.contexts = [context]


class FakeChromium:
    def __init__(self, fail_launch=False, fail_cdp=False):
        self.fail_launch = fail_launch
        self.fail_cdp = fail_cdp
        self.page = FakePage()
        self.context = FakeContext(self.page)

    def launch_persistent_context(self, user_data_dir, channel=None,
                                  headless=None, args=None):
        if self.fail_launch:
            raise RuntimeError("Failed to launch: profile is already in use")
        return self.context

    def connect_over_cdp(self, url):
        if self.fail_cdp:
            raise ConnectionError("connect_over_cdp: connection refused")
        return FakeBrowser(self.context)


class FakePW:
    """sync_playwright() stand-in: callable returning a started instance."""

    def __init__(self, chromium):
        self.chromium = chromium
        self.stopped = False

    def start(self):
        return self

    def stop(self):
        self.stopped = True


def make_pw_fn(chromium):
    return lambda: FakePW(chromium)


class FakePyAutoGUI:
    def __init__(self):
        self.calls = []

    def hotkey(self, *keys):
        self.calls.append(("hotkey", keys))

    def typewrite(self, text, interval=0.0):
        self.calls.append(("typewrite", text))

    def press(self, key):
        self.calls.append(("press", key))

    def moveTo(self, x, y):
        self.calls.append(("moveTo", x, y))

    def click(self, x, y):
        self.calls.append(("click", x, y))

    def screenshot(self, path):
        self.calls.append(("screenshot", path))


class ScriptedDriver:
    """A Driver-interface stub for the flow tests: records every call and
    moves the fake browser URL forward the way the real pages would."""

    dom_capable = True
    backend = "playwright"

    def __init__(self):
        self.calls = []
        self.url = "about:blank"
        self.text = ""
        self.fail = {}  # (action, selector-substring) -> error message
        self.fail_selectors = set()  # exact selectors that always fail

    def _should_fail(self, action, selector=""):
        for (act, sub), err in self.fail.items():
            if act == action and sub in (selector or ""):
                return err
        return None

    def navigate(self, url):
        self.calls.append(("navigate", url))
        self.url = url
        return True, f"Gelam: {url}"

    def click(self, selector):
        self.calls.append(("click", selector))
        if selector in self.fail_selectors:
            return False, f"element pelam na: {selector}"
        err = self._should_fail("click", selector)
        if err:
            return False, err
        if "Create repository" in selector:
            self.url = "https://github.com/someuser/my-repo"
        if "Create Web Service" in selector:
            self.url = "https://dashboard.render.com/web/srv-abc123"
        return True, f"Click korlam: {selector}"

    def fill(self, selector, text):
        self.calls.append(("fill", selector, text))
        if selector in self.fail_selectors:
            return False, f"element pelam na: {selector}"
        err = self._should_fail("fill", selector)
        if err:
            return False, err
        return True, f"Bhorlam: {selector}"

    def wait_for_selector(self, selector, timeout_ms=15000):
        self.calls.append(("wait_for_selector", selector))
        err = self._should_fail("wait_for_selector", selector)
        if err:
            return False, err
        return True, f"Pelam: {selector}"

    def read_text(self, selector=None):
        self.calls.append(("read_text", selector))
        return True, self.text

    def current_url(self):
        return self.url

    def wait(self, seconds):
        self.calls.append(("wait", seconds))
        return True, f"Wait korlam {seconds}s"

    def close(self):
        self.calls.append(("close",))
        return True, "bondho"


# ── backend selection ────────────────────────────────────────────────────────

class TestEnsureDriverOrder(unittest.TestCase):
    def test_playwright_channel_first(self):
        chrom = FakeChromium()
        driver, backend, msg = drv.ensure_driver(
            auto_install=False, playwright_fn=make_pw_fn(chrom))
        self.assertEqual(backend, "playwright")
        self.assertIsNotNone(driver)
        self.assertTrue(driver.dom_capable)
        self.assertIn("Playwright", msg)
        ok, _ = driver.navigate("https://github.com/new")
        self.assertTrue(ok)
        self.assertEqual(driver.current_url(), "https://github.com/new")

    def test_launch_fails_then_cdp(self):
        chrom = FakeChromium(fail_launch=True, fail_cdp=False)
        driver, backend, msg = drv.ensure_driver(
            auto_install=False, playwright_fn=make_pw_fn(chrom))
        self.assertEqual(backend, "cdp")
        self.assertIsNotNone(driver)
        self.assertTrue(driver.dom_capable)
        self.assertIn("CDP", msg)

    def test_playwright_and_cdp_fail_then_pyautogui(self):
        chrom = FakeChromium(fail_launch=True, fail_cdp=True)
        pag = FakePyAutoGUI()
        driver, backend, msg = drv.ensure_driver(
            auto_install=False, playwright_fn=make_pw_fn(chrom),
            pyautogui_mod=pag)
        self.assertEqual(backend, "pyautogui")
        self.assertIsNotNone(driver)
        self.assertFalse(driver.dom_capable)
        ok, _ = driver.mouse_click(10, 20)
        self.assertTrue(ok)
        self.assertIn(("click", 10, 20), pag.calls)

    def test_nothing_available_says_driver_not_ready(self):
        chrom = FakeChromium(fail_launch=True, fail_cdp=True)
        orig = drv._load_pyautogui
        drv._load_pyautogui = lambda: None
        try:
            driver, backend, msg = drv.ensure_driver(
                auto_install=False, playwright_fn=make_pw_fn(chrom))
        finally:
            drv._load_pyautogui = orig
        self.assertIsNone(driver)
        self.assertEqual(backend, "")
        self.assertIn("Chrome driver ready noy", msg)
        self.assertIn("Playwright", msg)

    def test_real_playwright_import_no_chrome(self):
        """Real import check on this machine: Playwright IS importable but
        no Chrome is installed, so ensure_driver must never hand back a
        DOM-capable driver pretending it can drive the browser. Skipped
        where Chrome exists. (Note: the full suite imports
        test_mouse_video first, which stubs pyautogui into sys.modules —
        so a pyautogui backend here is possible and is NOT a DOM driver.)"""
        if drv.find_chrome_exe():
            self.skipTest("Chrome installed here — real launch not attempted")
        self.assertIsNotNone(drv._load_playwright())
        driver, backend, msg = drv.ensure_driver(auto_install=False)
        self.assertNotEqual(backend, "playwright")
        self.assertNotEqual(backend, "cdp")
        if driver is None:
            self.assertIn("Chrome driver ready noy", msg)
        else:
            self.assertEqual(backend, "pyautogui")
            self.assertFalse(driver.dom_capable)


class TestDriverMethods(unittest.TestCase):
    def setUp(self):
        self.chrom = FakeChromium()
        self.driver, _, _ = drv.ensure_driver(
            auto_install=False, playwright_fn=make_pw_fn(self.chrom))

    def test_click_fill_read_screenshot_mouse_wait(self):
        ok, _ = self.driver.click("#repository_name")
        self.assertTrue(ok)
        ok, _ = self.driver.fill("#repository_name", "my-repo")
        self.assertTrue(ok)
        self.driver._page.text = "hello page"
        ok, text = self.driver.read_text()
        self.assertTrue(ok)
        self.assertEqual(text, "hello page")
        ok, _ = self.driver.screenshot("/tmp/x.png")
        self.assertTrue(ok)
        ok, _ = self.driver.mouse_move(5, 6)
        self.assertTrue(ok)
        ok, _ = self.driver.mouse_click(5, 6)
        self.assertTrue(ok)
        ok, _ = self.driver.wait(0)
        self.assertTrue(ok)

    def test_click_missing_selector_fails_plainly(self):
        self.driver._page.fail_click.add("#nope")
        ok, msg = self.driver.click("#nope")
        self.assertFalse(ok)
        self.assertIn("#nope", msg)

    def test_pyautogui_backend_refuses_dom_work(self):
        pag = FakePyAutoGUI()
        d = drv.Driver("pyautogui", pyautogui_mod=pag)
        ok, _ = d.launch()
        self.assertTrue(ok)
        ok, msg = d.click("#repository_name")
        self.assertFalse(ok)
        self.assertIn("DOM", msg)
        ok, msg = d.fill("#repository_name", "x")
        self.assertFalse(ok)
        ok, msg = d.read_text()
        self.assertFalse(ok)
        ok, _ = d.navigate("https://github.com/new")
        self.assertTrue(ok)
        self.assertIn(("hotkey", ("ctrl", "l")), pag.calls)

    def test_close_never_raises(self):
        ok, _ = self.driver.close()
        self.assertTrue(ok)


# ── step runner ──────────────────────────────────────────────────────────────

class TestDriverVerification(unittest.TestCase):
    """Verify the no-extension driver end to end (mocked Playwright):
    the pyautogui fallback really drives the address bar, a locked
    Chrome profile is reported plainly, and closing a CDP session never
    closes the user's own Chrome."""

    def test_pyautogui_navigate_uses_address_bar(self):
        pag = FakePyAutoGUI()
        d = drv.Driver(drv.BACKEND_PYAUTOGUI, pyautogui_mod=pag)
        ok, msg = d.launch()
        self.assertTrue(ok)
        ok, msg = d.navigate("https://example.com")
        self.assertTrue(ok, msg)
        self.assertIn(("hotkey", ("ctrl", "l")), pag.calls)
        self.assertIn(("typewrite", "https://example.com"), pag.calls)
        self.assertIn(("press", "enter"), pag.calls)

    def test_playwright_profile_lock_message(self):
        chrom = FakeChromium(fail_launch=True)
        d = drv.Driver(drv.BACKEND_PLAYWRIGHT,
                       playwright_fn=make_pw_fn(chrom))
        ok, msg = d.launch()
        self.assertFalse(ok)
        self.assertIn("Chrome already khula", msg)
        self.assertIn("CDP", msg)

    def test_cdp_close_keeps_user_chrome(self):
        chrom = FakeChromium()
        pw = FakePW(chrom)
        d = drv.Driver(drv.BACKEND_CDP, playwright_fn=lambda: pw)
        ok, msg = d.launch()
        self.assertTrue(ok, msg)
        self.assertEqual(d.backend, "cdp")
        self.assertTrue(d.dom_capable)
        ok, msg = d.close()
        self.assertTrue(ok)
        # The user's own Chrome (the fake context) was never closed.
        self.assertFalse(chrom.context.closed)
        self.assertTrue(pw.stopped)

    def test_navigate_then_read_then_screenshot(self):
        chrom = FakeChromium()
        driver, backend, msg = drv.ensure_driver(
            auto_install=False, playwright_fn=make_pw_fn(chrom))
        self.assertEqual(backend, "playwright")
        ok, _ = driver.navigate("https://github.com/new")
        self.assertTrue(ok)
        self.assertEqual(driver.current_url(), "https://github.com/new")
        chrom.page.text = "hello page"
        ok, text = driver.read_text()
        self.assertTrue(ok)
        self.assertEqual(text, "hello page")
        ok, _ = driver.screenshot("/tmp/mark-test-shot.png")
        self.assertTrue(ok)
        self.assertIn(("screenshot", "/tmp/mark-test-shot.png"),
                      chrom.page.calls)


class TestRunSteps(unittest.TestCase):
    def test_happy_path_records_selector_used(self):
        d = ScriptedDriver()
        d.fail_selectors = {"#missing"}
        trace = []
        steps = [
            {"label": "Page khola", "action": "navigate",
             "url": "https://github.com/new"},
            {"label": "Name bhorlam", "action": "fill",
             "selectors": ["#missing", "#repository_name"], "text": "my-repo"},
        ]
        ok, msg = auto.run_steps(steps, d, trace=trace)
        self.assertTrue(ok, msg)
        self.assertEqual(trace[1]["selector_used"], "#repository_name")
        # The failed "#missing" attempt is recorded too; the successful
        # fill is the one that matters.
        self.assertIn(("fill", "#repository_name", "my-repo"), d.calls)

    def test_stops_at_failing_step_and_names_it(self):
        d = ScriptedDriver()
        d.fail[("click", "Create repository")] = "element pelam na"
        steps = [
            {"label": "Page khola", "action": "navigate",
             "url": "https://github.com/new"},
            {"label": "Repo name bhorlam", "action": "fill",
             "selectors": ["#repository_name"], "text": "my-repo"},
            {"label": "Create repository chaplam", "action": "click",
             "selectors": ["button:has-text('Create repository')",
                           "text=Create repository"]},
            {"label": "Notun repo page asha", "action": "wait", "wait_s": 3},
        ]
        ok, msg = auto.run_steps(steps, d)
        self.assertFalse(ok)
        self.assertIn("Create repository chaplam", msg)
        self.assertIn("Step 3", msg)
        # The wait step after the failure never ran.
        self.assertNotIn(("wait", 3), d.calls)

    def test_verify_failure_names_what_was_seen(self):
        d = ScriptedDriver()
        d.url = "https://github.com/new"  # stuck on the form
        steps = [{"label": "Notun repo page asha", "action": "wait",
                  "wait_s": 0,
                  "verify": {"url_regex": r"^https://github\.com/[^/]+/x/?$"}}]
        ok, msg = auto.run_steps(steps, d)
        self.assertFalse(ok)
        self.assertIn("Notun repo page asha", msg)
        self.assertIn("github.com/new", msg)

    def test_optional_step_failure_is_skipped(self):
        d = ScriptedDriver()
        d.fail[("click", "Connect")] = "button nei"
        steps = [
            {"label": "Connect chaplam", "action": "click",
             "selectors": ["button:has-text('Connect')"], "optional": True},
            {"label": "Name bhorlam", "action": "fill",
             "selectors": ["#x"], "text": "y"},
        ]
        ok, msg = auto.run_steps(steps, d)
        self.assertTrue(ok, msg)
        self.assertEqual(d.calls[-1], ("fill", "#x", "y"))

    def test_no_driver_fails_plainly(self):
        ok, msg = auto.run_steps([{"label": "x", "action": "wait"}], None)
        self.assertFalse(ok)
        self.assertIn("driver", msg.lower())

    def test_pyautogui_driver_refused_by_runner(self):
        d = ScriptedDriver()
        d.dom_capable = False
        ok, msg = auto.run_steps([{"label": "x", "action": "wait"}], d)
        self.assertFalse(ok)
        self.assertIn("pyautogui", msg)


# ── GitHub flow ──────────────────────────────────────────────────────────────

class TestGithubFlow(unittest.TestCase):
    def test_step_sequence_and_selectors(self):
        steps = auto.github_steps("my-repo", "a test repo", private=True)
        actions = [s["action"] for s in steps]
        self.assertEqual(actions, ["navigate", "wait_for", "fill", "fill",
                                   "click", "click", "wait"])
        self.assertEqual(steps[0]["url"], "https://github.com/new")
        self.assertEqual(steps[2]["selectors"],
                         auto.GITHUB_SELECTORS["repo_name"])
        self.assertEqual(steps[2]["text"], "my-repo")
        self.assertEqual(steps[3]["selectors"],
                         auto.GITHUB_SELECTORS["repo_desc"])
        self.assertEqual(steps[4]["selectors"],
                         auto.GITHUB_SELECTORS["visibility_private"])
        self.assertEqual(steps[5]["selectors"],
                         auto.GITHUB_SELECTORS["create_button"])
        self.assertIn("#repository_name",
                      steps[1]["selectors"])

    def test_public_skips_description_step_when_empty(self):
        steps = auto.github_steps("my-repo", "", private=False)
        self.assertEqual([s["action"] for s in steps],
                         ["navigate", "wait_for", "fill", "click", "click",
                          "wait"])
        self.assertEqual(steps[3]["selectors"],
                         auto.GITHUB_SELECTORS["visibility_public"])

    def test_success_returns_repo_url(self):
        d = ScriptedDriver()
        ok, msg = auto.github_new_repo("my-repo", "a test repo",
                                       private=False, driver=d)
        self.assertTrue(ok, msg)
        self.assertIn("https://github.com/someuser/my-repo", msg)
        navs = [c for c in d.calls if c[0] == "navigate"]
        self.assertEqual(navs, [("navigate", "https://github.com/new")])
        fills = [c for c in d.calls if c[0] == "fill"]
        self.assertIn(("fill", "#repository_name", "my-repo"), fills)

    def test_empty_name_fails_before_any_driver_call(self):
        d = ScriptedDriver()
        ok, msg = auto.github_new_repo("   ", driver=d)
        self.assertFalse(ok)
        self.assertIn("naam", msg)
        self.assertEqual(d.calls, [])

    def test_bad_name_fails_before_any_driver_call(self):
        d = ScriptedDriver()
        ok, msg = auto.github_new_repo("bad name!", driver=d)
        self.assertFalse(ok)
        self.assertEqual(d.calls, [])

    def test_create_click_failure_names_step(self):
        d = ScriptedDriver()
        # Every fallback for the Create button must fail, or the runner
        # correctly recovers on the next selector (that is the point of
        # fallbacks — this test wants a total failure).
        d.fail[("click", "Create repository")] = "button pelam na"
        d.fail[("click", "form button[type='submit']")] = "button pelam na"
        ok, msg = auto.github_new_repo("my-repo", driver=d)
        self.assertFalse(ok)
        self.assertIn("Create repository chaplam", msg)

    def test_stuck_on_new_page_means_name_taken(self):
        d = ScriptedDriver()
        d.text = "Repository name is already taken on this account"
        # Never leave /new: block the URL change after the create click.
        orig_click = d.click

        def _click(selector):
            res = orig_click(selector)
            d.url = "https://github.com/new"
            return res
        d.click = _click
        ok, msg = auto.github_new_repo("taken", driver=d)
        self.assertFalse(ok)
        self.assertIn("already", msg)


# ── Render flow ──────────────────────────────────────────────────────────────

class TestRenderFlow(unittest.TestCase):
    def test_step_sequence_and_selectors(self):
        steps = auto.render_steps("my-app",
                                  "https://github.com/owner/my-app", "main")
        actions = [s["action"] for s in steps]
        self.assertEqual(actions, ["navigate", "wait", "click", "click",
                                   "click", "click", "fill", "click", "wait"])
        self.assertEqual(steps[0]["url"], "https://dashboard.render.com")
        self.assertEqual(steps[2]["selectors"],
                         auto.RENDER_SELECTORS["new_button"])
        self.assertEqual(steps[3]["selectors"],
                         auto.RENDER_SELECTORS["web_service"])
        self.assertIn("text=my-app", steps[4]["selectors"])
        self.assertIn("text=owner/my-app", steps[4]["selectors"])
        self.assertTrue(steps[5]["optional"])  # Connect is optional
        self.assertEqual(steps[6]["selectors"],
                         auto.RENDER_SELECTORS["service_name"])
        self.assertEqual(steps[6]["text"], "my-app")
        self.assertEqual(steps[7]["selectors"],
                         auto.RENDER_SELECTORS["create_service"])
        # main is the default branch — no branch step for it.
        self.assertNotIn("Branch", [s.get("label", "") for s in steps])

    def test_non_main_branch_adds_branch_step(self):
        steps = auto.render_steps("my-app",
                                  "https://github.com/owner/my-app", "dev")
        labels = [s.get("label", "") for s in steps]
        self.assertIn("Branch bhorlam", labels)

    def test_success_returns_service_url(self):
        d = ScriptedDriver()
        d.text = "Your service is live at https://my-app.onrender.com — enjoy!"
        ok, msg = auto.render_deploy("my-app",
                                     "https://github.com/owner/my-app",
                                     driver=d)
        self.assertTrue(ok, msg)
        self.assertIn("https://my-app.onrender.com", msg)
        navs = [c for c in d.calls if c[0] == "navigate"]
        self.assertEqual(navs, [("navigate", "https://dashboard.render.com")])
        fills = [c for c in d.calls if c[0] == "fill"]
        self.assertIn(("fill", "input[name='serviceName']", "my-app"), fills)

    def test_bad_inputs_fail_before_any_driver_call(self):
        d = ScriptedDriver()
        ok, msg = auto.render_deploy("", "https://github.com/o/r", driver=d)
        self.assertFalse(ok)
        self.assertEqual(d.calls, [])
        ok, msg = auto.render_deploy("My App!",
                                     "https://github.com/o/r", driver=d)
        self.assertFalse(ok)
        self.assertEqual(d.calls, [])
        ok, msg = auto.render_deploy("my-app", "not-a-url", driver=d)
        self.assertFalse(ok)
        self.assertEqual(d.calls, [])

    def test_new_button_failure_names_step(self):
        d = ScriptedDriver()
        # "New" is a substring of every fallback selector for the button.
        d.fail[("click", "New")] = "button pelam na"
        ok, msg = auto.render_deploy("my-app",
                                     "https://github.com/owner/my-app",
                                     driver=d)
        self.assertFalse(ok)
        self.assertIn("New button chaplam", msg)


# ── no-extension guard ───────────────────────────────────────────────────────

class TestNoExtensionDependency(unittest.TestCase):
    """The driver and the flows must never import or call the Chrome
    extension / dashboard browser-command queue. This scans the module
    source for the functional markers of that path."""

    _FORBIDDEN = (
        "queue_browser_command",
        "wait_browser_result",
        "X-Browser-Token",
        "/api/browser/",
        "chrome-extension",
        "background.js",
        "from dashboard",
        "import dashboard",
    )

    def test_driver_has_no_extension_hooks(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, "core", "browser_driver.py"),
                  encoding="utf-8") as f:
            src = f.read()
        for marker in self._FORBIDDEN:
            self.assertNotIn(marker, src, f"driver mentions {marker!r}")

    def test_automation_has_no_extension_hooks(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, "core", "browser_automation.py"),
                  encoding="utf-8") as f:
            src = f.read()
        for marker in self._FORBIDDEN:
            self.assertNotIn(marker, src, f"automation mentions {marker!r}")


# ── plugins ──────────────────────────────────────────────────────────────────

class _FakePlayer:
    def __init__(self):
        self.logs = []

    def write_log(self, text):
        self.logs.append(text)


class TestPlugins(unittest.TestCase):
    def _wait_for(self, event, timeout=2.0):
        self.assertTrue(event.wait(timeout), "plugin worker never ran")

    def test_github_plugin_starts_flow_in_background(self):
        import plugins.github_browser as gb
        from core import browser_automation as _auto
        called = {}
        done = threading.Event()
        orig = _auto.github_new_repo

        def _fake(name, description="", private=False, driver=None):
            called.update(name=name, description=description,
                          private=private)
            done.set()
            return True, "✅ Repo banalam: https://github.com/u/my-repo"

        _auto.github_new_repo = _fake
        try:
            player = _FakePlayer()
            res = gb.run({"name": "my-repo", "description": "d",
                          "private": True}, player=player)
        finally:
            _auto.github_new_repo = orig
        self._wait_for(done)
        self.assertEqual(called["name"], "my-repo")
        self.assertTrue(called["private"])
        self.assertIn("my-repo", res)
        self.assertIn("⏳", res)

    def test_github_plugin_empty_name_never_starts_flow(self):
        import plugins.github_browser as gb
        from core import browser_automation as _auto
        orig = _auto.github_new_repo
        started = []
        _auto.github_new_repo = lambda *a, **k: started.append(True) or (True, "x")
        try:
            res = gb.run({"name": "   "}, player=_FakePlayer())
        finally:
            _auto.github_new_repo = orig
        self.assertEqual(started, [])
        self.assertIn("naam", res)

    def test_render_plugin_starts_flow_in_background(self):
        import plugins.render_browser as rb
        from core import browser_automation as _auto
        called = {}
        done = threading.Event()
        orig = _auto.render_deploy

        def _fake(service_name, repo_url, branch="main", driver=None):
            called.update(service_name=service_name, repo_url=repo_url,
                          branch=branch)
            done.set()
            return True, "✅ Deploy shuru holo: https://x.onrender.com"

        _auto.render_deploy = _fake
        try:
            res = rb.run({"service_name": "my-app",
                          "repo_url": "https://github.com/o/r",
                          "branch": "dev"}, player=_FakePlayer())
        finally:
            _auto.render_deploy = orig
        self._wait_for(done)
        self.assertEqual(called["service_name"], "my-app")
        self.assertEqual(called["branch"], "dev")
        self.assertIn("my-app", res)

    def test_plugin_metadata(self):
        import plugins.github_browser as gb
        import plugins.render_browser as rb
        self.assertEqual(gb.PLUGIN["name"], "github_repo_browser_create")
        self.assertEqual(rb.PLUGIN["name"], "render_deploy_browser")
        for mod in (gb, rb):
            self.assertIn("description", mod.PLUGIN)
            self.assertIn("parameters", mod.PLUGIN)
            self.assertIn("required", mod.PLUGIN["parameters"])
        self.assertIn("name", gb.PLUGIN["parameters"]["required"])
        self.assertIn("service_name",
                      rb.PLUGIN["parameters"]["required"])
        self.assertIn("repo_url", rb.PLUGIN["parameters"]["required"])

    def test_plugin_run_never_raises_without_player(self):
        import plugins.github_browser as gb
        import plugins.render_browser as rb
        self.assertIsInstance(gb.run(None), str)
        self.assertIsInstance(rb.run({}), str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
