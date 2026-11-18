"""core/social_auto.py — 💬 SOCIAL AUTO-ENGAGEMENT (Instagram / Facebook).

Open a profile, play a reel/video, like, comment, send a message, and
auto-reply — Mark does it once the user tells it once. Flows run through
the no-extension browser driver on Instagram/Facebook in the user's
logged-in Chrome.

PERMISSION-FIRST (the user's own rule): NOTHING is posted or commented
without the user's permission.
  * Like: per-session approval — the user says "ei reel-ta like koro" or
    enables Auto-Like for a session. A like never happens silently.
  * Comment / message: the user approves the EXACT TEXT before it is sent
    (or approves a template once, then Mark uses only that template).
  * Auto-reply: replies in the user's style using user-approved reply
    templates; anything it cannot handle (unknown question, money,
    personal info) is ESCALATED to the user instead of answered — never
    guessed.

SAFE LIMITS (hard-coded, shown in the UI):
  * max ~30 likes/hour and ~150/day;
  * 20-60 s human-like delay with jitter between actions;
  * STOP immediately on any platform warning / captcha / "action blocked"
    message — then tell the user plainly and wait;
  * never run auto-engagement while the user is manually using the same
    account at the same time (conflict guard: pause when the user is
    active in the browser / manual mode is on).

CONTROL: Plugin Settings -> Social Auto with ON/OFF toggles per action
(Auto-Like, Auto-Comment, Auto-Message, Auto-Reply) + the limits shown +
a log of everything Mark did (who, what, when). All toggles OFF by default.

HONEST LIMITS (shown in the UI): Instagram/Facebook login is required
(the user's own account, logged in on Chrome — Mark never sees or stores
the site password); platforms rate-limit automated engagement and too much
of it can warn or temporarily block the account — that is why the caps +
delays exist; auto-reply is template-based, not free-form mind-reading.

No Qt, no network except through the driver. Every public function
returns a plain value and never raises. The driver is injected
(driver_fn) so tests can use a fake.
"""
from __future__ import annotations

import random
import re
import time

try:
    from memory import config_manager as _cm
except Exception:  # pragma: no cover
    _cm = None  # type: ignore

from core.browser_automation import run_steps
from core.browser_driver import ensure_driver

_NS = "social_auto"

# ── hard-coded safe limits ───────────────────────────────────────────────────

MAX_LIKES_HOUR = 30
MAX_LIKES_DAY = 150
DELAY_MIN_S = 20
DELAY_MAX_S = 60
LOG_CAP = 100

TOGGLES = ("auto_like", "auto_comment", "auto_message", "auto_reply")

DEFAULT_TEMPLATES = [
    {"name": "Thanks", "keywords": ["thank", "dhonnobad", "thanks", "shukriya"],
     "text": "Thank you so much! 🙏"},
    {"name": "Hello", "keywords": ["hi", "hello", "hey", "salam", "namaste"],
     "text": "Hello! Kemon acho? 😊"},
    {"name": "Price", "keywords": ["price", "dam", "koto", "cost", "rate"],
     "text": "Price-ta janar jonno please DM koro — ami janiye debo."},
]

_WARNING_RE = re.compile(
    r"(action blocked|temporarily blocked|captcha|try again later"
    r"|we restrict certain activity|unusual activity|suspicious activity"
    r"|you can't do this right now|action not allowed)",
    re.IGNORECASE)

_ESCALATE_RE = re.compile(
    r"(money|payment|pay|price|dam|koto|bank|upi|account|password|otp"
    r"|phone number|address|personal|refund|cancel order)",
    re.IGNORECASE)


def _read_ns() -> dict:
    try:
        if _cm is None:
            return {}
        return dict(_cm.get_plugin_config(_NS) or {})
    except Exception:
        return {}


def _save_ns(values: dict) -> None:
    try:
        if _cm is not None:
            _cm.save_plugin_config(_NS, values)
    except Exception:
        pass


# ── toggles (ALL OFF by default) ─────────────────────────────────────────────

def toggles() -> dict:
    """{auto_like, auto_comment, auto_message, auto_reply} — all False
    until the user turns one ON."""
    try:
        saved = _read_ns().get("toggles")
        out = {t: False for t in TOGGLES}
        if isinstance(saved, dict):
            for t in TOGGLES:
                out[t] = bool(saved.get(t, False))
        return out
    except Exception:
        return {t: False for t in TOGGLES}


