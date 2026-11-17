"""tests/test_apk_selfheal.py — self-healing APK build + automation fix.

Run from ~/workspace/mark-lvii:
    python3 tests/test_apk_selfheal.py
    python3 -m unittest discover -s tests -v

Stdlib only. The GitHub API (dispatch / runs / jobs / contents) and the
build logs are fully mocked — no network, no real token, and no real build
is ever dispatched. The fake token is distinctive so the tests can also
prove it never leaks into any returned string.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import apk_selfheal, automation_fix  # noqa: E402

_FAKE_TOKEN = "ghp_FAKE_selfheal_test_token_never_real"

# ── canned build logs, one per error class ───────────────────────────────────

LOG_DEPENDENCY = """
> Task :app:compileDebugKotlin FAILED
Could not resolve com.example:widget:+.
Required by: project :app
Found version 1.4.2 available for com.example:widget
* Try: Run with --info for more log output.
"""

LOG_MANIFEST = """
> Task :app:processDebugMainManifest FAILED
AndroidManifest.xml:12:9-20 Error: android:exported needs to be explicitly
specified for element <activity#com.example.MainActivity>. Apps targeting
Android 12 and higher are required to specify an explicit value for
`android:exported` when the corresponding component has an intent filter defined.
Manifest merger failed : android:exported needs to be explicitly specified
"""

LOG_MISSING_SECRET = """
> Task :app:assembleRelease FAILED
Error: secret KEYSTORE_PASSWORD not found — signingConfig release requires
a keystore password secret. Set it in GitHub repo Settings > Secrets.
"""

LOG_SYNTAX_KNOWN = """
e: app/src/main/java/com/example/MainActivity.kt: (12, 5): Unresolved reference: Toast
e: app/src/main/java/com/example/MainActivity.kt: (12, 5): Unresolved reference: Toast
> Task :app:compileDebugKotlin FAILED
"""

LOG_SYNTAX_UNKNOWN = """
e: app/src/main/java/com/example/MainActivity.kt: (12, 5): Unresolved reference: Zqxwv
> Task :app:compileDebugKotlin FAILED
"""

LOG_TRANSIENT = """
> Task :app:assembleDebug FAILED
Connection reset by peer during dependency download —
https://dl.google.com/dl/android/maven2/com/example/widget/1.4.2/widget-1.4.2.aar
* Try: Run with --info for more log output.
"""

BUILD_GRADLE = (
    'plugins { id "com.android.application" }\n'
    'android { namespace "com.example" }\n'
    'dependencies {\n'
    '    implementation "com.example:widget:+"\n'
    '}\n'
)

MANIFEST = """<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application android:label="Test">
        <activity android:name=".MainActivity">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""

MAIN_ACTIVITY_KT = """package com.example

class MainActivity {
    fun show() { Toast.makeText(this, "hi", 0).show() }
}
"""


# ── fake GitHub ──────────────────────────────────────────────────────────────

