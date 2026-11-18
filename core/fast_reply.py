"""core/fast_reply.py — ⚡ INSTANT LOCAL ANSWERS (no Gemini round-trip).

WHY THIS EXISTS
    The user reported Mark "thinking" forever without replying. A full
    Gemini Live reply needs network + the model, so it can never literally
    be milliseconds — but a large share of what people ask every day does
    not need the model at all: the time, a sum, Mark's own status, a mode
    switch. Those used to travel to the Live session and back, so a slow
    network or a stalled session turned "time koto?" into a long silence.

    This module answers those locally, in microseconds, with no network
    and no model. main.py's text-command path calls answer_locally()
    BEFORE sending anything to the Live session; when it returns a string
    the user gets that answer at once and the model is never bothered.
    Voice turns cannot be intercepted this way — the audio streams to
    Live directly — so voice gets the other half of the fix instead:
    a shorter stall limit, an instant on-screen ack, streaming
    transcription and a spoken local fallback when the session stalls
    (see main.py _watch_stall / _speak_local).

    Everything here is pure and never raises. Nothing here imports Qt,
    the network, or the model.
"""
from __future__ import annotations

import ast
import re
import time
from datetime import datetime

# ── instant ack + stall lines ────────────────────────────────────────────────

_ACK_LINES = (
    "💭 Shunechi — bhabchi...",
    "💭 Hmm, ek sec — dekhchi...",
    "💭 Bujhechi — uttor dicchi...",
)

_STALL_LINES = (
    "Net slow lagche — abar connect korchi, ektu darao...",
    "Model-ta uttor dicche na — session-ta notun kore khulchi...",
    "Ektu deri hocche — abar try korchi, chinta koro na...",
)


def ack_line() -> str:
    """One short 'heard you' line, rotating by the second."""
    return _ACK_LINES[int(time.time()) % len(_ACK_LINES)]


def stall_line() -> str:
    """One short 'the model stalled, reconnecting' line."""
    return _STALL_LINES[int(time.time()) % len(_STALL_LINES)]


# ── calculator (safe: ast only, no eval) ─────────────────────────────────────

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
                   ast.Pow, ast.FloorDiv)
_ALLOWED_UNARY = (ast.USub, ast.UAdd)


def calc(expr: str):
    """Evaluate a plain arithmetic expression. Returns (ok, value|error)."""
    try:
        s = str(expr or "").strip()
        if not s:
            return False, "khali"
        if len(s) > 120:
            return False, "eto boro hisab ekbare korte parbo na"
        tree = ast.parse(s, mode="eval")
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp):
                if not isinstance(node.op, _ALLOWED_BINOPS):
                    return False, "ei operator-ta cholbe na"
            elif isinstance(node, ast.UnaryOp):
                if not isinstance(node.op, _ALLOWED_UNARY):
                    return False, "ei operator-ta cholbe na"
            elif isinstance(node, ast.Constant):
                if not isinstance(node.value, (int, float)):
                    return False, "shudhu number cholbe"
            elif isinstance(node, (ast.Expression, ast.operator,
                                   ast.unaryop)):
                # ast.walk also visits the operator nodes themselves
                # (Add/Mult/...) — the BinOp/UnaryOp checks above already
                # validated them, so skip them here.
                continue
            else:
                return False, "shudhu + - * / % ** // ar bracket cholbe"
        val = eval(compile(tree, "<calc>", "eval"), {"__builtins__": {}}, {})
        if isinstance(val, float) and val == int(val):
            val = int(val)
        return True, val
    except ZeroDivisionError:
        return False, "0 diye bhag kora jay na"
    except Exception:
        return False, "hisab-ta bujhlam na"


_CALC_RE = re.compile(
    r"(?i)^\s*(?:hisab|calculate|calc|koto|jog|biyog)?\s*"
    r"([-+0-9][0-9\s+\-*/%().^]*?)\s*\??\s*$")


def try_calc(text: str):
    """Pull an arithmetic expression out of a short command, or None."""
    try:
        t = str(text or "").strip()
        if not t or len(t) > 140:
            return None
        # Must look like maths: digits + operators, nothing else.
        if not re.fullmatch(r"[0-9\s+\-*/%().^a-zA-Z\u0980-\u09FF?]+", t):
            return None
        # Trailing "koto?" ("how much?") is how Bengali asks — drop it.
        t = re.sub(r"(?i)\s*koto\s*\??\s*$", "", t)
        m = _CALC_RE.match(t)
        if not m:
            return None
        expr = m.group(1).strip().replace("^", "**")
        if not re.search(r"\d", expr) or not re.search(r"[+\-*/%]", expr):
            return None
        if re.search(r"[a-zA-Z\u0980-\u09FF]", expr):
            return None
        return expr
    except Exception:
        return None


# ── time / date / status ─────────────────────────────────────────────────────

def time_text() -> str:
    now = datetime.now()
    return ("🕐 Ekhon " + now.strftime("%I:%M %p").lstrip("0")
            + f" — {now.strftime('%A, %d %B %Y')}.")


def date_text() -> str:
    now = datetime.now()
    return f"📅 Aaj {now.strftime('%A, %d %B %Y')}."


