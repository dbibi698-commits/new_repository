"""plugins/jarvis_language.py — 🗣️ LANGUAGE: "শুধু বাংলা" (Bengali-only).

set_bengali_only flips Mark's reply language: ON means every reply is in
Bengali only (Bangla script or Roman Banglish), anytime — OFF means Mark
replies the way it always did. The toggle is saved in
plugin_config["language"] and the Live session prompt picks it up from the
next (re)connect (core/language.py). The reply itself tells the model the
new language, so it starts talking Bengali in THIS session too.
"""
from __future__ import annotations

PLUGIN = {
    "name": "set_bengali_only",
    "description": (
        "Turn Bengali-only replies ON or OFF. When ON, Mark replies ONLY in "
        "Bengali (Bangla script or Roman Banglish), anytime — never English "
        "or Hindi. Call when the user says: sudhu Bangla bolo, Bengali-only "
        "on koro, shudhu Bangla-e kotha bolo, English bolbe na, Bangla-only "
        "off koro. The setting is saved and applies from the next reply."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "on": {"type": "BOOLEAN",
                   "description": "True = Bengali only ON, False = OFF."},
        },
        "required": ["on"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "language",
    "title": "🗣️ LANGUAGE — শুধু বাংলা",
    "fields": [
        {"key": "bengali_only", "type": "toggle",
         "label": "শুধু বাংলা — Mark shudhu Bangla-e kotha bolbe, anytime",
         "default": False},
    ],
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Flip the Bengali-only toggle. Never raises."""
    try:
        from core import language as _lang
    except Exception as e:
        return f"Language setting bodlate parlam na: {e}"
    try:
        params = parameters if isinstance(parameters, dict) else {}
        on = params.get("on")
        if on is None:
            # No value given — report the current state instead of guessing.
            return ("Bengali-only ekhon "
                    + ("ON ache — Mark shudhu Bangla-e bolche."
                       if _lang.bengali_only()
                       else "OFF ache — Mark ager motoi bolche."))
        if not _lang.set_bengali_only(bool(on)):
            return "Bengali-only setting save korte parlam na — abar try koro."
        return ("✅ শুধু বাংলা ON — ekhon theke Mark shudhu Bangla-e kotha "
                "bolbe, anytime."
                if on else
                "Bengali-only OFF — Mark ager moto English/Hindi/Bangla "
                "mishiye bolbe.")
    except Exception:
        return "Bengali-only setting bodlate parlam na — kichu ekta gondogol holo."
