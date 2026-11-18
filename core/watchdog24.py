"""core/watchdog24.py — ⏰ BACKGROUND 24 HOURS: uptime + self-watchdog.

WHAT THIS IS
    Mark on the PC is meant to run all day. Two things make that real:

    1. UPTIME + AUTOSTART STATUS — how long Mark has been up, whether
       Windows will start him again after a restart, and what the PHONE's
       background is doing (last heartbeat seen over the relay).
    2. A SUPERVISOR — a daemon thread that watches Mark's own services
       (the Live session, the Jarvis Link poller, the dashboard server)
       once a minute and restarts any that died, instead of the whole app
       sitting dead until somebody notices.

WHAT THIS IS NOT (honest, shown in the UI too)
    Nothing runs while the PC is fully OFF. A restart or a Windows
    update still needs autostart to bring Mark back — that is what the
    autostart toggle is for, and its state is shown here so the user can
    see it. Wake-on-LAN cannot wake the PC from itself, so it is not
    built and not promised.

Nothing here imports Qt; nothing here ever raises.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

_START_MONO = time.monotonic()
_START_WALL = time.time()

_LOCK = threading.Lock()
_SERVICES: dict[str, dict] = {}
_WATCHDOG_THREAD: threading.Thread | None = None
_WATCHDOG_STOP = threading.Event()
_WATCHDOG_RUNNING = {"on": False}


def uptime_seconds() -> float:
    try:
        return max(0.0, time.monotonic() - _START_MONO)
    except Exception:
        return 0.0


def uptime_text() -> str:
    try:
        secs = int(uptime_seconds())
        if secs < 60:
            return f"{secs}s"
        mins, sec = divmod(secs, 60)
        hrs, mins = divmod(mins, 60)
        days, hrs = divmod(hrs, 24)
        if days:
            return f"{days}d {hrs}h {mins}m"
        if hrs:
            return f"{hrs}h {mins}m"
        return f"{mins}m {sec}s"
    except Exception:
        return "?"


def started_at_text() -> str:
    try:
        return datetime.fromtimestamp(_START_WALL).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


# ── supervisor ───────────────────────────────────────────────────────────────

def register_service(name: str, alive_fn, restart_fn) -> None:
    """Register one of Mark's own services. alive_fn() -> bool,
    restart_fn() -> str (what it did). Never raises."""
    try:
        with _LOCK:
            _SERVICES[str(name or "?")] = {
                "alive_fn": alive_fn, "restart_fn": restart_fn,
                "restarts": 0, "last_check": "", "last_restart": "",
            }
    except Exception:
        pass


def check_now() -> list[dict]:
    """Check every registered service once; restart the dead ones.
    Returns [{name, alive, restarted, note}]. Never raises."""
    out = []
    try:
        with _LOCK:
            items = list(_SERVICES.items())
        for name, svc in items:
            alive = False
            note = ""
            restarted = False
            try:
                alive = bool(svc["alive_fn"]())
            except Exception as e:
                note = f"check korte parlam na: {e}"
            if not alive:
                try:
                    note = str(svc["restart_fn"]() or "restart korlam")
                    restarted = True
                    with _LOCK:
                        svc["restarts"] = int(svc.get("restarts") or 0) + 1
                        svc["last_restart"] = datetime.now().strftime("%H:%M:%S")
                except Exception as e:
                    note = f"restart korte parlam na: {e}"
            with _LOCK:
                svc["last_check"] = datetime.now().strftime("%H:%M:%S")
            out.append({"name": name, "alive": bool(alive),
                        "restarted": restarted, "note": note,
                        "restarts": int(svc.get("restarts") or 0)})
        return out
    except Exception:
        return out


def _watchdog_loop(interval_s: float = 60.0) -> None:
    while not _WATCHDOG_STOP.is_set():
        try:
            check_now()
        except Exception:
            pass
        _WATCHDOG_STOP.wait(max(10.0, float(interval_s or 60.0)))


def start_watchdog(interval_s: float = 60.0) -> bool:
    """Start the supervisor thread (idempotent). Never raises."""
    global _WATCHDOG_THREAD
    try:
        with _LOCK:
            if _WATCHDOG_THREAD is not None and _WATCHDOG_THREAD.is_alive():
                return True
            _WATCHDOG_STOP.clear()
            _WATCHDOG_THREAD = threading.Thread(
                target=_watchdog_loop, args=(interval_s,), daemon=True,
                name="mark-watchdog24")
            _WATCHDOG_THREAD.start()
            _WATCHDOG_RUNNING["on"] = True
            return True
    except Exception:
        return False


def stop_watchdog() -> None:
    global _WATCHDOG_THREAD
    try:
        _WATCHDOG_STOP.set()
        t = _WATCHDOG_THREAD
        if t is not None and t.is_alive():
            t.join(timeout=5)
        with _LOCK:
            _WATCHDOG_THREAD = None
            _WATCHDOG_RUNNING["on"] = False
    except Exception:
        pass


def watchdog_running() -> bool:
    try:
        with _LOCK:
            t = _WATCHDOG_THREAD
        return bool(t is not None and t.is_alive())
    except Exception:
        return False


# ── phone background status ──────────────────────────────────────────────────

def phone_background_text() -> str:
    """The PHONE's background, from the relay: paired? last seen when?
    Never raises; never pretends."""
    try:
        from core import jarvis_link as _jl
        link = _jl.LINK
        if link is None:
            return "📱 Phone link load hoy ni."
        if not getattr(link, "paired", False):
            return "📱 Phone pair kora nei — background status jani na."
        seen = None
        try:
            seen_raw = getattr(link, "last_phone_seen", None)
            if callable(seen_raw):
                seen = seen_raw()
            elif isinstance(seen_raw, str) and seen_raw:
                # ISO string (jarvis_link.last_phone_seen) -> epoch.
                seen = datetime.fromisoformat(seen_raw).timestamp()
            elif isinstance(seen_raw, (int, float)):
                seen = float(seen_raw)
        except Exception:
            seen = None
        if seen is None:
            return "📱 Phone pair kora ache — ekhono kono heartbeat/message ashe ni."
        ago = time.time() - float(seen)
        if ago < 90:
            return "📱 Phone background cholche — heartbeat asche (ekhoni)."
        mins = int(ago // 60)
        if mins < 60:
            return (f"📱 Phone-er shesh heartbeat {mins} min age — phone-e "
                    f"Jarvis khola ache kina dekho.")
        return (f"📱 Phone-er shesh heartbeat {mins // 60}h {mins % 60}m age — "
                f"phone-e Jarvis bondho thakle background cholbe na.")
    except Exception as e:
        return f"Phone-er background status dekhte parlam na: {e}"


# ── the 24h status block ─────────────────────────────────────────────────────

def status_text() -> str:
    """One plain-words block for the Plugin Settings box + master screen.
    Never raises."""
    try:
        lines = ["⏰ 24H RUNNING — Mark kotokhon dhore cholche:"]
        lines.append(f"  • Uptime: {uptime_text()} (start: {started_at_text()})")
        try:
            from core import autostart as _as
            on = _as.autostart_enabled()
            lines.append("  • Autostart: " + ("✅ ON — Windows restart hole "
                        "Mark nijei chalu hobe" if on else
                        "❌ OFF — Windows restart hole Mark nije chalu hobe na; "
                        "ON korte Settings-e Autostart chapo"))
        except Exception:
            lines.append("  • Autostart: check korte parlam na")
        lines.append("  • Watchdog: " + ("✅ cholche — mara gele service nijei "
                    "restart korbe" if watchdog_running() else
                    "❌ cholche na"))
        with _LOCK:
            items = list(_SERVICES.items())
        if items:
            for name, svc in items:
                lines.append(f"    - {name}: "
                             f"{int(svc.get('restarts') or 0)} bar restart")
        lines.append("  • " + phone_background_text())
        lines.append("  • ⚠️ PC puropuri bondho thakle kichu cholbe na — "
                     "PC chalu hole autostart-e Mark fire asbe, ar joma "
                     "thaka task gulo nijei cholbe.")
        return "\n".join(lines)
    except Exception as e:
        return f"24h status dekhte parlam na: {e}"
