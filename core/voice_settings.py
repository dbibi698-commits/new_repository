"""core/voice_settings.py — 🎙️ VOICE SETTINGS: kotha kemon shonabe.

Speaking rate + pitch + voice choice for the LOCAL TTS fallback, and the
auto-reply voice (phone-e voice reply) on/off. Gemini Live is the MAIN
voice — these settings cover the LOCAL fallback path (system TTS on
Windows/macOS/Linux, Piper, EdgeTTS, Kokoro) and the box says so plainly.

WIRING (real, not a dead setting):
  * SystemTTS (providers/tts_system.py) reads the stored rate/voice/pitch
    in __init__ when its own cfg does not set them (SAPI rate -10..10,
    say/espeak wpm mapping, espeak -p pitch on Linux).
  * PiperTTS (providers/tts_piper.py) reads the stored rate as its speed
    (length_scale = 1/speed) when its own cfg speed is the default.
  * core/tts.py EdgeTTSEngine wraps the text in SSML <prosody> when rate
    or pitch differ from 1.0; KokoroTTSEngine takes speed from the stored
    rate via create_tts_player.
  * main.py _send_link_voice checks auto_reply_voice_on() — OFF means the
    phone gets text replies only, no spoken audio.

Settings live in plugin_config["voice_settings"] through
memory/config_manager.py (never write config/api_keys.json directly).
`store` params exist so tests can inject an in-memory dict. Every public
function returns a plain value and never raises.
"""
from __future__ import annotations

_NAMESPACE = "voice_settings"

_RATE_MIN, _RATE_MAX = 0.5, 2.0
_PITCH_MIN, _PITCH_MAX = 0.5, 2.0

_DEFAULTS = {"rate": 1.0, "pitch": 1.0, "voice": "",
             "auto_reply_voice": True}


# ── validation (pure) ────────────────────────────────────────────────────────

def _clamp_rate(value) -> float:
    try:
        v = float(value)
    except Exception:
        return 1.0
    return max(_RATE_MIN, min(_RATE_MAX, v))


def _clamp_pitch(value) -> float:
    try:
        v = float(value)
    except Exception:
        return 1.0
    return max(_PITCH_MIN, min(_PITCH_MAX, v))


def _clean_voice(value) -> str:
    return str(value or "").strip()[:120]


# ── store access (config_manager by default, dict for tests) ─────────────────

def _read_ns(store=None) -> dict:
    try:
        if isinstance(store, dict):
            raw = store.get(_NAMESPACE) or {}
            return dict(raw) if isinstance(raw, dict) else {}
        from memory.config_manager import get_plugin_config
        return dict(get_plugin_config(_NAMESPACE) or {})
    except Exception:
        return {}


def _write_ns(values: dict, store=None) -> None:
    try:
        if isinstance(store, dict):
            cur = store.get(_NAMESPACE)
            if not isinstance(cur, dict):
                cur = {}
            cur.update(values)
            store[_NAMESPACE] = cur
            return
        from memory.config_manager import save_plugin_config
        save_plugin_config(_NAMESPACE, values)
    except Exception:
        pass


# ── get / set ────────────────────────────────────────────────────────────────

def get_settings(store=None) -> dict:
    """Current voice settings (defaults when nothing is stored)."""
    try:
        raw = _read_ns(store)
        rate = _clamp_rate(raw.get("rate", 1.0))
        pitch = _clamp_pitch(raw.get("pitch", 1.0))
        voice = _clean_voice(raw.get("voice", ""))
        arv = raw.get("auto_reply_voice", True)
        arv = False if arv in (False, 0, "0", "false", "False", "no") else True
        return {"rate": rate, "pitch": pitch, "voice": voice,
                "auto_reply_voice": arv}
    except Exception:
        return dict(_DEFAULTS)


def set_settings(rate=None, pitch=None, voice=None, auto_reply_voice=None,
                 store=None) -> dict:
    """Store the given values (only the ones passed), validated + clamped.
    Returns the full stored settings. Never raises."""
    try:
        cur = get_settings(store)
        if rate is not None:
            cur["rate"] = _clamp_rate(rate)
        if pitch is not None:
            cur["pitch"] = _clamp_pitch(pitch)
        if voice is not None:
            cur["voice"] = _clean_voice(voice)
        if auto_reply_voice is not None:
            cur["auto_reply_voice"] = False if auto_reply_voice in (
                False, 0, "0", "false", "False", "no") else True
        _write_ns(cur, store)
        return dict(cur)
    except Exception:
        return dict(_DEFAULTS)