class FakeGitHub:
    """Mocked dispatch / runs / jobs / contents / log download.

    `run_script` is a list of (conclusion, log) — one per dispatch, in
    order. `files` is the fake repo (path -> content). Nothing here touches
    the network or a real token.
    """

    def __init__(self, run_script, files=None):
        self.run_script = list(run_script)
        self.files = dict(files or {})
        self.dispatch_calls = []
        self.push_calls = []
        self.dispatch_failures = []  # queue of dispatch strings to return

    # -- dispatch --
    def dispatch(self, owner, repo, workflow, ref):
        self.dispatch_calls.append((owner, repo, workflow, ref))
        if self.dispatch_failures:
            return self.dispatch_failures.pop(0)
        return ("✅ GitHub Actions-e build dispatch holo — "
                "https://github.com/o/r/actions")

    # -- JSON API (runs list + jobs list + contents GET) --
    def request(self, method, url, headers=None, params=None, payload=None):
        if "/actions/workflows/" in url and url.endswith("/runs"):
            idx = max(0, len(self.dispatch_calls) - 1)
            conclusion, _log = (self.run_script[idx]
                                if idx < len(self.run_script)
                                else self.run_script[-1])
            run = {"id": 100 + idx, "status": "completed",
                   "conclusion": conclusion,
                   "html_url": "https://github.com/o/r/actions/runs/1",
                   # Far-future date: always newer than the poll's "since".
                   "created_at": "2999-01-01T00:00:00+00:00"}
            return 200, {"workflow_runs": [run]}, ""
        if "/actions/runs/" in url and url.endswith("/jobs"):
            idx = max(0, len(self.dispatch_calls) - 1)
            conclusion, _log = (self.run_script[idx]
                                if idx < len(self.run_script)
                                else self.run_script[-1])
            return 200, {"jobs": [{"id": 7,
                                   "conclusion": conclusion}]}, ""
        if "/contents/" in url:
            path = url.split("/contents/", 1)[1].split("?")[0]
            if path in self.files:
                import base64
                return 200, {"content": base64.b64encode(
                    self.files[path].encode()).decode(),
                    "sha": "fakesha"}, ""
            return 404, {"message": "Not Found"}, "Not Found"
        return 404, {"message": "Not Found"}, "Not Found"

    # -- job log tail --
    def log(self, owner, repo, job_id):
        idx = max(0, len(self.dispatch_calls) - 1)
        _conclusion, log = (self.run_script[idx]
                            if idx < len(self.run_script)
                            else self.run_script[-1])
        return log

    # -- repo file read / push --
    def read(self, owner, repo, path, ref):
        if path in self.files:
            return self.files[path], "fakesha"
        return None, None

    def push(self, owner, repo, path, content, message):
        self.push_calls.append((path, content, message))
        self.files[path] = content
        return f"✅ GitHub-e {owner}/{repo}/{path} update holo"


def _run_selfheal(fake, **kw):
    return apk_selfheal.build_apk_selfheal(
        "someone/my-app", "build-apk.yml", ref="main", max_attempts=3,
        request_fn=fake.request, dispatch_fn=fake.dispatch,
        log_fn=fake.log, read_fn=fake.read, push_fn=fake.push,
        sleep_fn=lambda s: None, poll_interval_s=0, max_polls=3, **kw)


# ── classification ───────────────────────────────────────────────────────────

class TestClassify(unittest.TestCase):
    def test_each_class(self):
        cases = [
            (LOG_DEPENDENCY, "dependency", True),
            (LOG_MANIFEST, "manifest", True),
            (LOG_MISSING_SECRET, "missing_secret", False),
            (LOG_SYNTAX_KNOWN, "syntax", True),
            (LOG_TRANSIENT, "transient", True),
            ("BUILD SUCCESSFUL in 12s", "unknown", False),
        ]
        for log, want_class, want_fixable in cases:
            got = apk_selfheal.classify_failure(log)
            self.assertEqual(got["class"], want_class, log[:60])
            self.assertEqual(got["auto_fixable"], want_fixable, log[:60])

    def test_missing_secret_outranks_dependency(self):
        # A log mentioning both must still be a secret problem — it must
        # never trigger a fix attempt.
        log = ("Could not resolve com.example:widget:+\n"
               "Error: secret KEYSTORE_PASSWORD not found")
        self.assertEqual(apk_selfheal.classify_failure(log)["class"],
                         "missing_secret")

    def test_never_raises(self):
        for bad in (None, "", 123):
            got = apk_selfheal.classify_failure(bad)
            self.assertIn("class", got)


# ── self-heal loop, one error class at a time ────────────────────────────────

