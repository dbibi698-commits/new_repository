"""tests/test_commander_advanced.py — 🎖️ COMMANDER smarter: auto-plan,
auto-delegate, retry with another worker, plan memory.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only. Config is monkeypatched to an in-memory dict (same pattern
as tests/test_commander.py). Real dispatches are exercised through
injected execute_fn fakes; the Gemini retry path is mocked.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import commander as cmd  # noqa: E402
from tests.test_commander import _ConfigPatch  # noqa: E402


class CommanderAdvancedBase(unittest.TestCase):
    def setUp(self):
        self._cfg = _ConfigPatch(self)
        self._cfg.__enter__()
        try:
            from core import agents as _ag
            _ag.REGISTRY.reset_all()
        except Exception:
            pass

    def tearDown(self):
        self._cfg.__exit__()
        try:
            from core import agents as _ag
            _ag.REGISTRY.reset_all()
        except Exception:
            pass


class TestDecompose(CommanderAdvancedBase):
    def test_multi_clause_splits_per_worker(self):
        plan = cmd.decompose_order(
            "ekta dashboard banao and chrome kholo google.com")
        self.assertEqual(len(plan), 2, plan)
        self.assertEqual(plan[0]["intent"], "software_build")
        self.assertEqual(plan[0]["agent_id"], "builder")
        self.assertEqual(plan[1]["intent"], "browser_control")
        self.assertEqual(plan[1]["agent_id"], "browser")

    def test_single_clause_unchanged(self):
        plan = cmd.decompose_order("ekta todo dashboard banao")
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["intent"], "software_build")

    def test_same_intent_clauses_fold(self):
        plan = cmd.decompose_order(
            "ekta dashboard banao and ekta website banao")
        self.assertEqual(len(plan), 1)
        self.assertIn("dashboard", plan[0]["subtask"])
        self.assertIn("website", plan[0]["subtask"])

    def test_general_clause_routes(self):
        plan = cmd.decompose_order("youtube-e video upload koro")
        self.assertTrue(plan)
        self.assertEqual(plan[0]["agent_id"], "media")

    def test_plan_order_is_decompose(self):
        self.assertEqual(
            cmd.plan_order("ekta dashboard banao and chrome kholo x.com"),
            cmd.decompose_order(
                "ekta dashboard banao and chrome kholo x.com"))


class TestPickWorker(CommanderAdvancedBase):
    def test_intent_worker_first(self):
        cands = cmd.pick_worker("software_build", "ekta dashboard banao")
        self.assertEqual(cands[0], "builder")
        self.assertIn("commander", cands)

    def test_routed_agent_in_candidates(self):
        cands = cmd.pick_worker("general", "youtube-e video upload koro")
        self.assertIn("media", cands)

    def test_exclude_drops_tried(self):
        cands = cmd.pick_worker("software_build", "ekta dashboard banao",
                                exclude=("builder",))
        self.assertNotIn("builder", cands)
        self.assertIn("commander", cands)


class TestRetry(CommanderAdvancedBase):
    def test_retry_with_other_worker_then_success(self):
        calls = {"n": 0}

        def _fake(step, payload):
            calls["n"] += 1
            if calls["n"] == 1:
                return "⚠️ kichu holo na"
            return "fake done on retry"

        res = cmd.issue_order("ekta dashboard banao", execute_fn=_fake)
        self.assertTrue(res["ok"], res)
        self.assertEqual(calls["n"], 2)
        step = res["plan"][0]
        self.assertTrue(step.get("retried"))
        self.assertEqual(step.get("tried"), ["builder", "commander"])
        self.assertEqual(step["status"], "done")
        text = cmd.status_text()
        self.assertIn("🔁 retry", text)

    def test_both_workers_fail_stays_error(self):
        res = cmd.issue_order(
            "ekta dashboard banao",
            execute_fn=lambda s, p: "⚠️ kichu holo na")
        self.assertFalse(res["ok"])
        self.assertEqual(res["plan"][0]["status"], "error")
        self.assertTrue(res["plan"][0].get("retried"))


class TestPlanMemory(CommanderAdvancedBase):
    def test_repeated_order_reuses_plan(self):
        fake = lambda s, p: "fake done"
        res1 = cmd.issue_order("ekta dashboard banao", execute_fn=fake)
        self.assertTrue(res1["ok"], res1)
        res2 = cmd.issue_order("ekta dashboard banao", execute_fn=fake)
        self.assertTrue(res2["ok"], res2)
        cur = cmd.current_order()
        self.assertTrue(cur.get("reused"))
        self.assertIn("Ager plan reuse", cmd.status_text())

    def test_different_order_does_not_reuse(self):
        fake = lambda s, p: "fake done"
        cmd.issue_order("ekta dashboard banao", execute_fn=fake)
        cmd.issue_order("python run: print(1)", execute_fn=fake)
        cur = cmd.current_order()
        self.assertFalse(cur.get("reused"))

    def test_history_capped_at_20(self):
        for i in range(25):
            cmd._save_history_entry(f"order number {i}", "general",
                                    [{"agent_id": "commander",
                                      "intent": "general",
                                      "subtask": f"order number {i}"}], True)
        self.assertEqual(len(cmd._history()), 20)
        norms = [e["norm"] for e in cmd._history()]
        self.assertNotIn("order number 0", norms)
        self.assertIn("order number 24", norms)

    def test_failed_order_not_reused(self):
        cmd.issue_order("ekta dashboard banao",
                        execute_fn=lambda s, p: "⚠️ kichu holo na")
        self.assertEqual(cmd.find_similar_plan("ekta dashboard banao"), [])


if __name__ == "__main__":
    unittest.main()
