"""tests/test_voice_settings.py — 🎙️ VOICE SETTINGS: validation clamps,
in-memory persistence, SAPI/espeak mappings, describe.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only. The store is an injected dict — no real config is touched.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import voice_settings as vs  # noqa: E402


class TestValidation(unittest.TestCase):
    def test_defaults(self):
        s = vs.get_settings(store={})
        self.assertEqual(s, {"rate": 1.0, "pitch": 1.0, "voice": "",
                             "auto_reply_voice": True})

    def test_clamps(self):
        store = {}
        out = vs.set_settings(rate=5.0, pitch=0.1, store=store)
        self.assertEqual(out["rate"], 2.0)
        self.assertEqual(out["pitch"], 0.5)
        out = vs.set_settings(rate=0.0, pitch=9.9, store=store)
        self.assertEqual(out["rate"], 0.5)
        self.assertEqual(out["pitch"], 2.0)

    def test_bad_values_fall_back(self):
        store = {}
        out = vs.set_settings(rate="abc", pitch=None, store=store)
        self.assertEqual(out["rate"], 1.0)

    def test_voice_trimmed_and_capped(self):
        store = {}
        out = vs.set_settings(voice="  Zira  ", store=store)
        self.assertEqual(out["voice"], "Zira")

    def test_auto_reply_toggle(self):
        store = {}
        vs.set_settings(auto_reply_voice=False, store=store)
        self.assertFalse(vs.auto_reply_voice_on(store))
        vs.set_settings(auto_reply_voice=True, store=store)
        self.assertTrue(vs.auto_reply_voice_on(store))

    def test_partial_set_keeps_rest(self):
        store = {}
        vs.set_settings(rate=1.5, voice="Zira", store=store)
        out = vs.set_settings(pitch=0.8, store=store)
        self.assertEqual(out["rate"], 1.5)
        self.assertEqual(out["voice"], "Zira")
        self.assertEqual(out["pitch"], 0.8)


class TestMappings(unittest.TestCase):
    def test_rate_as_sapi(self):
        self.assertEqual(vs.rate_as_sapi(1.0), 0)
        self.assertEqual(vs.rate_as_sapi(2.0), 10)
        self.assertEqual(vs.rate_as_sapi(0.5), -5)
        self.assertEqual(vs.rate_as_sapi(1.5), 5)

    def test_pitch_as_espeak(self):
        self.assertEqual(vs.pitch_as_espeak(1.0), 50)
        self.assertEqual(vs.pitch_as_espeak(2.0), 99)
        self.assertEqual(vs.pitch_as_espeak(0.5), 25)

    def test_tts_cfg_overrides(self):
        store = {}
        vs.set_settings(rate=1.5, voice="Zira", store=store)
        ov = vs.tts_cfg_overrides(store)
        self.assertEqual(ov["rate"], 5)
        self.assertEqual(ov["voice"], "Zira")
        self.assertEqual(ov["speed"], 1.5)
        self.assertEqual(ov["pitch"], 1.0)

    def test_apply_to_config_respects_explicit(self):
        cfg = vs.apply_to_config({"tts_speed": 1.5})
        self.assertEqual(cfg["tts_speed"], 1.5)
        cfg2 = vs.apply_to_config({})
        self.assertEqual(cfg2["tts_speed"], 1.0)

    def test_describe(self):
        store = {}
        vs.set_settings(rate=1.2, pitch=0.9, auto_reply_voice=False,
                        store=store)
        text = vs.describe(store)
        self.assertIn("1.20x", text)
        self.assertIn("0.90x", text)
        self.assertIn("OFF", text)
        self.assertIn("Gemini Live", text)


if __name__ == "__main__":
    unittest.main()
