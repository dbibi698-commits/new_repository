"""tests/test_fast_reply.py — ⚡ FAST REPLIES: instant local answers
(time/date/calculator/status/greetings/mode switches), ack + stall
lines, and the honest rule that a full Gemini reply is never claimed
to be instant (answer_locally returns None for model work).

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only. Config is monkeypatched — no real config is touched.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import fast_reply as fr  # noqa: E402


class TestAckAndStall(unittest.TestCase):
    def test_ack_line_short(self):
        line = fr.ack_line()
        self.assertTrue(line)
        self.assertLess(len(line), 80)

    def test_stall_line_mentions_reconnect(self):
        line = fr.stall_line()
        self.assertTrue(line)
        self.assertIn(line, fr._STALL_LINES)
        # Every rotating line must say it is reconnecting / retrying.
        for l in fr._STALL_LINES:
            self.assertTrue("korchi" in l or "khulchi" in l, l)


class TestCalculator(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(fr.calc("2 + 3 * 4"), (True, 14))
        self.assertEqual(fr.calc("12 * 12"), (True, 144))
        self.assertEqual(fr.calc("10 / 4"), (True, 2.5))
        ok, err = fr.calc("1 / 0")
        self.assertFalse(ok)
        self.assertIn("0 diye", err)

    def test_try_calc_picks_expression(self):
        # try_calc returns the expression string; calc() evaluates it.
        self.assertEqual(fr.try_calc("2+3 koto?"), "2+3")
        self.assertEqual(fr.try_calc("12 * 12"), "12 * 12")
        self.assertEqual(fr.calc(fr.try_calc("2+3 koto?")), (True, 5))
        self.assertIsNone(fr.try_calc("hello world"))

    def test_no_eval_danger(self):
        self.assertIsNone(fr.try_calc("__import__('os').system('x')"))
        self.assertIsNone(fr.try_calc("open('/etc/passwd')"))


class TestRouter(unittest.TestCase):
    def test_time(self):
        out = fr.answer_locally("time koto?")
        self.assertIsNotNone(out)
        self.assertIn("Ekhon", out)

    def test_date(self):
        out = fr.answer_locally("aaj ki bar?")
        self.assertIsNotNone(out)
        self.assertIn("Aaj", out)

    def test_greeting(self):
        out = fr.answer_locally("hello")
        self.assertIsNotNone(out)
        self.assertIn("Hey", out)

    def test_calculator_route(self):
        out = fr.answer_locally("12 * 12")
        self.assertIsNotNone(out)
        self.assertIn("144", out)

    def test_status_route(self):
        out = fr.answer_locally("status ki?")
        self.assertIsNotNone(out)
        self.assertIn("Mark", out)

    def test_model_work_returns_none(self):
        # A real question needs the model — never answered locally.
        self.assertIsNone(fr.answer_locally(
            "ekta kobita likhe dao brishti niye"))
        self.assertIsNone(fr.answer_locally(""))
        self.assertIsNone(fr.answer_locally("   "))

    def test_mode_switch_persists(self):
        store = {}
        with mock.patch("memory.config_manager.get_plugin_config",
                        lambda ns: dict(store.get(ns) or {})), \
                mock.patch("memory.config_manager.save_plugin_config",
                           lambda ns, v: store.__setitem__(ns, dict(v))):
            out = fr.answer_locally("comedy mode on koro")
            self.assertIsNotNone(out)
            self.assertIn("Comedy", out)
            self.assertEqual(store.get("jarvis_mood", {}).get("mood"),
                             "comedy")
            out = fr.answer_locally("girlfriend mode on")
            self.assertIn("Girlfriend", out)
            out = fr.answer_locally("boss mode")
            self.assertIn("Boss", out)

    def test_bengali_only_toggle(self):
        with mock.patch("core.language.set_bengali_only") as fake:
            out = fr.answer_locally("shudhu bangla on")
            self.assertIsNotNone(out)
            self.assertIn("Bengali-only ON", out)
            fake.assert_called_once_with(True)
            out = fr.answer_locally("bengali only off")
            self.assertIn("Bengali-only OFF", out)
            fake.assert_called_with(False)


if __name__ == "__main__":
    unittest.main()
