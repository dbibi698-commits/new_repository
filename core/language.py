"""core/language.py — 🗣️ LANGUAGE: "শুধু বাংলা" (Bengali-only) option.

A language setting — which language Mark replies in — not a mood. When the
toggle is ON, Mark replies ONLY in Bengali, anytime: Bangla script or Roman
Banglish, the way the boss talks. The toggle lives in plugin_config
["language"] through memory/config_manager.py (never write
config/api_keys.json directly), and the prompt paragraph is read fresh at
every session build (main.py _build_config), so flipping it in Plugin
Settings applies from the next (re)connect — no app restart needed.

Honest limit: this forces the REPLY language. The TTS voice itself stays
the one picked in Settings (a voice is a voice, not a language), and
Gemini Live may still greet in another language on the very first turn
before the instruction lands — if it does, the next reply is Bengali.
"""
from __future__ import annotations

_NS = "language"


def bengali_only() -> bool:
    """True when the boss wants Bengali-only replies. Never raises."""
    try:
        from memory.config_manager import get_plugin_config
        cfg = get_plugin_config(_NS) or {}
    except Exception:
        return False
    return cfg.get("bengali_only", False) is True


def set_bengali_only(on: bool) -> bool:
    """Persist the toggle. Returns False on a write error. Never raises."""
    try:
        from memory.config_manager import save_plugin_config
        save_plugin_config(_NS, {"bengali_only": bool(on)})
        return True
    except Exception:
        return False


def prompt_paragraph() -> str:
    """[LANGUAGE] paragraph for the Live session prompt — empty when the
    toggle is OFF, so an English/Hindi user is never affected."""
    if not bengali_only():
        return ""
    return (
        "[LANGUAGE — শুধু বাংলা]\n"
        "The boss turned ON Bengali-only: reply ONLY in Bengali, anytime, "
        "every single reply — Bangla script or Roman Banglish, the way the "
        "boss talks to you. Never reply in English or Hindi while this is "
        "on, not even for one sentence, not even for error messages or "
        "confirmations. Tool names, file paths and URLs stay as-is; "
        "everything else is Bengali.\n"
    )
