"""tests/test_live_screen_20fps.py — 📺 LIVE SCREEN 15–20 fps:
adaptive fps bounds (10–20, default 15), real measured fps, the Agora
viewer HTML (full-screen stage + fps readout + subscribe order), and the
phone-reply parsing for the Agora join parameters.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only. No real Agora, no real phone — everything mocked.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import agora_viewer as av  # noqa: E402
from core import live_screen as ls  # noqa: E402


class TestFpsAdaptation(unittest.TestCase):
    def test_default_fps_is_15(self):
        self.assertEqual(ls._POLL_INTERVAL, 1.0 / 15.0)
        self.assertEqual(ls._FPS_MAX, 20)
        self.assertEqual(ls._FPS_MIN, 10)
        s = ls.LiveScreenStreamer()
        self.assertEqual(s._fps, 15.0)

    def test_fresh_frames_speed_up(self):
        nxt = ls.adapt_interval(1.0 / 15.0, got_new=True)
        self.assertLess(nxt, 1.0 / 15.0)
        self.assertGreaterEqual(nxt, 1.0 / 20.0)

    def test_stale_frames_slow_down(self):
        nxt = ls.adapt_interval(1.0 / 15.0, got_new=False)
        self.assertGreater(nxt, 1.0 / 15.0)
        self.assertLessEqual(nxt, 1.0 / 10.0)

    def test_bounds_never_exceeded(self):
        cur = 1.0 / 15.0
        for _ in range(50):
            cur = ls.adapt_interval(cur, got_new=True)
        self.assertAlmostEqual(cur, 1.0 / 20.0, places=6)
        for _ in range(50):
            cur = ls.adapt_interval(cur, got_new=False)
        self.assertAlmostEqual(cur, 1.0 / 10.0, places=6)

    def test_bad_input_is_clamped_to_bounds(self):
        # 0 clamps to the fastest bound (20 fps), huge clamps to 10 fps.
        self.assertEqual(ls.adapt_interval(0, True), 1.0 / 20.0)
        self.assertEqual(ls.adapt_interval(999, False), 1.0 / 10.0)
        self.assertEqual(ls.adapt_interval(None, False), 1.0 / 20.0 * 1.15)

    def test_measured_fps_from_recent_frames(self):
        s = ls.LiveScreenStreamer()
        now = time.monotonic()
        s._record_frame(now - 0.5)
        s._record_frame(now - 1.0)
        s._record_frame(now - 1.5)
        s._record_frame(now - 3.0)  # outside the 2 s window
        self.assertAlmostEqual(s.measured_fps, 1.5)

    def test_measured_fps_idle_is_zero(self):
        self.assertEqual(ls.LiveScreenStreamer().measured_fps, 0.0)

    def test_stale_after_constant(self):
        self.assertEqual(ls._STALE_AFTER_S, 2.0)

    def test_start_needs_paired_phone(self):
        s = ls.LiveScreenStreamer(link=None)
        ok, msg = s.start()
        self.assertFalse(ok)
        self.assertIn("pair kora nei", msg)


class TestAgoraViewer(unittest.TestCase):
    def test_html_fullscreen_stage_and_fps(self):
        html = av.viewer_html("app123", "ch-1", token="tok", uid=1002)
        self.assertIn("app123", html)
        self.assertIn("ch-1", html)
        self.assertIn("tok", html)
        self.assertIn("1002", html)
        self.assertIn("position:fixed;inset:0", html)  # full-screen stage
        self.assertIn("width:100%!important", html)
        self.assertIn("fps", html.lower())
        self.assertIn("AgoraRTC", html)
        self.assertIn("subscribe", html)

    def test_html_no_token_uses_null(self):
        html = av.viewer_html("app123", "ch-1", token="")
        self.assertIn("ch-1", html)
        self.assertIn("TOKEN || null", html)

    def test_parse_json_reply(self):
        blob = '{"app_id": "app1", "channel": "jarvis-live", "token": "tk9"}'
        got = av.parse_phone_reply(blob)
        self.assertEqual(got["app_id"], "app1")
        self.assertEqual(got["channel"], "jarvis-live")
        self.assertEqual(got["token"], "tk9")

    def test_parse_plain_lines(self):
        blob = ("Agora live shuru holo.\n"
                "channel: jarvis-live\n"
                "token: abc123\n"
                "app id: app-xyz")
        got = av.parse_phone_reply(blob)
        self.assertEqual(got["channel"], "jarvis-live")
        self.assertEqual(got["token"], "abc123")
        self.assertEqual(got["app_id"], "app-xyz")

    def test_parse_no_data_returns_empty_dict(self):
        self.assertEqual(av.parse_phone_reply("kono data pelam na"), {})

    def test_write_viewer_file(self):
        url = av.write_viewer("app1", "ch", "tk")
        self.assertTrue(url.startswith("file://"))
        p = av.viewer_path()
        self.assertTrue(p.is_file())
        self.assertIn("AgoraRTC", p.read_text(encoding="utf-8"))
        p.unlink()  # keep the test run clean

    def test_start_agora_live_success(self):
        link = mock.Mock()
        link.paired = True
        link.send_and_wait_result.return_value = (
            '{"app_id": "app1", "channel": "jarvis-live", "token": "tk"}')
        driver = mock.Mock()
        driver.navigate.return_value = (True, "ok")
        with mock.patch("core.agora_viewer.write_viewer",
                        return_value="file:///tmp/agora.html"), \
                mock.patch("core.browser_driver.ensure_driver",
                           return_value=(driver, "playwright", "ok")):
            out = av.start_agora_live(link, timeout=10)
        self.assertTrue(out["ok"])
        self.assertEqual(out["source"], "agora")
        self.assertEqual(out["channel"], "jarvis-live")
        driver.navigate.assert_called_once_with("file:///tmp/agora.html")
        link.send_and_wait_result.assert_called_once()

    def test_start_agora_live_phone_offline(self):
        link = mock.Mock()
        link.paired = False
        out = av.start_agora_live(link, timeout=1)
        self.assertFalse(out["ok"])
        self.assertIn("pair kora nei", out["reason"])

    def test_start_agora_live_no_reply_falls_back(self):
        link = mock.Mock()
        link.paired = True
        link.send_and_wait_result.return_value = ""
        out = av.start_agora_live(link, timeout=10)
        self.assertFalse(out["ok"])
        self.assertIn("Frame stream", out["reason"])

    def test_start_agora_live_no_app_id(self):
        link = mock.Mock()
        link.paired = True
        link.send_and_wait_result.return_value = (
            '{"channel": "jarvis-live", "token": "tk"}')
        out = av.start_agora_live(link, timeout=10)
        self.assertFalse(out["ok"])
        self.assertIn("app id pelam na", out["reason"])


if __name__ == "__main__":
    unittest.main()
