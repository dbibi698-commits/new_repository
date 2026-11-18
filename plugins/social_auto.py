"""plugins/social_auto.py — 💬 SOCIAL AUTO-ENGAGEMENT (Instagram / Facebook).

Voice path for core/social_auto.py. PERMISSION-FIRST: nothing is posted
or commented without the user's permission.
  * Like: per-session approval ("ei reel-ta like koro") or the Auto-Like
    toggle ON for the session.
  * Comment / message: the user approves the EXACT TEXT first
    (action "approve_text"), then action "comment"/"message" sends it.
  * Auto-reply: approved templates only; anything it cannot handle is
    escalated to the user, never guessed.
  * action "status": toggles + limits + recent log (fast, synchronous).
  * action "log": the activity log.

Slow work (browser) runs on a background thread: run() returns in
seconds, progress is reported live in the activity log. Never raises.
Safe limits are hard-coded in the core (30 likes/hour, 150/day, 20-60 s
delays) and the flow stops at once on any platform warning.
"""
from __future__ import annotations

import threading

PLUGIN = {
    "name": "social_auto",
    "description": (
        "Social auto-engagement on Instagram/Facebook: open a profile, "
        "play a reel, like, comment, send a message, auto-reply. "
        "PERMISSION-FIRST: a like needs the user's per-session approval "
        "('ei reel-ta like koro') or Auto-Like ON; a comment/message is "
        "sent ONLY after the user approves the EXACT TEXT (action "
        "'approve_text' first); auto-reply uses only user-approved "
        "templates and escalates what it cannot handle. Actions: 'like', "
        "'comment', 'message', 'reply', 'open', 'approve_text', "
        "'approve_like', 'status', 'log'. Call when the user asks: "
        "reel-ta like koro / comment koro / DM koro / auto-reply dao. "
        "Do NOT use for posting a new post/video — that is "
        "video_upload_browser / instagram_post."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "'like', 'comment', 'message', 'reply', 'open', 'approve_text', 'approve_like', 'status', 'log'."},
            "profile_url": {"type": "STRING",
                            "description": "Profile / reel / post URL (for like/comment/message/open)."},
            "text": {"type": "STRING",
                     "description": "Exact comment/message text (must be approved first for comment/message)."},
            "thread_url": {"type": "STRING",
                           "description": "DM thread URL for an auto-reply."},
            "incoming": {"type": "STRING",
                         "description": "The incoming message to auto-reply to."},
            "toggle": {"type": "STRING",
                       "description": "Toggle name to flip: auto_like, auto_comment, auto_message, auto_reply."},
            "on": {"type": "BOOLEAN",
                   "description": "True = turn the named toggle ON, False = OFF."},
        },
        "required": [],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "social_auto",
    "title": "💬 SOCIAL AUTO — Instagram / Facebook (permission-first)",
    "widget": "social_auto",
    "fields": [],
}


def _log(player, text: str) -> None:
    if player is None:
        return
    try:
        player.write_log(text)
    except Exception:
        pass


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        from core import social_auto as sa
    except Exception as e:
        return f"Social Auto korte parlam na (core load hoy ni): {e}"
    params = parameters or {}
    action = str(params.get("action") or "status").strip().lower()
    profile_url = str(params.get("profile_url") or "").strip()
    text = str(params.get("text") or "").strip()
    thread_url = str(params.get("thread_url") or "").strip()
    incoming = str(params.get("incoming") or "").strip()

    if action == "status":
        try:
            t = sa.toggles()
            lines = ["💬 SOCIAL AUTO — toggles (sob OFF by default):"]
            for name in sa.TOGGLES:
                lines.append(f"  • {name}: {'ON' if t.get(name) else 'OFF'}")
            lines.append(sa.limits_text())
            return "\n".join(lines)
        except Exception as e:
            return f"Status dekhte parlam na: {e}"
    if action == "log":
        try:
            return sa.log_text()
        except Exception as e:
            return f"Log dekhte parlam na: {e}"
    if action == "approve_text":
        try:
            if sa.approve_text(text):
                return f"✅ Text approve korlam: {text[:100]}"
            return "Approve korar moto text dao."
        except Exception as e:
            return f"Approve korte parlam na: {e}"
    if action == "approve_like":
        try:
            sa.approve_like_session()
            return "✅ Ei session-er jonno like approve korlam."
        except Exception as e:
            return f"Approve korte parlam na: {e}"
    if action == "toggle":
        try:
            name = str(params.get("toggle") or "").strip()
            on = bool(params.get("on", False))
            if sa.set_toggle(name, on):
                return f"✅ {name} {'ON' if on else 'OFF'} korlam."
            return f"Toggle-ta chinlam na: {name}"
        except Exception as e:
            return f"Toggle korte parlam na: {e}"

    # Browser actions run on a thread; run() returns at once.
    def _work():
        try:
            if action == "like":
                ok, msg = sa.run_like(profile_url,
                                      log_fn=lambda m: _log(player, m))
            elif action == "comment":
                ok, msg = sa.run_comment(profile_url, text,
                                         log_fn=lambda m: _log(player, m))
            elif action == "message":
                ok, msg = sa.run_message(profile_url, text,
                                         log_fn=lambda m: _log(player, m))
            elif action == "reply":
                ok, msg = sa.run_auto_reply(incoming, thread_url,
                                            log_fn=lambda m: _log(player, m))
            elif action == "open":
                ok, msg = sa.open_profile(profile_url)
            else:
                ok, msg = False, f"Action-ta chinlam na: {action}"
            _log(player, msg)
        except Exception as e:
            _log(player, f"Social Auto-te error: {e}")
    threading.Thread(target=_work, daemon=True,
                     name="social-auto-work").start()
    return f"💬 Social Auto ({action}) shuru korlam — result log-e dekhabe."