class TestSelfHeal(unittest.TestCase):
    def test_dependency_pins_version_and_rebuilds(self):
        fake = FakeGitHub(
            [("failure", LOG_DEPENDENCY), ("success", "")],
            {"app/build.gradle": BUILD_GRADLE})
        res = _run_selfheal(fake)
        self.assertIn("✅", res, res)
        self.assertIn("Attempt 2", res, res)
        self.assertEqual(len(fake.dispatch_calls), 2)
        self.assertEqual(len(fake.push_calls), 1)
        path, content, _msg = fake.push_calls[0]
        self.assertEqual(path, "app/build.gradle")
        self.assertIn("com.example:widget:1.4.2", content)
        self.assertNotIn("widget:+", content)
        self.assertNotIn(_FAKE_TOKEN, res)

    def test_manifest_fixes_exported_and_rebuilds(self):
        fake = FakeGitHub(
            [("failure", LOG_MANIFEST), ("success", "")],
            {"AndroidManifest.xml": MANIFEST})
        res = _run_selfheal(fake)
        self.assertIn("✅", res, res)
        self.assertEqual(len(fake.dispatch_calls), 2)
        self.assertEqual(len(fake.push_calls), 1)
        path, content, _msg = fake.push_calls[0]
        self.assertEqual(path, "AndroidManifest.xml")
        self.assertIn('android:exported="true"', content)
        self.assertNotIn(_FAKE_TOKEN, res)

    def test_missing_secret_never_triggers_a_fix(self):
        fake = FakeGitHub(
            [("failure", LOG_MISSING_SECRET), ("success", "")],
            {"app/build.gradle": BUILD_GRADLE,
             "AndroidManifest.xml": MANIFEST})
        res = _run_selfheal(fake)
        self.assertIn("secret", res.lower(), res)
        self.assertIn("Final: build holo na", res, res)
        # Exactly ONE dispatch, ZERO pushes — a secret is never invented.
        self.assertEqual(len(fake.dispatch_calls), 1)
        self.assertEqual(len(fake.push_calls), 0)
        self.assertNotIn(_FAKE_TOKEN, res)

    def test_syntax_known_import_fixed(self):
        fake = FakeGitHub(
            [("failure", LOG_SYNTAX_KNOWN), ("success", "")],
            {"app/src/main/java/com/example/MainActivity.kt": MAIN_ACTIVITY_KT})
        res = _run_selfheal(fake)
        self.assertIn("✅", res, res)
        self.assertEqual(len(fake.dispatch_calls), 2)
        self.assertEqual(len(fake.push_calls), 1)
        path, content, _msg = fake.push_calls[0]
        self.assertEqual(path, "app/src/main/java/com/example/MainActivity.kt")
        self.assertIn("import android.widget.Toast", content)
        self.assertNotIn(_FAKE_TOKEN, res)

    def test_syntax_unknown_stops_with_file_and_line(self):
        fake = FakeGitHub(
            [("failure", LOG_SYNTAX_UNKNOWN), ("success", "")],
            {"app/src/main/java/com/example/MainActivity.kt": MAIN_ACTIVITY_KT})
        res = _run_selfheal(fake)
        self.assertIn("MainActivity.kt:12", res, res)
        self.assertIn("Final: build holo na", res, res)
        self.assertEqual(len(fake.dispatch_calls), 1)
        self.assertEqual(len(fake.push_calls), 0)

    def test_transient_redispatches_unchanged(self):
        fake = FakeGitHub(
            [("failure", LOG_TRANSIENT), ("success", "")],
            {"app/build.gradle": BUILD_GRADLE})
        res = _run_selfheal(fake)
        self.assertIn("✅", res, res)
        self.assertEqual(len(fake.dispatch_calls), 2)
        # Transient = re-dispatch unchanged: no file was touched.
        self.assertEqual(len(fake.push_calls), 0)

    def test_attempts_cap_at_three(self):
        fake = FakeGitHub(
            [("failure", LOG_TRANSIENT)] * 5,
            {"app/build.gradle": BUILD_GRADLE})
        res = _run_selfheal(fake)
        self.assertEqual(len(fake.dispatch_calls), 3, res)
        self.assertIn("3 bar", res, res)
        self.assertEqual(len(fake.push_calls), 0)

    def test_success_first_try(self):
        fake = FakeGitHub([("success", "")])
        res = _run_selfheal(fake)
        self.assertIn("✅", res, res)
        self.assertIn("attempt 1/3", res, res)
        self.assertEqual(len(fake.dispatch_calls), 1)

    def test_never_raises(self):
        # Bad inputs and a raising dispatch both return messages.
        fake = FakeGitHub([("success", "")])
        res = apk_selfheal.build_apk_selfheal(
            "", "", request_fn=fake.request, dispatch_fn=fake.dispatch,
            log_fn=fake.log, sleep_fn=lambda s: None)
        self.assertIsInstance(res, str)
        self.assertIn("owner/name", res, res)

        def _boom(*a, **k):
            raise RuntimeError("boom")

        res = apk_selfheal.build_apk_selfheal(
            "someone/my-app", "build-apk.yml", request_fn=fake.request,
            dispatch_fn=_boom, log_fn=fake.log,
            sleep_fn=lambda s: None, max_polls=1)
        self.assertIsInstance(res, str)
        self.assertIn("Final: build holo na", res, res)
        self.assertEqual(len(fake.dispatch_calls), 0)


