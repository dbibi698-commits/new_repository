"""tests/test_commander.py — 🎖️ COMMANDER: order → plan → delegate → result.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only. Config (command log + current order) is monkeypatched to an
in-memory dict — no real config file is touched. The Python-run and
software-build dispatches are REAL (real subprocess / real localhost
server); browser/Render/APK/Firebase/hosting dispatches are exercised
through injected execute_fn fakes or honest-missing-input paths.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import commander as cmd  # noqa: E402


class _ConfigPatch:
    """In-memory plugin_config for the commander (and agents) namespace."""

    def __init__(self, testcase):
        self.store: dict = {}
        self._get = mock.patch(
            "memory.config_manager.get_plugin_config",
            side_effect=lambda ns: dict(self.store.get(ns, {})))
        self._save = mock.patch(
            "memory.config_manager.save_plugin_config",
            side_effect=lambda ns, values: self.store.setdefault(
                ns, {}).update(values))

    def __enter__(self):
        self._get.start()
        self._save.start()
        return self

    def __exit__(self, *exc):
        self._get.stop()
        self._save.stop()


class CommanderTestBase(unittest.TestCase):
    def setUp(self):
        self._cfg = _ConfigPatch(self)
        self._cfg.__enter__()
        try:
            from core import agents as _ag
            _ag.REGISTRY.reset_all()
        except Exception:
            pass

    def tearDown(self):
        # Stop servers FIRST, while the config patch is still on — the
        # server registry lives in the patched (in-memory) config.
        try:
            from core import software_builder as _sb
            for srv in _sb.list_servers():
                _sb.stop_server(srv["id"])
        except Exception:
            pass
        self._cfg.__exit__()
        try:
            from core import agents as _ag
            _ag.REGISTRY.reset_all()
        except Exception:
            pass


class TestDetectIntent(CommanderTestBase):
    def test_intents(self):
        self.assertEqual(cmd.detect_intent("python run: print(1)"), "python_run")
        self.assertEqual(cmd.detect_intent("ekta dashboard banao"), "software_build")
        self.assertEqual(cmd.detect_intent("ekta website banao"), "software_build")
        self.assertEqual(cmd.detect_intent("apk build koro"), "apk_build")
        self.assertEqual(cmd.detect_intent("render-e deploy koro"), "render_deploy")
        self.assertEqual(cmd.detect_intent("firebase connect koro"), "firebase_connect")
        self.assertEqual(cmd.detect_intent("hosting fix koro"), "hosting_autofix")
        self.assertEqual(cmd.detect_intent("chrome kholo google.com"), "browser_control")
        self.assertEqual(cmd.detect_intent("ei photo-ta 6 copy A4 kore dao"),
                         "photo_edit")
        self.assertEqual(cmd.detect_intent("weather kemon"), "general")

    def test_payload_intent_wins(self):
        self.assertEqual(
            cmd.detect_intent("kuchu", {"intent": "apk_build"}), "apk_build")
        self.assertEqual(
            cmd.detect_intent("kuchu", {"code": "print(1)"}), "python_run")
        self.assertEqual(
            cmd.detect_intent("kuchu", {"spec": "todo app"}), "software_build")


class TestPlan(CommanderTestBase):
    def test_software_build_plan(self):
        plan = cmd.plan_order("ekta todo dashboard banao")
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["agent_id"], "builder")
        self.assertEqual(plan[0]["intent"], "software_build")
        self.assertEqual(plan[0]["status"], "pending")

    def test_python_plan(self):
        plan = cmd.plan_order("python run: print(1)")
        self.assertEqual(plan[0]["agent_id"], "builder")
        self.assertEqual(plan[0]["intent"], "python_run")

    def test_routed_general_plan(self):
        plan = cmd.plan_order("youtube-e video upload koro")
        self.assertTrue(plan)
        self.assertEqual(plan[0]["agent_id"], "media")

    def test_empty_order_no_plan(self):
        self.assertEqual(cmd.plan_order(""), [])
        self.assertEqual(cmd.plan_order("   "), [])


class TestIssueOrder(CommanderTestBase):
    def test_fake_worker_full_flow(self):
        seen = []

        def _fake(step, payload):
            seen.append((step["agent_id"], step["intent"]))
            return "fake built http://localhost:8000"

        res = cmd.issue_order("ekta todo dashboard banao", execute_fn=_fake)
        self.assertTrue(res["ok"], res)
        self.assertEqual(seen, [("builder", "software_build")])
        self.assertEqual(res["plan"][0]["status"], "done")
        self.assertIn("fake built", res["result_text"])
        # Worker status tracked in the registry (completed_count is
        # cumulative across orders — check the delta, not the absolute).
        from core import agents as _ag
        before = _ag.REGISTRY.state("builder")["completed_count"]
        res2 = cmd.issue_order("ekta dashboard banao", execute_fn=_fake)
        self.assertTrue(res2["ok"], res2)
        st = _ag.REGISTRY.state("builder")
        self.assertEqual(st["status"], "done")
        self.assertEqual(st["completed_count"], before + 1)
        # Command log: order → delegate → result → done.
        kinds = [e["kind"] for e in cmd.command_log(10)]
        self.assertIn("order", kinds)
        self.assertIn("delegate", kinds)
        self.assertIn("result", kinds)
        self.assertIn("done", kinds)
        cur = cmd.current_order()
        self.assertEqual(cur.get("status"), "done")
        self.assertIn("dashboard", cur.get("order", ""))

    def test_empty_order(self):
        res = cmd.issue_order("")
        self.assertFalse(res["ok"])
        self.assertIn("Order dao", res["result_text"])

    def test_real_python_run_dispatch(self):
        res = cmd.issue_order("python run: print(7*6)")
        self.assertTrue(res["ok"], res)
        self.assertIn("42", res["result_text"])

    def test_real_software_build_dispatch(self):
        from core import software_builder as _sb
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(_sb, "default_projects_dir",
                                   return_value=Path(tmp)), \
                 mock.patch.object(_sb, "open_in_browser",
                                   return_value="browser mocked"):
                res = cmd.issue_order("ekta todo dashboard banao")
        self.assertTrue(res["ok"], res)
        self.assertIn("http://localhost:", res["result_text"])

    def test_apk_build_without_repo_is_honest(self):
        res = cmd.issue_order("apk build koro")
        self.assertIn("repo dao", res["result_text"])

    def test_render_deploy_without_key_is_honest(self):
        res = cmd.issue_order("render-e deploy koro")
        self.assertIn("Render", res["result_text"])

    def test_failing_worker_marks_error(self):
        res = cmd.issue_order("ekta dashboard banao",
                              execute_fn=lambda s, p: "⚠️ kichu holo na")
        self.assertFalse(res["ok"])
        self.assertEqual(res["plan"][0]["status"], "error")


class TestStatusText(CommanderTestBase):
    def test_panel_shows_order_plan_workers_log(self):
        cmd.issue_order("ekta dashboard banao",
                        execute_fn=lambda s, p: "fake done")
        text = cmd.status_text()
        self.assertIn("COMMANDER", text)
        self.assertIn("dashboard", text)
        self.assertIn("builder", text)
        self.assertIn("✅", text)
        self.assertIn("📜 Log:", text)

    def test_panel_with_no_order(self):
        text = cmd.status_text()
        self.assertIn("COMMANDER", text)
        self.assertIn("Kono order", text)


class TestPhoneRelay(CommanderTestBase):
    def test_prefix_detection(self):
        self.assertTrue(cmd.is_commander_request("COMMANDER::{}"))
        self.assertFalse(cmd.is_commander_request("hello"))

    def test_phone_json_order_python(self):
        out = cmd.handle_phone_request(
            'COMMANDER::{"order": "python run: print(3+4)"}')
        self.assertIn("7", out)

    def test_phone_plain_order(self):
        out = cmd.handle_phone_request("COMMANDER::python run: print(9+1)")
        self.assertIn("10", out)

    def test_phone_empty_order(self):
        self.assertIn("order dao",
                      cmd.handle_phone_request("COMMANDER::{}"))


class TestPluginContract(CommanderTestBase):
    def test_plugin_never_raises(self):
        from plugins import commander as plugin
        self.assertEqual(plugin.PLUGIN["name"], "commander")
        self.assertEqual(plugin.PLUGIN_SETTINGS["widget"], "commander")
        self.assertIn("order dao", plugin.run({}))
        out = plugin.run({"order": "python run: print(5+5)"})
        self.assertIn("10", out)


if __name__ == "__main__":
    unittest.main()