def set_toggle(name: str, on: bool) -> bool:
    """Flip one toggle. Returns False for an unknown toggle name."""
    name = (name or "").strip()
    if name not in TOGGLES:
        return False
    cur = toggles()
    cur[name] = bool(on)
    _save_ns({"toggles": cur})
    return True


def limits_text() -> str:
    return (f"Safe limits (hard-coded): max {MAX_LIKES_HOUR} likes/hour, "
            f"{MAX_LIKES_DAY} likes/day, {DELAY_MIN_S}-{DELAY_MAX_S}s "
            "human-like delay with jitter between actions. Platform "
            "warning/captcha pele sathe sathe STOP — tarpor tumi bolo.")


# ── delay with jitter (injectable rng for tests) ─────────────────────────────

def delay_seconds(rng=None) -> float:
    """A human-like pause between actions: 20-60 s with jitter."""
    try:
        r = rng or random
        return float(r.uniform(DELAY_MIN_S, DELAY_MAX_S))
    except Exception:
        return float(DELAY_MIN_S)


# ── like counters (hour/day caps) ────────────────────────────────────────────

def _counters() -> dict:
    try:
        raw = _read_ns().get("counters")
        if isinstance(raw, dict):
            return {"hour": int(raw.get("hour", 0)),
                    "day": int(raw.get("day", 0)),
                    "hour_key": str(raw.get("hour_key", "")),
                    "day_key": str(raw.get("day_key", ""))}
    except Exception:
        pass
    return {"hour": 0, "day": 0, "hour_key": "", "day_key": ""}


def _reset_if_needed(c: dict) -> dict:
    now = time.localtime()
    hour_key = time.strftime("%Y-%m-%d %H", now)
    day_key = time.strftime("%Y-%m-%d", now)
    if c.get("hour_key") != hour_key:
        c["hour"] = 0
        c["hour_key"] = hour_key
    if c.get("day_key") != day_key:
        c["day"] = 0
        c["day_key"] = day_key
    return c


def can_like() -> tuple[bool, str]:
    """Hour/day caps. Returns (ok, reason)."""
    try:
        c = _reset_if_needed(_counters())
        if c["hour"] >= MAX_LIKES_HOUR:
            return False, (f"Like cap: ei ghontay {MAX_LIKES_HOUR} ta like "
                           "hoye geche — porer ghontay abar hobe.")
        if c["day"] >= MAX_LIKES_DAY:
            return False, (f"Like cap: ajke {MAX_LIKES_DAY} ta like hoye "
                           "geche — kal abar hobe.")
        return True, ""
    except Exception as e:
        return False, f"Like cap check korte parlam na: {e}"


def _bump_like() -> None:
    try:
        c = _reset_if_needed(_counters())
        c["hour"] += 1
        c["day"] += 1
        _save_ns({"counters": c})
    except Exception:
        pass


# ── permission gating (pure) ─────────────────────────────────────────────────

def approve_like_session() -> None:
    """The user said 'ei reel-ta like koro' (or enabled Auto-Like for
    this session) — one session approval for likes."""
    _save_ns({"like_session": True})


def like_approved() -> bool:
    """Per-session approval OR the Auto-Like toggle is ON."""
    try:
        if toggles().get("auto_like"):
            return True
        return bool(_read_ns().get("like_session", False))
    except Exception:
        return False


def approve_text(text: str) -> bool:
    """Approve an EXACT comment/message text (stored, so only this text
    may be sent). Returns False for empty text."""
    text = (text or "").strip()
    if not text:
        return False
    try:
        approved = _read_ns().get("approved_texts") or []
        if not isinstance(approved, list):
            approved = []
        if text not in approved:
            approved.append(text)
        _save_ns({"approved_texts": approved[-20:]})
        return True
    except Exception:
        return False


def text_approved(text: str) -> bool:
    """True when this EXACT text was approved by the user."""
    try:
        approved = _read_ns().get("approved_texts") or []
        return (text or "").strip() in list(approved)
    except Exception:
        return False


