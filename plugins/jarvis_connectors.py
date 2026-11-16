"""plugins/jarvis_connectors.py — 🔗 CONNECTORS: token status + settings form.

The settings form writes into plugin_config["connectors"] — the exact
namespace core/connectors.py reads tokens from (_NS = "connectors"). Field
keys match the keys connectors.py reads: github_token, whatsapp_token,
whatsapp_phone_number_id, youtube_api_key, facebook_page_token,
instagram_token, drive_access_token.

Note the two key names that look "wrong" but are correct: connectors.py reads
"youtube_api_key" (not "youtube_key") and "drive_access_token" (not
"drive_token"). A field named youtube_key / drive_token would save fine and
never be read — so this file uses the real keys.
"""
from __future__ import annotations

PLUGIN = {
    "name": "connectors_test",
    "description": (
        "Check which connector tokens are set (GitHub, WhatsApp, YouTube, "
        "Facebook, Instagram, Google Drive) and report each one's status — "
        "set or missing, and where to add it. Call when the user asks: "
        "connectors thik ache kina, token gulo ache kina, ki ki connect kora. "
        "This only checks whether a token is SAVED, not whether it still works."
    ),
    "parameters": {"type": "OBJECT", "properties": {}, "required": []},
}

PLUGIN_SETTINGS = {
    "namespace": "connectors",
    "title": "🔗 CONNECTORS — API Tokens",
    "fields": [
        {"key": "github_token", "type": "password",
         "label": "GitHub token (fine-grained PAT)",
         "placeholder": "ghp_... / github_pat_..."},
        {"key": "whatsapp_token", "type": "password",
         "label": "WhatsApp Business token (Meta app)",
         "placeholder": "EAAG..."},
        {"key": "whatsapp_phone_number_id", "type": "text",
         "label": "WhatsApp phone number id",
         "placeholder": "e.g. 123456789012345"},
        {"key": "youtube_api_key", "type": "password",
         "label": "YouTube Data API key",
         "placeholder": "AIza..."},
        {"key": "facebook_page_token", "type": "password",
         "label": "Facebook Page token",
         "placeholder": "EAAG..."},
        {"key": "instagram_token", "type": "password",
         "label": "Instagram token (Page token)",
         "placeholder": "EAAG..."},
        {"key": "drive_access_token", "type": "password",
         "label": "Google Drive OAuth access token (~1h)",
         "placeholder": "ya29..."},
        {"key": "render_api_key", "type": "password",
         "label": "Render API key (dashboard deploy-er jonno)",
         "placeholder": "rnd_..."},
    ],
}

_CHECKS = [
    ("github_token", "GitHub"),
    ("whatsapp_token", "WhatsApp"),
    ("youtube_api_key", "YouTube"),
    ("facebook_page_token", "Facebook"),
    ("instagram_token", "Instagram"),
    ("drive_access_token", "Google Drive"),
    ("render_api_key", "Render"),
]


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        from core import connectors as _conn
    except Exception as e:
        return f"Connectors check korte parlam na: {e}"
    lines = []
    missing = []
    for key, label in _CHECKS:
        try:
            ok = bool(_conn.get_token(key))
        except Exception:
            ok = False
        lines.append(("✅ " if ok else "❌ ") + label + (" — set" if ok else " — not set"))
        if not ok:
            missing.append(label)
    out = "Connectors:\n" + "\n".join(lines)
    if missing:
        out += ("\nToken gulo Plugin Settings > 🔗 CONNECTORS-e bosao "
                "(password field — kokhono chat-e pathiyo na).")
    return out
