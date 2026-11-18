"""plugins/utility_create.py — 🎨 CREATE tools: QR Generator, Password
Generator, Meme Maker, Subtitle Maker, Invoice Maker, Resume Builder.
Thin voice wrapper over core/utility_tools.py. Never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "utility_create",
    "description": (
        "Create tools — QR generator (text/URL -> PNG), password generator "
        "(strong random), meme maker (image + top/bottom text), subtitle "
        "maker (text -> .srt), invoice maker (Excel .xlsx), resume builder "
        "(DOCX). Call when the user says: QR banao, password banao, meme "
        "banao, subtitle banao, invoice banao, resume banao."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "qr | password | meme | subtitle | invoice | resume"},
            "text": {"type": "STRING", "description": "Text/URL (QR, subtitle text)."},
            "name": {"type": "STRING", "description": "File name (QR) / client or person name (invoice/resume)."},
            "length": {"type": "NUMBER", "description": "Password length (default 16)."},
            "image": {"type": "STRING", "description": "Image path (meme)."},
            "top": {"type": "STRING", "description": "Meme top text."},
            "bottom": {"type": "STRING", "description": "Meme bottom text."},
            "amount": {"type": "NUMBER", "description": "Invoice amount."},
            "items": {"type": "STRING", "description": "Invoice items (one per line)."},
            "role": {"type": "STRING", "description": "Resume role/title."},
            "skills": {"type": "STRING", "description": "Resume skills (comma-separated)."},
            "video": {"type": "STRING", "description": "Video path for the subtitle file."},
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        p = parameters or {}
        action = str(p.get("action") or "").strip().lower()
        from core import utility_tools as u
        if action == "qr":
            return u.qr_generate(str(p.get("text") or ""),
                                 str(p.get("name") or ""))
        if action == "password":
            return u.password_generate(int(p.get("length") or 16))
        if action == "meme":
            return u.meme_make(str(p.get("image") or ""),
                               str(p.get("top") or ""),
                               str(p.get("bottom") or ""))
        if action == "subtitle":
            return u.subtitle_make(str(p.get("video") or ""),
                                   str(p.get("text") or ""))
        if action == "invoice":
            return u.invoice_make(str(p.get("name") or ""),
                                  float(p.get("amount") or 0),
                                  str(p.get("items") or ""))
        if action == "resume":
            return u.resume_build(str(p.get("name") or ""),
                                  str(p.get("role") or ""),
                                  str(p.get("skills") or ""))
        return ("Ki banabo — qr, password, meme, subtitle, invoice, "
                "resume-er ekta bolo.")
    except Exception as e:
        return f"Create tool chalate parlam na: {e}"