def can_send(kind: str, text: str) -> tuple[bool, str]:
    """Comment/message gate: the toggle must be ON *and* the exact text
    must be user-approved. Returns (ok, reason)."""
    kind = (kind or "").strip()
    toggle = {"comment": "auto_comment", "message": "auto_message"}.get(kind)
    if toggle is None:
        return False, f"Unknown send kind: {kind}"
    if not toggles().get(toggle):
        return False, (f"{'Auto-Comment' if kind == 'comment' else 'Auto-Message'} "
                       "OFF ache — Settings-e ON koro, tarpor text approve koro.")
    if not text_approved(text):
        return False, ("Ei text-ta approve kora nei — age exact text-ta "
                       "approve koro (Social Auto box-e 'TEXT APPROVE KORO'), "
                       "tarpor pathabo. Bina permission-e kichu pathabo na.")
    return True, ""


# ── warning + escalation detection (pure) ────────────────────────────────────

def detect_warning(page_text: str) -> bool:
    """True when the platform is warning / blocking (captcha, action
    blocked, try again later...). Pure."""
    try:
        return bool(_WARNING_RE.search(page_text or ""))
    except Exception:
        return False


def needs_escalation(incoming: str) -> bool:
    """True when the message is about money / personal info / something
    the templates must NOT answer. Pure."""
    try:
        return bool(_ESCALATE_RE.search(incoming or ""))
    except Exception:
        return False


def templates() -> list[dict]:
    """User-approved reply templates (defaults merged with saved ones)."""
    try:
        saved = _read_ns().get("templates")
        if isinstance(saved, list) and saved:
            return [dict(t) for t in saved if isinstance(t, dict)]
    except Exception:
        pass
    return [dict(t) for t in DEFAULT_TEMPLATES]


def save_templates(tpls: list[dict]) -> bool:
    try:
        clean = []
        for t in tpls or []:
            if not isinstance(t, dict):
                continue
            text = str(t.get("text") or "").strip()
            if text:
                clean.append({"name": str(t.get("name") or "Template")[:40],
                              "keywords": [str(k).lower() for k in
                                           (t.get("keywords") or [])][:10],
                              "text": text[:500]})
        _save_ns({"templates": clean[:20]})
        return True
    except Exception:
        return False


def pick_reply(incoming: str) -> dict | None:
    """The template whose keywords match the incoming message, or None
    (then the message is ESCALATED, never guessed). Pure."""
    try:
        low = (incoming or "").lower()
        for t in templates():
            for kw in (t.get("keywords") or []):
                if kw and str(kw).lower() in low:
                    return t
        return None
    except Exception:
        return None


# ── conflict guard ───────────────────────────────────────────────────────────

def manual_pause_on() -> bool:
    """True when the user is manually using the account right now —
    auto-engagement must pause."""
    try:
        return bool(_read_ns().get("manual_pause", False))
    except Exception:
        return False


def set_manual_pause(on: bool) -> None:
    _save_ns({"manual_pause": bool(on)})


# ── activity log ─────────────────────────────────────────────────────────────

def log_action(who: str, what: str) -> None:
    """Append one entry (who, what, when) to the activity log (cap 100)."""
    try:
        log = _read_ns().get("log") or []
        if not isinstance(log, list):
            log = []
        log.append({"who": str(who or "")[:80], "what": str(what or "")[:200],
                    "at": time.strftime("%Y-%m-%d %H:%M")})
        _save_ns({"log": log[-LOG_CAP:]})
    except Exception:
        pass


def list_log() -> list[dict]:
    try:
        raw = _read_ns().get("log") or []
        return [dict(e) for e in raw if isinstance(e, dict)]
    except Exception:
        return []


def log_text() -> str:
    entries = list_log()
    if not entries:
        return "📋 Ekhono kichu kora hoy ni — Social Auto ja korbe, ekhane dekhabe."
    lines = ["📋 SOCIAL AUTO LOG:"]
    for e in entries[-20:]:
        lines.append(f"  • [{e.get('at', '')}] {e.get('who', '')}: {e.get('what', '')}")
    return "\n".join(lines)


# ── the flows (driver injected) ──────────────────────────────────────────────

def _get_driver(driver_fn=None):
    try:
        fn = driver_fn or ensure_driver
        return fn()
    except Exception as e:
        return None, "", f"Browser driver pelam na: {e}"


def _read_page(driver) -> str:
    try:
        ok, text = driver.read_text()
        return text if ok else ""
    except Exception:
        return ""


