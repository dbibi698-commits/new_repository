"""tests/test_auto_tasks.py — 📋 AUTOMATIC TASKS: natural-language
parsing (Bengali + English), creation/scheduling via the Commander,
executor attribution (phone vs PC), offline queue + retry, and the
phone TASK_REPORT:: handling.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only. ENGINE + config + relay are mocked.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import auto_tasks as at  # noqa: E402


class TestParse(unittest.TestCase):
    def test_daily_bengali(self):
        spec = at.parse_task_text("protidin sokal 8-tay weather report dao")
        self.assertEqual(spec["kind"], "daily")
        self.assertEqual(spec["time"], "08:00")
        self.assertIn("weather", spec["order"].lower())

    def test_weekly_bengali(self):
        spec = at.parse_task_text("proti Robibar Downloads organize koro")
        self.assertEqual(spec["kind"], "weekly")
        self.assertEqual(spec["weekday"], 6)

    def test_monthly(self):
        spec = at.parse_task_text("proti masher 1 tarikh report banao")
        self.assertEqual(spec["kind"], "monthly")
        self.assertEqual(spec["day"], 1)

    def test_once_in_minutes(self):
        spec = at.parse_task_text("1 minute pore ekta test report banao")
        self.assertEqual(spec["kind"], "once")
        self.assertIsNotNone(spec["at"])
        at_time = datetime.fromisoformat(spec["at"])
        self.assertLess((at_time - datetime.now()).total_seconds(), 120)

    def test_executor_phone(self):
        spec = at.parse_task_text("phone-e protidin sokal 8-tay message pathao")
        self.assertEqual(spec["executor"], "phone")

    def test_executor_pc(self):
        spec = at.parse_task_text("pc-te protidin backup nao")
        self.assertEqual(spec["executor"], "pc")

    def test_english_daily(self):
        spec = at.parse_task_text("every day at 9:00 send me the news")
        self.assertEqual(spec["kind"], "daily")
        self.assertEqual(spec["time"], "09:00")


class TestCreateAndExecutor(unittest.TestCase):
    def _engine_fake(self):
        eng = mock.Mock()
        created = {}

        def _create(raw):
            tid = "task-123"
            created["raw"] = raw
            return tid

        eng.create_task.side_effect = _create
        eng.list_tasks.return_value = []
        eng.history.return_value = []
        return eng, created

    def test_create_daily_via_commander(self):
        store = {}
        eng, created = self._engine_fake()
        with mock.patch("core.automation.ENGINE", eng), \
                mock.patch("core.auto_tasks.get_plugin_config",
                           lambda ns: dict(store.get(ns) or {})), \
                mock.patch("core.auto_tasks.save_plugin_config",
                           lambda ns, v: store.__setitem__(ns, dict(v))):
            out = at.create_task_from_text(
                "protidin sokal 8-tay weather report dao")
        self.assertIn("Task banalam", out)
        self.assertIn("daily", out)
        raw = created["raw"]
        self.assertEqual(raw["trigger"]["kind"], "daily")
        self.assertEqual(raw["trigger"]["time"], "08:00")
        # The step runs through the Commander.
        self.assertEqual(raw["steps"][0]["tool"], "commander")
        self.assertIn("weather", raw["steps"][0]["args"]["order"].lower())
        # Executor metadata is stored separately (automation drops extras).
        self.assertEqual(store["auto_tasks_meta"]["task-123"]["executor"],
                         "auto")

    def test_create_phone_task_sends_to_phone(self):
        store = {}
        eng, created = self._engine_fake()
        link = mock.Mock()
        link.paired = True
        link.send_text.return_value = True
        with mock.patch("core.automation.ENGINE", eng), \
                mock.patch("core.jarvis_link.LINK", link), \
                mock.patch("core.auto_tasks.get_plugin_config",
                           lambda ns: dict(store.get(ns) or {})), \
                mock.patch("core.auto_tasks.save_plugin_config",
                           lambda ns, v: store.__setitem__(ns, dict(v))):
            out = at.create_task_from_text(
                "phone-e protidin sokal 8-tay message pathao")
        self.assertIn("phone-e pathalam", out)
        sent = link.send_text.call_args[0][0]
        self.assertTrue(sent.startswith("TASK_SCHEDULE::"))
        self.assertIn("message", sent.lower())

    def test_create_unpaired_phone_warns(self):
        store = {}
        eng, created = self._engine_fake()
        link = mock.Mock()
        link.paired = False
        with mock.patch("core.automation.ENGINE", eng), \
                mock.patch("core.jarvis_link.LINK", link), \
                mock.patch("core.auto_tasks.get_plugin_config",
                           lambda ns: dict(store.get(ns) or {})), \
                mock.patch("core.auto_tasks.save_plugin_config",
                           lambda ns, v: store.__setitem__(ns, dict(v))):
            out = at.create_task_from_text(
                "phone-e protidin sokal 8-tay message pathao")
        self.assertIn("pair kora nei", out)


class TestTaskReport(unittest.TestCase):
    def test_phone_report_recorded_with_executor(self):
        eng = mock.Mock()
        with mock.patch("core.automation.ENGINE", eng):
            out = at.handle_task_report(
                {"name": "Morning message", "status": "ok",
                 "result": "sent to Rahim"})
        self.assertIn("Phone task complete", out)
        eng.record_external_run.assert_called_once()
        args, kwargs = eng.record_external_run.call_args
        self.assertEqual(args[0], "Morning message")
        self.assertEqual(args[1], "ok")
        self.assertEqual(kwargs.get("executor"), "phone")

    def test_phone_report_json_string(self):
        eng = mock.Mock()
        with mock.patch("core.automation.ENGINE", eng):
            out = at.handle_task_report(
                '{"name": "Upload", "status": "failed", '
                '"result": "no internet"}')
        self.assertIn("Upload", out)
        eng.record_external_run.assert_called_once()

    def test_tasks_panel_shows_executor_and_pc_off_note(self):
        eng = mock.Mock()
        eng.list_tasks.return_value = [
            {"id": "t1", "name": "Morning", "enabled": True,
             "trigger": {"kind": "daily"}, "next_run": "2026-11-19T08:00:00"}]
        eng.history.return_value = [
            {"task_name": "Morning", "status": "ok",
             "finished_at": "2026-11-18T08:00:00", "executor": "phone",
             "note": "sent"}]
        store = {"auto_tasks_meta": {"t1": {"executor": "phone"}},
                 "auto_tasks": {"offline_queue": []}}
        with mock.patch("core.automation.ENGINE", eng), \
                mock.patch("core.auto_tasks.get_plugin_config",
                           lambda ns: dict(store.get(ns) or {})):
            txt = at.tasks_panel_text()
        self.assertIn("[phone]", txt)
        self.assertIn("PC OFF thakle", txt)
        self.assertIn("executor: phone", txt)


class TestOfflineQueue(unittest.TestCase):
    def test_mark_and_retry_when_online(self):
        store = {}
        eng = mock.Mock()
        eng.run_task_now.return_value = "Task cholllo ✅"
        with mock.patch("core.auto_tasks.get_plugin_config",
                        lambda ns: dict(store.get(ns) or {})), \
                mock.patch("core.auto_tasks.save_plugin_config",
                           lambda ns, v: store.__setitem__(ns, dict(v))):
            at.mark_offline("t9", "no internet")
            self.assertEqual(len(store["auto_tasks"]["offline_queue"]), 1)
            with mock.patch("core.auto_tasks.check_internet",
                            return_value=True), \
                    mock.patch("core.automation.ENGINE", eng):
                out = at.retry_offline_tasks()
        self.assertIn("1 ta task cholllo", out)
        eng.run_task_now.assert_called_once_with("t9")

    def test_retry_stays_queued_when_offline(self):
        store = {"auto_tasks": {"offline_queue": [
            {"task_id": "t9", "reason": "no internet",
             "at": "2026-11-18T10:00:00"}]}}
        with mock.patch("core.auto_tasks.get_plugin_config",
                        lambda ns: dict(store.get(ns) or {})), \
                mock.patch("core.auto_tasks.save_plugin_config",
                           lambda ns, v: store.__setitem__(ns, dict(v))), \
                mock.patch("core.auto_tasks.check_internet",
                           return_value=False):
            out = at.retry_offline_tasks()
        self.assertIn("ekhono internet nei", out)

    def test_monthly_next_run(self):
        from core.automation import compute_next_run
        now = datetime(2026, 11, 18, 10, 0, 0)
        task = {"trigger": {"type": "time", "kind": "monthly",
                            "time": "08:00", "day": 1}}
        nxt = compute_next_run(task, now=now)
        self.assertTrue(nxt.startswith("2026-12-01T08:00"))
        task2 = {"trigger": {"type": "time", "kind": "monthly",
                             "time": "08:00", "day": 31}}
        nxt2 = compute_next_run(task2, now=datetime(2026, 4, 15, 10, 0, 0))
        self.assertTrue(nxt2.startswith("2026-04-30T08:00"))


if __name__ == "__main__":
    unittest.main()
