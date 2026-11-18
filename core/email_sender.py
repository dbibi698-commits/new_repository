"""core/email_sender.py — ✉️ EMAIL SENDER: SMTP diye asol email pathano.

Sends a real email through the user's OWN SMTP settings — stored in
plugin_config["email_sender"] (smtp_host, smtp_port, smtp_user,
smtp_pass, smtp_from, use_tls), set from Settings, never hardcoded and
never in chat. When the settings are missing the reply says plainly what
to set instead of pretending the mail went out. smtplib only (stdlib),
no Qt, no other network. Every public function returns a plain value and
never raises.
"""
from __future__ import annotations

import re
import smtplib
from email.message import EmailMessage

_NAMESPACE = "email_sender"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


def get_settings(store=None) -> dict:
    """Stored SMTP settings (password is masked in the returned dict)."""
    try:
        raw = _read_ns(store)
        return {
            "smtp_host": str(raw.get("smtp_host") or "").strip(),
            "smtp_port": int(raw.get("smtp_port") or 587),
            "smtp_user": str(raw.get("smtp_user") or "").strip(),
            "smtp_pass": str(raw.get("smtp_pass") or ""),
            "smtp_from": str(raw.get("smtp_from") or "").strip(),
            "use_tls": raw.get("use_tls", True) not in (
                False, 0, "0", "false", "False", "no"),
        }
    except Exception:
        return {"smtp_host": "", "smtp_port": 587, "smtp_user": "",
                "smtp_pass": "", "smtp_from": "", "use_tls": True}


def set_settings(host: str = "", port: int = 587, user: str = "",
                 password: str = "", from_addr: str = "",
                 use_tls: bool = True, store=None) -> dict:
    """Store SMTP settings. Returns the masked settings dict."""
    try:
        vals: dict = {}
        if host is not None:
            vals["smtp_host"] = str(host or "").strip()
        if port is not None:
            vals["smtp_port"] = int(port or 587)
        if user is not None:
            vals["smtp_user"] = str(user or "").strip()
        if password:
            vals["smtp_pass"] = str(password)
        if from_addr is not None:
            vals["smtp_from"] = str(from_addr or "").strip()
        if use_tls is not None:
            vals["use_tls"] = bool(use_tls)
        _write_ns(vals, store)
        return get_settings(store)
    except Exception:
        return get_settings(store)


def configured(store=None) -> tuple[bool, str]:
    """(ready, missing-text). Never raises."""
    try:
        s = get_settings(store)
        missing = []
        if not s["smtp_host"]:
            missing.append("smtp_host (e.g. smtp.gmail.com)")
        if not s["smtp_user"]:
            missing.append("smtp_user (tomar email)")
        if not s["smtp_pass"]:
            missing.append("smtp_pass (app password)")
        if missing:
            return False, ", ".join(missing)
        return True, ""
    except Exception:
        return False, "settings porte parlam na"


def send_email(to: str, subject: str = "", body: str = "",
               settings: dict | None = None, store=None,
               smtp_class=None) -> tuple[bool, str]:
    """Send one email. Returns (ok, message). `smtp_class` is injectable
    for tests (defaults to smtplib.SMTP). Never raises."""
    try:
        to = (to or "").strip()
        if not _EMAIL_RE.match(to):
            return False, "Kar kache pathabo — thik email address dao."
        cfg = settings if isinstance(settings, dict) else get_settings(store)
        host = str(cfg.get("smtp_host") or "").strip()
        user = str(cfg.get("smtp_user") or "").strip()
        pw = str(cfg.get("smtp_pass") or "")
        if not host or not user or not pw:
            ok, missing = configured(store)
            return False, ("Email pathate parlam na — SMTP set kora nei. "
                           f"Settings-e bosao: {missing}. "
                           "Gmail hole app password lagbe (2-step on kore).")
        port = int(cfg.get("smtp_port") or 587)
        from_addr = str(cfg.get("smtp_from") or user).strip() or user
        use_tls = cfg.get("use_tls", True) not in (
            False, 0, "0", "false", "False", "no")
        msg = EmailMessage()
        msg["From"] = from_addr
        msg["To"] = to
        msg["Subject"] = (subject or "").strip() or "(kono subject nei)"
        msg.set_content((body or "").strip() or "(khali message)")
        cls = smtp_class or smtplib.SMTP
        server = cls(host, port, timeout=30)
        try:
            if use_tls:
                server.starttls()
            server.login(user, pw)
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except Exception:
                pass
        return True, f"✅ Email pathalam — {to} ({subject or '(no subject)'})"
    except Exception as e:
        return False, f"Email pathate parlam na: {e}"


def describe(store=None) -> str:
    """Readiness text for the card. Never raises."""
    try:
        ok, missing = configured(store)
        if ok:
            s = get_settings(store)
            return (f"✉️ Email Sender ready — {s['smtp_host']}:{s['smtp_port']} "
                    f"({s['smtp_user']}). Kar kache + ki likhbo bolo.")
        return (f"✉️ Email Sender — SMTP set kora nei: {missing}. "
                "Plugin Settings > Email Sender-e bosao (Gmail hole app "
                "password lagbe).")
    except Exception as e:
        return f"Email Sender-er status dekhte parlam na: {e}"
