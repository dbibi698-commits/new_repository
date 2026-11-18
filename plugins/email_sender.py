"""plugins/email_sender.py — ✉️ EMAIL SENDER: SMTP diye asol email pathano.

Sends a real email through the user's OWN SMTP settings (stored in
plugin_config["email_sender"] — host, port, user, app password, from).
When the settings are missing the reply says plainly what to set in
Settings instead of pretending the mail went out. Runs on a worker
thread. Returns a short string, never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "email_sender",
    "description": (
        "Send a real email through your own SMTP settings (Gmail app "
        "password works). Call when the user asks: email pathao, mail koro. "
        "SMTP set kora na thakle bolbe ki bosate hobe — Settings-e "
        "smtp_host / smtp_user / smtp_pass bosao."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "to": {"type": "STRING",
                   "description": "Recipient email address."},
            "subject": {"type": "STRING",
                        "description": "Email subject."},
            "body": {"type": "STRING",
                     "description": "Email body."},
            "smtp_host": {"type": "STRING",
                          "description": "SMTP host (e.g. smtp.gmail.com) — "
                                         "save korte."},
            "smtp_user": {"type": "STRING",
                          "description": "SMTP user (tomar email) — save korte."},
            "smtp_pass": {"type": "STRING",
                          "description": "SMTP app password — save korte."},
        },
        "required": [],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Send an email, or save SMTP settings. Short string, never raises."""
    try:
        params = parameters or {}
        from core import email_sender as _em
        host = str(params.get("smtp_host") or "").strip()
        user = str(params.get("smtp_user") or "").strip()
        pw = str(params.get("smtp_pass") or "")
        if host or user or pw:
            saved = _em.set_settings(host=host or None,
                                     user=user or None,
                                     password=pw or None)
            return ("✉️ SMTP settings save holo — "
                    f"{saved.get('smtp_host') or '(host khali)'} "
                    f"({saved.get('smtp_user') or '(user khali)'}). "
                    "Ebar email pathate bolo: kar kache + ki likhbo.")
        to = str(params.get("to") or "").strip()
        if not to:
            return _em.describe()
        ok, msg = _em.send_email(
            to, subject=str(params.get("subject") or ""),
            body=str(params.get("body") or ""))
        return msg
    except Exception as e:
        return f"Email pathate parlam na: {e}"
