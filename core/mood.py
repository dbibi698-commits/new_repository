"""core/mood.py — 🎭 MOOD & FEELINGS: tone/personality setting for Mark.

A mood is a TONE setting — how Mark phrases its replies — not real
emotion. Mark does not feel anything; it thinks briefly before it acts and
talks in the mood the boss picked, in the boss's own style when
mirror_boss_style is on.

Single source of truth for the mood: the plugin (set_mood), the prompt
(main.py _build_config) and the HUD badge (gui/window.py) all read from
here, which reads plugin_config["jarvis_mood"] via config_manager.
"""
from __future__ import annotations

MOODS = {
    "friendly": ("😊", "Friendly",
                 "warm, kind, easy — like a good friend who helps."),
    "playful": ("😄", "Playful",
                "light, witty, fun — a joke when it fits, never mean."),
    "caring": ("💛", "Caring",
               "gentle, patient, looking out for the boss."),
    "serious": ("🧐", "Serious",
                "calm, focused, precise — no jokes, just the work."),
    "boss": ("👑", "Boss-style",
             "short, direct, confident — the boss's own way of talking."),
}
_DEFAULT = "friendly"


def normalize(raw) -> str:
    """'Playful' / 'playful' / 'Boss-style' / 'boss' -> a MOODS key."""
    t = str(raw or "").strip().lower().replace("_", "-").replace(" ", "-")
    if t in MOODS:
        return t
    if t.startswith("boss"):
        return "boss"
    return _DEFAULT


def current() -> dict:
    """{key, emoji, name, desc, mirror_boss_style, think_aloud} from config."""
    try:
        from memory.config_manager import get_plugin_config
        cfg = get_plugin_config("jarvis_mood") or {}
    except Exception:
        cfg = {}
    key = normalize(cfg.get("mood", _DEFAULT))
    emoji, name, desc = MOODS[key]
    return {
        "key": key,
        "emoji": emoji,
        "name": name,
        "desc": desc,
        "mirror_boss_style": cfg.get("mirror_boss_style", True) is not False,
        "think_aloud": bool(cfg.get("think_aloud", False)),
    }


def prompt_paragraph() -> str:
    """[MOOD] paragraph for the Live session prompt — read fresh at every
    session build, so a mood change applies from the next (re)connect."""
    m = current()
    lines = [
        "[MOOD]",
        f"Your mood right now is {m['name']} {m['emoji']} — {m['desc']}",
        "Think briefly before you answer — short, thoughtful, not rushed.",
    ]
    if m["mirror_boss_style"]:
        lines.append(
            "Mirror the boss's own style: short Banglish/Hindi-mix bursts, "
            "warm and direct — the way he talks to you.")
    if m["think_aloud"]:
        lines.append(
            "Think aloud: before you act, briefly say what you are thinking "
            "(one short line), then do it.")
    lines.append(
        "A mood is a tone setting, not real emotion — you do not feel, "
        "you phrase.")
    return "\n".join(lines) + "\n"