def status_text() -> str:
    """Mark's own status, locally, without the model."""
    try:
        from core import mark_status as _ms
        snap = _ms.snapshot()
        lines = ["⚡ Mark — live status (local):"]
        lines.append(f"  • Task: {snap.get('current_task') or 'Idle'}")
        last = str(snap.get("last_response") or "").strip()
        if last:
            lines.append(f"  • Shesh uttor: {last[:100]}")
        lines.append(f"  • Queue: {snap.get('queue_len', 0)} ta")
    except Exception:
        lines = ["⚡ Mark cholche."]
    try:
        from core import mood as _mood
        m = _mood.current()
        lines.append(f"  • Mode: {m.get('emoji', '')} {m.get('name', '')}")
    except Exception:
        pass
    try:
        from core import watchdog24 as _wd
        lines.append(f"  • Uptime: {_wd.uptime_text()}")
    except Exception:
        pass
    try:
        from core import jarvis_link as _jl
        link = _jl.LINK
        if link is not None and getattr(link, "paired", False):
            lines.append("  • 📱 Phone pair kora ache")
        else:
            lines.append("  • 📱 Phone pair kora nei")
    except Exception:
        pass
    return "\n".join(lines)


# ── the router ───────────────────────────────────────────────────────────────

_TIME_RE = re.compile(
    r"(?i)\b(time|koyta|kotota|somoy|ekhon)\b.*\b(koto|ki|kotota)?\b")
_DATE_RE = re.compile(r"(?i)\b(aaj|today|date|tarikh|ki bar|kobe)\b")
_GREET_RE = re.compile(
    r"(?i)^\s*(hi+|hello+|hey+|salam+|assalamu alaikum|nomoskar+|good\s*(morning|afternoon|evening|night)|shuprobhat+|valo\s*acho+|kemon\s*acho+)\s*[!.?]?\s*$")
_MODE_RE = re.compile(
    r"(?i)\b(girlfriend|comedy|boss)\s*(mode|mood)?\s*(on|chalu|koro|hoy|hao|switch)?\b")
_BENGALI_RE = re.compile(
    r"(?i)\b(bengali[-\s]?only|shudhu\s*bangla|bangla\s*only)\b\s*(on|off|chalu|bondho)?\b")


def answer_locally(text: str) -> str | None:
    """Answer a typed command locally, or None when it needs the model.

    Covers: time/date, arithmetic, Mark's own status, greetings, mode
    switches (girlfriend/comedy/boss), Bengali-only toggle. Everything
    else returns None so the Live session handles it as before.
    Never raises."""
    try:
        t = str(text or "").strip()
        if not t:
            return None
        low = t.lower()

        # Mode switches — persistent, applied at once.
        m = _MODE_RE.search(t)
        if m and ("mode" in low or "mood" in low or "on" in low
                  or "chalu" in low or "koro" in low or "hoy" in low
                  or "hao" in low or low.strip() in ("girlfriend", "comedy", "boss")):
            try:
                from core import mood as _mood
                key = _mood.normalize(m.group(1))
                from memory.config_manager import (
                    get_plugin_config, save_plugin_config)
                cfg = dict(get_plugin_config("jarvis_mood") or {})
                cfg["mood"] = key
                save_plugin_config("jarvis_mood", cfg)
                cur = _mood.current()
                from plugins import jarvis_mood as _jm
                conf = _jm._CONFIRM.get(key, "")
                return conf or (f"{cur.get('emoji', '')} {cur.get('name', '')} "
                                f"mode on holo.")
            except Exception:
                return None

        # Bengali-only toggle.
        m = _BENGALI_RE.search(t)
        if m:
            try:
                from core import language as _lang
                word = (m.group(2) or "").lower()
                if word in ("off", "bondho"):
                    _lang.set_bengali_only(False)
                    return "🇧🇩 Bengali-only OFF — ekhon jemon bolbe temon uttor dibo."
                _lang.set_bengali_only(True)
                return "🇧🇩 Bengali-only ON — ekhon theke shudhu Bangla-tei kotha bolbo."
            except Exception:
                return None

        # Time / date.
        if _TIME_RE.search(t) and len(t) <= 60:
            return time_text()
        if _DATE_RE.search(t) and len(t) <= 60:
            return date_text()

        # Status / uptime.
        if re.search(r"(?i)\b(status|uptime|kemon\s*acho|cholcho|ready)\b", t) \
                and len(t) <= 60:
            return status_text()

        # Greetings.
        if _GREET_RE.match(t):
            try:
                from core import mood as _mood
                key = _mood.current().get("key", "friendly")
            except Exception:
                key = "friendly"
            if key == "girlfriend":
                return "💕 Hey jan! Ami ekhane achi — bolo, ki korbo tomar jonno?"
            if key == "comedy":
                return "😂 Hey hey! Ami ready — hasi-o dibo, kaj-o korbo. Bolo ki chai!"
            if key == "boss":
                return "👑 Yes boss. Ready. Bolo."
            return "😊 Hey! Ami achi — bolo, ki korte hobe?"

        # Calculator.
        expr = try_calc(t)
        if expr is not None:
            ok, val = calc(expr)
            if ok:
                return f"🔢 {expr} = {val}"
            return f"🔢 Hisab-ta holo na: {val}"
        return None
    except Exception:
        return None