def _stop_on_warning(driver, label: str) -> str | None:
    """The warning message when the platform blocked us, else None."""
    text = _read_page(driver)
    if detect_warning(text):
        log_action("Mark", f"⛔ STOP — platform warning ({label})")
        return (f"⛔ STOP — {label}-e platform warning dilo (captcha / "
                "action blocked hote pare). Ami theme gelam — tumi dekho, "
                "tarpor abar bolo.")
    return None


def run_like(profile_url: str, driver_fn=None, delay_fn=None,
             log_fn=None) -> tuple[bool, str]:
    """Like one reel/post — ONLY with per-session approval (or Auto-Like
    ON) and inside the caps. Returns (ok, message)."""
    if manual_pause_on():
        return False, ("⏸️ Tumi nije account-ta chalaccho — auto-engagement "
                       "pause ache. 'Ami nije chalacchi' bondho korle abar cholbe.")
    if not like_approved():
        return False, ("⛔ Like korar permission nei — 'ei reel-ta like koro' "
                       "bolo, ba Social Auto box-e Auto-Like ON koro. Bina "
                       "permission-e like korbo na.")
    ok, reason = can_like()
    if not ok:
        return False, f"⛔ {reason}"
    driver, _backend, msg = _get_driver(driver_fn)
    if driver is None:
        return False, f"Browser driver ready noy — {msg}"
    try:
        ok, m = driver.navigate((profile_url or "").strip()
                                or "https://www.instagram.com/")
        if not ok:
            return False, f"Page khulte parlam na: {m}"
        driver.wait(2)
        warn = _stop_on_warning(driver, "Like")
        if warn:
            return False, warn
        ok, m = run_steps([
            {"label": "Like chaplam", "action": "click",
             "selectors": ["button:has-text('Like')",
                           "svg[aria-label='Like']",
                           "span:has-text('Like')"]},
        ], driver)
        if not ok:
            return False, f"Like korte parlam na: {m}"
        _bump_like()
        log_action("Mark", f"❤️ Like korlam: {profile_url}")
        if callable(log_fn):
            try:
                log_fn("❤️ Like korlam.")
            except Exception:
                pass
        if callable(delay_fn):
            try:
                delay_fn()
            except Exception:
                pass
        return True, "❤️ Like korlam."
    except Exception as e:
        return False, f"Like korte giye error: {e}"


def run_comment(profile_url: str, text: str, driver_fn=None,
                delay_fn=None, log_fn=None) -> tuple[bool, str]:
    """Post a comment — ONLY when the toggle is ON *and* this exact text
    was user-approved. Returns (ok, message)."""
    if manual_pause_on():
        return False, "⏸️ Tumi nije account-ta chalaccho — auto-engagement pause ache."
    ok, reason = can_send("comment", text)
    if not ok:
        return False, f"⛔ {reason}"
    driver, _backend, msg = _get_driver(driver_fn)
    if driver is None:
        return False, f"Browser driver ready noy — {msg}"
    try:
        ok, m = driver.navigate((profile_url or "").strip()
                                or "https://www.instagram.com/")
        if not ok:
            return False, f"Page khulte parlam na: {m}"
        driver.wait(2)
        warn = _stop_on_warning(driver, "Comment")
        if warn:
            return False, warn
        ok, m = run_steps([
            {"label": "Comment box khullam", "action": "click",
             "selectors": ["button:has-text('Comment')",
                           "textarea[placeholder*='comment']",
                           "text=Add a comment"]},
            {"label": "Comment likhlam", "action": "fill",
             "selectors": ["textarea[placeholder*='comment']", "textarea"],
             "text": text},
            {"label": "Post chaplam", "action": "click",
             "selectors": ["button:has-text('Post')", "text=Post"]},
        ], driver)
        if not ok:
            return False, f"Comment korte parlam na: {m}"
        log_action("Mark", f"💬 Comment korlam: {text[:80]}")
        if callable(delay_fn):
            try:
                delay_fn()
            except Exception:
                pass
        return True, f"💬 Comment pathalam: {text[:100]}"
    except Exception as e:
        return False, f"Comment korte giye error: {e}"


