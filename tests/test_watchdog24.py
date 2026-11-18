"""tests/test_watchdog24.py — 🕐 24H RUNNING: uptime text, supervisor
(register/check/restart), phone background status (last-seen as an ISO
string, a float, or a callable — never a crash), and the PC-off honesty
line in status_text.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only. No real services are registered; the module-level registry
is saved + restored around the tests.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import watchdog24 as w  # noqa: E402


class TestUptime(unittest.TestCase):
    def test_uptime_text_format(self):
        t = w.uptime_text()
        self.assertTrue(t)
        self.assertRegex(t, r"(\d+s|\d+m|\d+h|\d+d)")

    def test_uptime_seconds_non_negative(self):
        self.assertGreaterEqual(w.uptime_seconds(), 0.0)

    def test_started_at_text(self):
        self.assertRegex(w.started_at_text(), r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")


class TestSupervisor(unittest.TestCase):
    def setUp(self):
        self._saved = dict(w._SERVICES)

    def tearDown(self):
        w._SERVICES.clear()
        w._SERVICES.update(self._saved)

    def test_alive_service_not_restarted(self):
        w.register_service("svc-alive", lambda: True,
                           lambda: "should not run")
        out = w.check_now()
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["alive"])
        self.assertFalse(out[0]["restarted"])
        self.assertEqual(out[0]["restarts"], 0)

    def test_dead_service_restarted_once(self):
        calls = []
        state = {"alive": False}

        def _restart():
            state["alive"] = True
            calls.append(1)
            return "restarted ok"

        w.register_service("svc-dead", lambda: state["alive"], _restart)
        out = w.check_now()
        self.assertFalse(out[0]["alive"])  # was dead at check time
        self.assertTrue(out[0]["restarted"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(out[0]["restarts"], 1)
        out2 = w.check_now()
        self.assertTrue(out2[0]["alive"])
        self.assertEqual(len(calls), 1)  # no second restart

    def test_restart_failure_reported(self):
        def _boom():
            raise RuntimeError("nope")

        w.register_service("svc-boom", lambda: False, _boom)
        out = w.check_now()
        self.assertFalse(out[0]["restarted"])
        self.assertIn("nope", out[0]["note"])

    def test_start_stop_watchdog(self):
        self.assertTrue(w.start_watchdog(interval_s=60))
        self.assertTrue(w.watchdog_running())
        w.stop_watchdog()
        self.assertFalse(w.watchdog_running())


class TestPhoneBackground(unittest.TestCase):
    def _fake_link(self, paired=True, last_seen=""):
        link = mock.Mock()
        link.paired = paired
        link.last_phone_seen = last_seen
        return link

    def test_not_paired(self):
        import core.jarvis_link as jl
        with mock.patch.object(jl, "LINK", None):
            self.assertIn("link load", w.phone_background_text())

    def test_paired_never_seen(self):
        import core.jarvis_link as jl
        with mock.patch.object(jl, "LINK", self._fake_link(True, "")):
            self.assertIn("ekhono kono", w.phone_background_text())

    def test_paired_seen_now_iso_string(self):
        import core.jarvis_link as jl
        now = datetime.now().isoformat(timespec="seconds")
        with mock.patch.object(jl, "LINK", self._fake_link(True, now)):
            self.assertIn("cholche", w.phone_background_text())

    def test_paired_seen_long_ago(self):
        import core.jarvis_link as jl
        old = (datetime.now() - timedelta(hours=2)).isoformat(
            timespec="seconds")
        with mock.patch.object(jl, "LINK", self._fake_link(True, old)):
            txt = w.phone_background_text()
            self.assertIn("2h", txt)

    def test_status_text_has_pc_off_honesty(self):
        txt = w.status_text()
        self.assertIn("Uptime", txt)
        self.assertIn("PC puropuri bondho", txt)


if __name__ == "__main__":
    unittest.main()