# ── automation fix ───────────────────────────────────────────────────────────

class FakeEngine:
    """Minimal stand-in for core.automation.ENGINE."""

    def __init__(self, task, results, raise_on_run=False):
        self.task = dict(task)
        self.results = list(results)
        self.raise_on_run = raise_on_run
        self.calls = 0
        self.updated = []
        self._history = []

    def get_task(self, task_id):
        return dict(self.task) if task_id == self.task.get("id") else None

    def run_task_now(self, task_id):
        self.calls += 1
        if self.raise_on_run:
            raise RuntimeError("runner boom")
        res = self.results.pop(0) if self.results else "✅ done"
        failed = res.startswith("❌")
        import re as _re
        tool_m = _re.search(r"step '([^']+)'", res)
        tool = tool_m.group(1) if tool_m else "weather_report"
        self._history.append({
            "task_id": task_id,
            "status": "failed" if failed else "ok",
            "steps": [{"tool": tool, "ok": not failed,
                       "result": res[:200]}] if failed else [],
        })
        return res

    def history(self, task_id):
        return list(self._history)

    def update_task(self, task_id, patch):
        self.updated.append(patch)
        for key, value in patch.items():
            self.task[key] = value
        return True


_TASK = {
    "id": "abc123",
    "name": "Morning briefing",
    "steps": [
        {"tool": "weather_report", "args": {"city": "Kolkata"}},
        {"tool": "web_search", "args": {"query": "top news today"}},
    ],
}