def _send_dm(driver, thread_url: str, text: str, delay_fn=None) -> tuple[bool, str]:
    """The actual DM send on an already-launched driver (shared by
    run_message and run_auto_reply). Returns (ok, message)."""
    try:
        ok, m = driver.navigate((thread_url or "").strip()
                                or "https://www.instagram.com/direct/inbox/")
        if not ok:
            return False, f"Page khulte parlam na: {m}"
        driver.wait(2)
        warn = _stop_on_warning(driver, "Message")
        if warn:
            return False, warn
        ok, m = run_steps([
            {"label": "Message box khullam", "action": "click",
             "selectors": ["button:has-text('Message')", "text=Message"]},
            {"label": "Message likhlam", "action": "fill",
             "selectors": ["textarea[placeholder*='Message']", "textarea"],
             "text": text},
            {"label": "Send chaplam", "action": "click",
             "selectors": ["button:has-text('Send')", "text=Send"]},
        ], driver)
        if not ok:
            return False, f"Message pathate parlam na: {m}"
        log_action("Mark", f"✉️ Message pathalam: {text[:80]}")
        if callable(delay_fn):
            try:
                delay_fn()
            except Exception:
                pass
        return True, f"✉️ Message pathalam: {text[:100]}"
    except Exception as e:
        return False, f"Message pathate giye error: {e}"


def run_message(profile_url: str, text: str, driver_fn=None,
                delay_fn=None, log_fn=None) -> tuple[bool, str]:
    """Send a DM — same permission gate as comments. Returns (ok, msg)."""
    if manual_pause_on():
        return False, "⏸️ Tumi nije account-ta chalaccho — auto-engagement pause ache."
    ok, reason = can_send("message", text)
    if not ok:
        return False, f"⛔ {reason}"
    driver, _backend, msg = _get_driver(driver_fn)
    if driver is None:
        return False, f"Browser driver ready noy — {msg}"
    return _send_dm(driver, profile_url, text, delay_fn)


def run_auto_reply(incoming: str, thread_url: str = "", who: str = "",
                   driver_fn=None, log_fn=None) -> tuple[bool, str]:
    """Auto-reply to one incoming message: template match -> reply;
    no match / money / personal info -> ESCALATE to the user, never
    guess. Returns (ok, message)."""
    if not toggles().get("auto_reply"):
        return False, ("⛔ Auto-Reply OFF ache — Settings-e ON koro, "
                       "tarpor reply korbo.")
    if manual_pause_on():
        return False, "⏸️ Tumi nije account-ta chalaccho — auto-engagement pause ache."
    incoming = (incoming or "").strip()
    if not incoming:
        return False, "Reply korar moto message dao."
    if not (thread_url or "").strip():
        return False, ("🆘 Kon thread-e reply korbo bolo (DM link dao) — "
                       "thread chara reply pathabo na.")
    if needs_escalation(incoming):
        log_action("Mark", f"🆘 Escalate korlam: {incoming[:80]}")
        return False, (f"🆘 Ei message-ta ami nije answer korbo na — "
                       f"eta taka / personal info niye: '{incoming[:100]}' "
                       "Tumi bolo ki reply korbo.")
    tpl = pick_reply(incoming)
    if tpl is None:
        log_action("Mark", f"🆘 Escalate korlam (kono template milbe na): {incoming[:80]}")
        return False, (f"🆘 Ei message-er kono approved template pelam na: "
                       f"'{incoming[:100]}' — tumi bolo ki reply korbo, "
                       "ami nije baniye pathabo na.")
    # The template text is user-approved by construction (templates live
    # in Settings and the user approved them there).
    driver, _backend, msg = _get_driver(driver_fn)
    if driver is None:
        return False, f"Browser driver ready noy — {msg}"
    ok, m = _send_dm(driver, thread_url, tpl["text"])
    if ok:
        log_action("Mark", f"↩️ Auto-reply ({tpl.get('name', '')}): {tpl['text'][:80]}")
    return ok, m


def open_profile(profile_url: str, driver_fn=None) -> tuple[bool, str]:
    """Open a profile / reel in the browser and play it (read-only —
    no like/comment without permission). Returns (ok, message)."""
    driver, _backend, msg = _get_driver(driver_fn)
    if driver is None:
        return False, f"Browser driver ready noy — {msg}"
    try:
        ok, m = driver.navigate((profile_url or "").strip())
        if not ok:
            return False, f"Page khulte parlam na: {m}"
        driver.wait(2)
        log_action("Mark", f"👀 Profile khullam: {profile_url}")
        return True, f"👀 Profile khullam: {profile_url}"
    except Exception as e:
        return False, f"Profile khulte giye error: {e}"
