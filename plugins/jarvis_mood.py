"""plugins/jarvis_mood.py — 🎭 MOOD & FEELINGS: Mark talks in a mood.

set_mood switches Mark's tone (friendly/playful/caring/serious/boss/
girlfriend) and
saves it in plugin_config["jarvis_mood"], so it survives restarts and the
next Live session picks it up in its prompt. The reply itself tells the
model the new mood, so it starts talking that way in THIS session too.

A mood is a tone/personality setting — not real emotion. Mark does not
feel anything; it phrases its replies in the mood the boss picked.
"""
from __future__ import annotations

PLUGIN = {
    "name": "set_mood",
    "description": (
        "Change Mark's mood — how it talks: friendly, playful, caring, "
        "serious, boss-style (short, direct, like the boss), girlfriend "
        "(warm, affectionate, a little playful), or comedy (funny, "
        "a joke in every reply). Call when "
        "the user says: mood change koro, friendly hoye kotha bolo, serious "
        "hoye jao, boss-er moto kotha bolo, girlfriend-er moto kotha bolo, "
        "ektu moja kore bolo. The mood "
        "is saved and applies from now on."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "mood": {"type": "STRING",
                     "description": "friendly | playful | caring | serious | boss | girlfriend | comedy."},
        },
        "required": ["mood"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "jarvis_mood",
    "title": "🎭 MOOD & FEELINGS",
    "fields": [
        {"key": "mood", "type": "choice",
         "label": "Mood",
         "options": ["Friendly", "Playful", "Caring", "Serious", "Boss-style", "Girlfriend", "Comedy"],
         "default": "Friendly"},
        {"key": "mirror_boss_style", "type": "toggle",
         "label": "Talk the way the boss talks (short Banglish bursts, warm, direct)",
         "default": True},
        {"key": "think_aloud", "type": "toggle",
         "label": "Think aloud — briefly say what I am thinking before I act",
         "default": False},
    ],
    # Extra box the Plugin Settings overlay builds at the end of this
    # section: Girlfriend / Comedy / Boss quick-switch buttons + the
    # current mode. The overlay only knows the widget key; the box
    # itself lives in gui/overlays.py.
    "widget": "modes",
}

# Confirmation in each mood's own voice — spoken back to the user.
_CONFIRM = {
    "friendly": "😊 Friendly mood-e gelam — aram kore, valo kore kotha bolbo.",
    "playful": "😄 Playful mood on — ekhon theke halka moja kore kotha bolbo!",
    "caring": "💛 Caring mood-e achi — aste, jotno kore shunbo ar bolbo.",
    "serious": "🧐 Serious mood — ekhon theke kajer kotha, soja ar thikthak.",
    "boss": "👑 Boss-style on — short, direct, soja kotha.",
    "girlfriend": "💕 Girlfriend mood on — ekhon theke misti kore, jotno kore kotha bolbo!",
    "comedy": "😂 Comedy mood on — ekhon theke prottek uttor-e ekta moja thakbe!",
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    raw = (parameters.get("mood") or "").strip()
    try:
        from core import mood as _mood
        from memory.config_manager import save_plugin_config, get_plugin_config
    except Exception as e:
        return f"Mood change korte parlam na: {e}"
    key = _mood.normalize(raw)
    if not raw:
        m = _mood.current()
        return (f"Ekhon mood {m['emoji']} {m['name']} — change korte chaile bolo: "
                "friendly, playful, caring, serious, boss, girlfriend, na comedy.")
    try:
        cfg = dict(get_plugin_config("jarvis_mood") or {})
        cfg["mood"] = key
        save_plugin_config("jarvis_mood", cfg)
    except Exception as e:
        return f"Mood save korte parlam na: {e}"
    _, name, desc = _mood.MOODS[key]
    # The tail is an instruction the model reads in this same session, so the
    # new mood starts at once; the saved config makes the next session use it.
    return (_CONFIRM[key] +
            f" From now on, talk in a {name} mood: {desc}")
