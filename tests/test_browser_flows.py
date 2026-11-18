"""tests/test_browser_flows.py — 🌐 Browser control flows (2026-11-18 add-on).

Mocked-driver tests for sign-up / register / login flows, the Render
Static Site flow, manual watch mode + takeover, and the new step
actions (click by text / coordinates, fill by label, scroll). No real
Chrome, no network, no Qt.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import browser_flows as bf


class FakeDriver:
    """Minimal driver double: records calls, serves canned page text."""

    def __init__(self, page_text="Welcome! Account created. Dashboard",
                 url="https://example.com/welcome"):
        self.dom_capable = True
        self.calls = []
        self.page_text = page_text
        self.url = url
        self.eval_results = {}

    def navigate(self, url):
        self.calls.append(("navigate", url))
        self.url = url
        return True, f"Khullam {url}"

    def current_url(self):
        return self.url

    def read_text(self, selector=None):
        self.calls.append(("read_text", selector))
        return True, self.page_text

    def click(self, selector):
        self.calls.append(("click", selector))
        return True, f"Click korlam: {selector}"

    def fill(self, selector, text):
        self.calls.append(("fill", selector, text))
        return True, "Field bhorlam"

    def type_text(self, selector, text):
        self.calls.append(("type_text", selector, text))
        return True, "Type korlam"

    def wait(self, seconds):
        self.calls.append(("wait", seconds))
        return True, "Wait korlam"

    def wait_for_selector(self, selector, timeout_ms=15000):
        self.calls.append(("wait_for_selector", selector))
        return True, "Pelam"

    def eval_js(self, js):
        self.calls.append(("eval_js", js[:80]))
        for needle, result in self.eval_results.items():
            if needle in js:
                return True, result
        return True, "OK:done"

    def mouse_click(self, x, y):
        self.calls.append(("mouse_click", x, y))
        return True, f"Click korlam ({x}, {y})"

    def press_key(self, key):
        self.calls.append(("press_key", key))
        return True, f"Key: {key}"

    def play_video(self, selector=None):
        self.calls.append(("play_video", selector))
        return True, "Video cholche"

    def screenshot(self, path):
        self.calls.append(("screenshot", path))
        return True, f"Screenshot: {path}"

    def close(self):
        self.calls.append(("close",))
        return True, "Bondho"


class TestSignupLoginSteps(unittest.TestCase):
    def test_signup_steps_shape(self):
        steps = bf.signup_steps(
            "https://example.com/signup",
            {"Email": "a@b.com", "Password": "secret"},
            success_markers=("Account created",))
        actions = [s["action"] for s in steps]
        self.assertEqual(actions[0], "navigate")
        self.assertIn("fill_by_label", actions)
        self.assertIn("click_text", actions)
        self.assertEqual(steps[-1]["verify"]["text_contains"],
                         "Account created")
        fill = next(s for s in steps if s["action"] == "fill_by_label")
        self.assertEqual(fill["fields"], {"Email": "a@b.com",
                                          "Password": "secret"})

    def test_login_steps_shape(self):
        steps = bf.login_steps(
            "https://example.com/login",
            {"Email": "a@b.com", "Password": "secret"},
            success_markers=("Dashboard",))
        self.assertEqual(steps[0]["label"], "Login page khola")
        self.assertEqual(steps[-1]["verify"]["text_contains"], "Dashboard")

    def test_signup_auto_succeeds_on_success_marker(self):
        driver = FakeDriver(page_text="Welcome! Account created.")
        ok, msg = bf.signup("https://example.com/signup",
                            {"Email": "a@b.com"},
                            success_markers=("Account created",),
                            driver=driver)
        self.assertTrue(ok, msg)
        self.assertIn("Account created", msg)

    def test_signup_fails_plainly_without_url_or_fields(self):
        ok, msg = bf.signup("", {"Email": "a@b.com"})
        self.assertFalse(ok)
        ok, msg = bf.signup("https://example.com/signup", {})
        self.assertFalse(ok)
        self.assertIn("field", msg.lower())

    def test_login_auto_succeeds(self):
        driver = FakeDriver(page_text="Dashboard — welcome back")
        ok, msg = bf.login("https://example.com/login",
                           {"Email": "a@b.com", "Password": "x"},
                           success_markers=("Dashboard",),
                           driver=driver)
        self.assertTrue(ok, msg)

    def test_signup_step_failure_names_the_step(self):
        class FailingDriver(FakeDriver):
            def eval_js(self, js):
                self.calls.append(("eval_js", js[:80]))
                return False, "JS evaluate korte parlam na: boom"

        driver = FailingDriver()
        ok, msg = bf.signup("https://example.com/signup",
                            {"Email": "a@b.com"}, driver=driver)
        self.assertFalse(ok)
        # The failed step names itself (step number + label).
        self.assertIn("Step 3", msg)
        self.assertIn("label", msg.lower())


class TestClickTextAndFillByLabel(unittest.TestCase):
    def test_click_text_js_clicks_by_visible_text(self):
        js = bf.click_text_js("Sign up")
        self.assertIn("Sign up".lower(), js)
        self.assertIn("click()", js)
        self.assertIn("OK:", js)
        self.assertIn("FAIL:", js)

    def test_fill_by_label_js_finds_inputs_by_label(self):
        js = bf.fill_by_label_js({"Email": "a@b.com", "Password": "x"})
        self.assertIn("a@b.com", js)
        self.assertIn("querySelectorAll('label')", js)
        self.assertIn("aria-label", js)
        self.assertIn("OK:", js)
        self.assertIn("FAIL:", js)

    def test_eval_ok_parses_ok_fail(self):
        driver = FakeDriver()
        driver.eval_results = {"Email": "OK:2"}
        ok, msg = bf._eval_ok(driver, bf.fill_by_label_js({"Email": "a@b.com"}))
        self.assertTrue(ok)
        driver.eval_results = {"Email": "FAIL:Email"}
        ok, msg = bf._eval_ok(driver, bf.fill_by_label_js({"Email": "a@b.com"}))
        self.assertFalse(ok)
        self.assertIn("Email", msg)


class TestStaticSite(unittest.TestCase):
    def test_static_steps_pick_static_site_not_web_service(self):
        steps = bf.render_static_steps("amar-site",
                                       "https://github.com/owner/repo")
        text = " ".join(str(s) for s in steps)
        self.assertIn("Static Site", text)
        self.assertNotIn("Web Service", text)
        # The final verify looks for a static-service URL.
        self.assertIn("static/srv-", text)
        self.assertIn("dashboard", text)

    def test_static_deploy_validates_inputs(self):
        ok, msg = bf.render_static_deploy("", "https://github.com/o/r")
        self.assertFalse(ok)
        ok, msg = bf.render_static_deploy("site", "not-a-github-url")
        self.assertFalse(ok)
        self.assertIn("github.com", msg)


class TestManualMode(unittest.TestCase):
    def test_manual_returns_when_success_marker_appears(self):
        narrated = []
        driver = FakeDriver(page_text="Welcome! Account created.")
        ok, msg = bf.run_manual(
            "https://example.com/signup",
            ("Account created",), driver=driver,
            narrate_fn=narrated.append, stop_fn=lambda: False,
            poll_s=0.01, timeout_s=5.0)
        self.assertTrue(ok, msg)
        self.assertIn("Account created", msg)
        self.assertTrue(any("khullam" in n for n in narrated))

    def test_manual_stop_hands_over_to_auto(self):
        driver = FakeDriver(page_text="Sign up form here")
        ok, msg = bf.run_manual(
            "https://example.com/signup", ("Account created",),
            driver=driver, narrate_fn=lambda t: None,
            stop_fn=lambda: True, poll_s=0.01, timeout_s=5.0)
        self.assertFalse(ok)
        self.assertIn("tumi koro", msg.lower())

    def test_manual_never_closes_the_users_browser(self):
        driver = FakeDriver(page_text="nothing yet")
        bf.run_manual("https://example.com", (), driver=driver,
                      narrate_fn=lambda t: None, stop_fn=lambda: True,
                      poll_s=0.01, timeout_s=1.0)
        self.assertNotIn(("close",), driver.calls)

    def test_manual_needs_url(self):
        ok, msg = bf.run_manual("", (), driver=FakeDriver())
        self.assertFalse(ok)


class TestStepActions(unittest.TestCase):
    def test_click_coords_and_scroll_steps_run(self):
        from core.browser_automation import run_steps
        driver = FakeDriver()
        ok, msg = run_steps([
            {"label": "Click (100, 200)", "action": "click_coords",
             "x": 100, "y": 200},
            {"label": "Scroll down", "action": "scroll", "dy": 500},
            {"label": "Click text", "action": "click_text",
             "text": "Sign up"},
        ], driver)
        self.assertTrue(ok, msg)
        kinds = [c[0] for c in driver.calls]
        self.assertIn("mouse_click", kinds)
        self.assertIn("eval_js", kinds)

    def test_click_text_falls_back_to_js(self):
        from core.browser_automation import run_steps

        class NoTextDriver(FakeDriver):
            def click(self, selector):
                self.calls.append(("click", selector))
                return False, "text= selector support nei"

        driver = NoTextDriver()
        ok, msg = run_steps([
            {"label": "Click text", "action": "click_text", "text": "Login"},
        ], driver)
        self.assertTrue(ok, msg)
        self.assertTrue(any(c[0] == "eval_js" for c in driver.calls))

    def test_fill_by_label_step_runs(self):
        from core.browser_automation import run_steps
        driver = FakeDriver()
        ok, msg = run_steps([
            {"label": "Form bhorlam", "action": "fill_by_label",
             "fields": {"Email": "a@b.com"}},
        ], driver)
        self.assertTrue(ok, msg)


class TestModesAndLimits(unittest.TestCase):
    def test_mode_text(self):
        self.assertIn("AUTO", bf.mode_text("auto"))
        self.assertIn("MANUAL", bf.mode_text("manual"))
        self.assertIn("AUTO", bf.mode_text("bogus"))

    def test_limits_are_honest(self):
        self.assertIn("Login lagbe", bf.BROWSER_LIMITS)
        self.assertIn("password", bf.BROWSER_LIMITS.lower())
        self.assertIn("design bodle", bf.BROWSER_LIMITS)
        self.assertIn("Render account", bf.BROWSER_LIMITS)
        self.assertIn("GitHub login", bf.BROWSER_LIMITS)

    def test_flow_strings_have_no_banned_word(self):
        for text in (bf.BROWSER_LIMITS, bf.mode_text("auto"),
                     bf.mode_text("manual")):
            self.assertNotIn("extension", text.lower())


if __name__ == "__main__":
    unittest.main()