class TestAutomationFix(unittest.TestCase):
    def test_success_first_try(self):
        eng = FakeEngine(_TASK, ["✅ Morning briefing: 2/2 steps done in 1.2s"])
        res = automation_fix.run_automation_with_fix(
            "abc123", engine=eng, sleep_fn=lambda s: None)
        self.assertIn("✅", res, res)
        self.assertEqual(eng.calls, 1)

    def test_timeout_retried_then_success(self):
        eng = FakeEngine(_TASK, [
            "❌ Morning briefing: step 'weather_report' failed (retried once) — timed out after 30s",
            "✅ Morning briefing: 2/2 steps done in 3.1s",
        ])
        res = automation_fix.run_automation_with_fix(
            "abc123", engine=eng, sleep_fn=lambda s: None)
        self.assertIn("✅", res, res)
        self.assertIn("Attempt 2", res, res)
        self.assertEqual(eng.calls, 2)

    def test_timeout_bumps_timeout_arg(self):
        task = {"id": "abc123", "name": "Slow search",
                "steps": [{"tool": "web_search",
                           "args": {"query": "news", "timeout": 10}}]}
        eng = FakeEngine(task, [
            "❌ Slow search: step 'web_search' failed (retried once) — timed out",
            "✅ Slow search: 1/1 steps done in 2.0s",
        ])
        res = automation_fix.run_automation_with_fix(
            "abc123", engine=eng, sleep_fn=lambda s: None)
        self.assertIn("✅", res, res)
        self.assertEqual(len(eng.updated), 1)
        new_timeout = eng.updated[0]["steps"][0]["args"]["timeout"]
        self.assertEqual(new_timeout, 20)

    def test_missing_input_stops_and_asks(self):
        task = {"id": "abc123", "name": "Social post",
                "steps": [{"tool": "facebook_post",
                           "args": {"message": "[EDIT: your Facebook post text]"}}]}
        eng = FakeEngine(task, [
            "❌ Social post: step 'facebook_post' failed (retried once) — empty message",
        ])
        res = automation_fix.run_automation_with_fix(
            "abc123", engine=eng, sleep_fn=lambda s: None)
        self.assertIn("Final: automation choleni", res, res)
        self.assertIn("[EDIT", res, res)
        # Never retried blindly: exactly one run.
        self.assertEqual(eng.calls, 1)

    def test_step_error_cap_at_three(self):
        eng = FakeEngine(_TASK, [
            "❌ Morning briefing: step 'weather_report' failed (retried once) — 500 error",
        ] * 5)
        res = automation_fix.run_automation_with_fix(
            "abc123", engine=eng, sleep_fn=lambda s: None)
        self.assertEqual(eng.calls, 3, res)
        self.assertIn("3 bar", res, res)

    def test_unknown_task(self):
        eng = FakeEngine(_TASK, [])
        res = automation_fix.run_automation_with_fix(
            "nope", engine=eng, sleep_fn=lambda s: None)
        self.assertIn("pelam na", res, res)
        self.assertEqual(eng.calls, 0)

    def test_condition_not_retried(self):
        eng = FakeEngine(_TASK, [
            "❌ Morning briefing: skipped — condition not met (offline — no route to 8.8.8.8:53)",
        ])
        res = automation_fix.run_automation_with_fix(
            "abc123", engine=eng, sleep_fn=lambda s: None)
        self.assertIn("condition", res.lower(), res)
        self.assertEqual(eng.calls, 1)

    def test_never_raises(self):
        eng = FakeEngine(_TASK, [], raise_on_run=True)
        res = automation_fix.run_automation_with_fix(
            "abc123", engine=eng, sleep_fn=lambda s: None)
        self.assertIsInstance(res, str)
        self.assertEqual(eng.calls, 3, res)  # retried to the cap, never raised
        res2 = automation_fix.run_automation_with_fix(
            "", engine=eng, sleep_fn=lambda s: None)
        self.assertIsInstance(res2, str)


class TestDiagnose(unittest.TestCase):
    def test_kinds(self):
        task = {"id": "x", "name": "t", "steps": []}
        self.assertEqual(
            automation_fix.diagnose_failure(
                task, "❌ t: step 'a' failed — timed out", [])["kind"],
            "timeout")
        self.assertEqual(
            automation_fix.diagnose_failure(
                task, "❌ t: step 'a' failed — 500", [])["kind"],
            "step_error")
        self.assertEqual(
            automation_fix.diagnose_failure(
                task, "❌ t: skipped — condition not met (offline)", [])["kind"],
            "condition")
        task2 = {"id": "x", "name": "t",
                 "steps": [{"tool": "facebook_post",
                            "args": {"message": "[EDIT: text]"}}]}
        self.assertEqual(
            automation_fix.diagnose_failure(task2, "❌ t: failed", [])["kind"],
            "missing_input")


# ── plugins ──────────────────────────────────────────────────────────────────

class TestPlugins(unittest.TestCase):
    def test_plugin_contracts(self):
        import plugins.apk_selfheal as p1
        import plugins.automation_fix as p2
        self.assertEqual(p1.PLUGIN["name"], "apk_build_selfheal")
        self.assertEqual(p2.PLUGIN["name"], "automation_fix")
        for p in (p1, p2):
            self.assertIn("description", p.PLUGIN)
            self.assertIn("parameters", p.PLUGIN)
            self.assertTrue(callable(p.run))
        # Missing params → a message, never a raise, never a thread.
        self.assertIn("repo", p1.run({}, player=None))
        self.assertIn("automation_id", p2.run({}, player=None))


if __name__ == "__main__":
    unittest.main()
