"""plugins/voice_settings.py — 🎙️ VOICE SETTINGS: kotha kemon shonabe.

Speaking rate + pitch + voice choice for the LOCAL TTS fallback, and
the auto-reply voice (phone-e voice reply) on/off. Gemini Live is the
MAIN voice — these settings cover the local fallback path (system TTS,
Piper, EdgeTTS, Kokoro) and the box says so plainly. The Plugin Settings
overlay builds the "Voice Settings" box for this plugin (widget
"voice_settings").

Runs on a worker thread. Returns a short string, never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "voice_settings",
    "description": (
        "Set how Mark's local fallback voice sounds — speaking rate "
        "(0.5–2.0x), pitch (0.5–2.0x), voice name, and whether the phone "
        "gets spoken (voice) replies or text only. Gemini Live is the main "
        "voice; these settings cover the local TTS fallback (system TTS, "
        "Piper, EdgeTTS, Kokoro). Call when the user asks: voice slow/fast "
        "koro, pitch bodlao, voice bodlao, phone-e voice reply bondho koro."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "rate": {"type": "NUMBER",
                     "description": "Speaking rate 0.5 (slow) to 2.0 (fast)."},
            "pitch": {"type": "NUMBER",
                      "description": "Pitch 0.5 (low) to 2.0 (high)."},
            "voice": {"type": "STRING",
                      "description": "Voice name (system voice list theke), "
                                     "khali = system default."},
            "auto_reply_voice": {"type": "BOOLEAN",
                                 "description": "False = phone-e sudhu text "
                                                "reply jabe, voice jabe na."},
        },
        "required": [],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "voice_settings",
    "title": "🎙️ VOICE SETTINGS — kotha kemon shonabe",
    "widget": "voice_settings",
    "fields": [],
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Get or set voice settings. Returns a short string, never raises."""
    try:
        params = parameters or {}
        from core import voice_settings as _vs
        if not any(k in params for k in
                   ("rate", "pitch", "voice", "auto_reply_voice")):
            return _vs.describe()
        rate = params.get("rate")
        pitch = params.get("pitch")
        voice = params.get("voice")
        arv = params.get("auto_reply_voice")
        try:
            rate = float(rate) if rate is not None else None
        except Exception:
            rate = None
        try:
            pitch = float(pitch) if pitch is not None else None
        except Exception:
            pitch = None
        if arv is not None:
            arv = arv not in (False, 0, "0", "false", "False", "no")
        saved = _vs.set_settings(rate=rate, pitch=pitch,
                                 voice=(str(voice) if voice is not None
                                        else None),
                                 auto_reply_voice=arv)
        return ("🎙️ Voice Settings save holo:\n" + _vs.describe())
    except Exception as e:
        return f"Voice Settings korte parlam na: {e}"
