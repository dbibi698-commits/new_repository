"""tests/test_modes_tone.py — 🎭 MODES: Girlfriend / Comedy / Boss must
actually change the reply (prompt injection + TTS tone), not just the
badge. Comedy is a NEW mood (was only 'playful' before).

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

from core import mood  # noqa: E402
from core import voice_settings as vs  # noqa: E402


def _with_mood(key: str):
    """Patch config_manager so mood.current() sees `key`."""
    store = {"jarvis_mood": {"mood": key}}
    return mock.patch(
        "memory.config_manager.get_plugin_config",
        lambda ns: dict(store.get(ns) or {}))


class TestMoodsExist(unittest.TestCase):
    def test_comedy_exists(self):
        self.assertIn("comedy", mood.MOODS)
        self.assertIn("girlfriend", mood.MOODS)
        self.assertIn("boss", mood.MOODS)

    def test_normalize_comedy(self):
        self.assertEqual(mood.normalize("Comedy"), "comedy")
        self.assertEqual(mood.normalize("girlfriend"), "girlfriend")
        self.assertEqual(mood.normalize("boss-style"), "boss")


class TestPromptChanges(unittest.TestCase):
    def test_each_mode_changes_the_prompt(self):
        paragraphs = {}
        for key in ("girlfriend", "comedy", "boss", "friendly"):
            with _with_mood(key):
                paragraphs[key] = mood.prompt_paragraph()
        self.assertNotEqual(paragraphs["girlfriend"], paragraphs["comedy"])
        self.assertNotEqual(paragraphs["comedy"], paragraphs["boss"])
        self.assertNotEqual(paragraphs["boss"], paragraphs["friendly"])
        self.assertIn("loving girlfriend", paragraphs["girlfriend"].lower())
        self.assertIn("funny", paragraphs["comedy"].lower())
        self.assertIn("boss", paragraphs["boss"].lower())
        self.assertIn("ji boss", paragraphs["boss"].lower())

    def test_prompt_says_mood_is_tone_not_emotion(self):
        with _with_mood("girlfriend"):
            p = mood.prompt_paragraph()
        self.assertIn("tone setting", p)
        self.assertIn("not real emotion", p)


class TestTone(unittest.TestCase):
    def test_mode_tone_differs(self):
        tones = {}
        for key in ("girlfriend", "comedy", "boss", "friendly"):
            with _with_mood(key):
                tones[key] = mood.mode_tone()
        self.assertNotEqual(tones["girlfriend"], tones["comedy"])
        self.assertNotEqual(tones["comedy"], tones["boss"])
        self.assertEqual(tones["friendly"], (1.0, 1.0))
        # Comedy is faster + brighter; Boss is steadier + lower.
        self.assertGreater(tones["comedy"][0], 1.0)
        self.assertLess(tones["boss"][1], 1.0)

    def test_effective_settings_apply_tone(self):
        store = {"voice_settings": {"rate": 1.0, "pitch": 1.0,
                                    "voice": "", "auto_reply_voice": True}}
        with _with_mood("comedy"):
            eff = vs.effective_settings(store=store)
        self.assertGreater(eff["rate"], 1.0)
        self.assertGreater(eff["pitch"], 1.0)
        with _with_mood("friendly"):
            eff = vs.effective_settings(store=store)
        self.assertEqual(eff["rate"], 1.0)
        self.assertEqual(eff["pitch"], 1.0)


class TestMoodPlugin(unittest.TestCase):
    def test_comedy_confirmation_exists(self):
        from plugins import jarvis_mood as jm
        self.assertIn("comedy", jm._CONFIRM)
        self.assertIn("Comedy", jm.PLUGIN_SETTINGS["fields"][0]["options"])

    def test_set_mood_saves_comedy(self):
        from plugins import jarvis_mood as jm
        store = {}
        with mock.patch("memory.config_manager.get_plugin_config",
                        lambda ns: dict(store.get(ns) or {})), \
                mock.patch("memory.config_manager.save_plugin_config",
                           lambda ns, v: store.__setitem__(ns, dict(v))):
            out = jm.run({"mood": "comedy"})
            self.assertIn("Comedy", out)
            self.assertEqual(store["jarvis_mood"]["mood"], "comedy")


if __name__ == "__main__":
    unittest.main()
