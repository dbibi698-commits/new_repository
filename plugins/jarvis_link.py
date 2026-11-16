"""plugins/jarvis_link.py — 📱 JARVIS LINK: AI-to-AI talk, phone <-> PC.

Mark (this PC) sends a message to the phone Jarvis over the backend relay
(kind=text, the same path as phone_command) and WAITS for the phone's reply,
so the two AIs can talk to each other: the user tells one AI to pass a
message to the other, and the reply comes back here and is spoken aloud.

The reverse direction (phone -> PC) already works without this plugin: relay
text arrives in the inbox and main.py's _link_ask feeds it to the Live
session, and the answer goes back to the phone automatically.
"""
from __future__ import annotations

PLUGIN = {
    "name": "phone_say",
    "description": (
        "Send a spoken message TO the phone Jarvis and bring back its reply — "
        "the two AIs talking to each other. Call when the user says: phone "
        "Jarvis-ke bolo ..., mobile Jarvis-ke ei kothata pathao, phone-er "
        "Jarvis-ke jiggesh koro ..., tell the phone Jarvis .... The phone's "
        "reply is returned so it can be spoken aloud here. Needs the phone "
        "paired over Jarvis Link."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "message": {"type": "STRING", "description": "The message for the phone Jarvis, in the user's words."},
        },
        "required": ["message"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "jarvis_link",
    "title": "📱 JARVIS LINK — Phone ↔ PC",
    "fields": [
        {"key": "speak_phone_replies", "type": "toggle",
         "label": "Speak phone replies aloud", "default": True},
        {"key": "auto_reconnect", "type": "toggle",
         "label": "Auto-reconnect reminder when unpaired", "default": True},
        {"key": "render_url", "type": "text",
         "label": "Render Direct Connect URL (dashboard host)",
         "placeholder": "https://mark-lvii-dashboard.onrender.com"},
        {"key": "browser_token", "type": "password",
         "label": "Browser extension token — Chrome extension popup-e bosao (dashboard start-e auto-toiri hoy)",
         "placeholder": "dashboard start hole toiri hobe"},
    ],
}


def _settings() -> dict:
    try:
        from memory.config_manager import get_plugin_config
        return get_plugin_config("jarvis_link")
    except Exception:
        return {}


def run(parameters: dict, player=None, session_memory=None) -> str:
    message = (parameters.get("message") or "").strip()
    if not message:
        return "Phone Jarvis-ke ki bolbo — kothata dao."
    try:
        from core.jarvis_link import LINK
    except Exception:
        return "Jarvis Link chalu hoy ni — restart koro."
    cfg = _settings()
    if LINK is None or not LINK.paired:
        base = ("Phone pair kora nei — phone-e Jarvis khule Settings > PC Pairing > "
                "Scan PC QR diye Mark-er QR scan koro, tarpor abar bolo.")
        if cfg.get("auto_reconnect", True):
            base += " QR dekhte amake bolo 'QR dekhao'."
        return base
    try:
        reply = LINK.send_and_wait_result(message, timeout=90.0)
    except Exception as e:
        return f"Phone-e pathate parlam na: {e}"
    if not reply:
        return ("Phone-e pathalam, kintu 90 second-e kono uttor elo na — "
                "phone-er Jarvis khola ache kina dekho.")
    if cfg.get("speak_phone_replies", True) is False:
        if player:
            try:
                player.write_log(f"📱 Phone bollo: {reply}")
            except Exception:
                pass
        return "Phone uttor diyeche — activity log-e dekhte paro."
    return reply[:500]
