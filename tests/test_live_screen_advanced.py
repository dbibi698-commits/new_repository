"""tests/test_live_screen_advanced.py — 📺 LIVE SCREEN smoother: adaptive
poll interval (10–20 fps) + real measured fps.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only. No phone, no network.
"""
from __future__ import annotations

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import live_screen as ls  # noqa: E402


class TestAdaptInterval(unittest.TestCase):
    def test_fresh_frame_speeds_up(self):
        self.assertLess(ls.adapt_interval(1.0 / 15.0, True), 1.0 / 12.0)

    def test_stale_poll_slows_down(self):
        self.assertGreater(ls.adapt_interval(1.0 / 15.0, False), 1.0 / 15.0)

    def test_never_faster_than_20fps(self):
        cur = 1.0 / 15.0
        for _ in range(50):
            cur = ls.adapt_interval(cur, True)
        self.assertGreaterEqual(cur, 1.0 / 20.0 - 1e-9)

    def test_never_slower_than_10fps(self):
        cur = 1.0 / 15.0
        for _ in range(50):
            cur = ls.adapt_interval(cur, False)
        self.assertLessEqual(cur, 1.0 / 10.0 + 1e-9)

    def test_starts_at_15fps(self):
        self.assertAlmostEqual(ls._POLL_INTERVAL, 1.0 / 15.0)


class TestMeasuredFps(unittest.TestCase):
    def test_default_fps_is_15(self):
        streamer = ls.LiveScreenStreamer(link=None)
        self.assertEqual(streamer._fps, 15.0)
        self.assertAlmostEqual(streamer._interval, 1.0 / 15.0)

    def test_measured_fps_from_recorded_frames(self):
        streamer = ls.LiveScreenStreamer(link=None)
        now = time.monotonic()
        for i in range(4):
            streamer._record_frame(now=now - 0.1 * i)
        # 4 frames in the last 2 s -> 2.0 fps.
        self.assertAlmostEqual(streamer.measured_fps, 2.0)

    def test_measured_fps_zero_when_idle(self):
        streamer = ls.LiveScreenStreamer(link=None)
        self.assertEqual(streamer.measured_fps, 0.0)

    def test_old_frames_drop_out(self):
        streamer = ls.LiveScreenStreamer(link=None)
        now = time.monotonic()
        streamer._record_frame(now=now - 5.0)
        self.assertEqual(streamer.measured_fps, 0.0)

    def test_live_status_is_plain_words(self):
        # Unpaired: the status honestly says the phone is not paired.
        # The adaptive part is covered by adapt_interval bounds above.
        text = ls.live_status()
        self.assertTrue(text.strip())
        self.assertIn("pair", text.lower())
        self.assertEqual(ls._FPS_MIN, 10.0)
        self.assertEqual(ls._FPS_MAX, 20.0)


if __name__ == "__main__":
    unittest.main()