def effective_settings(store=None) -> dict:
    """Voice settings WITH the current mood's tone applied (rate x
    mode-rate, pitch x mode-pitch, clamped). The local TTS fallback
    speaks in the mood's tone — Girlfriend warmer, Comedy brighter,
    Boss steadier. Never raises."""
    try:
        s = get_settings(store)
        from core import mood as _mood
        mr, mp = _mood.mode_tone()
        return {"rate": _clamp_rate(s["rate"] * mr),
                "pitch": _clamp_pitch(s["pitch"] * mp),
                "voice": s["voice"],
                "auto_reply_voice": s["auto_reply_voice"]}
    except Exception:
        return get_settings(store)


def auto_reply_voice_on(store=None) -> bool:
    """True when the phone should get spoken (voice) replies. Never raises."""
    try:
        return bool(get_settings(store).get("auto_reply_voice", True))
    except Exception:
        return True


# ── engine mappings (pure) ───────────────────────────────────────────────────

def rate_as_sapi(rate: float = 1.0) -> int:
    """Voice-settings rate (0.5–2.0) -> SAPI rate (-10..10). 1.0 -> 0."""
    try:
        r = _clamp_rate(rate)
        return max(-10, min(10, round((r - 1.0) * 10)))
    except Exception:
        return 0


def pitch_as_espeak(pitch: float = 1.0) -> int:
    """Voice-settings pitch (0.5–2.0) -> espeak -p (0..99, default 50)."""
    try:
        p = _clamp_pitch(pitch)
        return max(0, min(99, round(50 + (p - 1.0) * 50)))
    except Exception:
        return 50


def tts_cfg_overrides(store=None) -> dict:
    """{"rate": SAPI int, "voice": str, "speed": float} for provider cfgs.
    Providers merge this UNDER their own explicit cfg values. Uses the
    EFFECTIVE settings (mood tone applied). Never raises."""
    try:
        s = effective_settings(store)
        return {"rate": rate_as_sapi(s["rate"]), "voice": s["voice"],
                "speed": s["rate"], "pitch": s["pitch"]}
    except Exception:
        return {"rate": 0, "voice": "", "speed": 1.0, "pitch": 1.0}


def apply_to_config(config: dict | None) -> dict:
    """Merge the stored voice settings into a TTS config dict (used by
    core/tts.py create_tts_player): tts_speed = rate, tts_voice = voice
    when one is stored. The passed config wins when it already sets a
    non-default value. Never raises, never mutates the input."""
    try:
        cfg = dict(config or {})
        s = get_settings()
        if not cfg.get("tts_speed"):
            cfg["tts_speed"] = s["rate"]
        if not cfg.get("tts_voice"):
            cfg["tts_voice"] = s["voice"]
        return cfg
    except Exception:
        return dict(config or {})


def describe(store=None) -> str:
    """One plain-words summary for the box / card. Never raises."""
    try:
        s = get_settings(store)
        lines = ["🎙️ Voice Settings — local TTS fallback-er jonno "
                 "(Gemini Live-i main voice):"]
        lines.append(f"  • Speed/rate: {s['rate']:.2f}x "
                     f"(SAPI rate {rate_as_sapi(s['rate']):+d})")
        lines.append(f"  • Pitch: {s['pitch']:.2f}x "
                     f"(Linux espeak -p {pitch_as_espeak(s['pitch'])})")
        lines.append(f"  • Voice: {s['voice'] or '(system default)'}")
        lines.append("  • Phone-e voice reply: "
                     + ("ON — kotha shonabe" if s["auto_reply_voice"]
                        else "OFF — sudhu text jabe, voice jabe na"))
        lines.append("  • Rate sob platform-e kaj kore; pitch Linux "
                     "(espeak) + EdgeTTS-e kaj kore.")
        return "\n".join(lines)
    except Exception as e:
        return f"Voice settings dekhte parlam na: {e}"
