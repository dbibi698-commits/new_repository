"""plugins/utility_time.py — ⏱️ TIME tools: Timer, Stopwatch, Pomodoro,
World Clock, Sleep Timer, Focus Mode. Thin voice wrapper over
core/utility_tools.py. Returns a short string, never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "utility_time",
    "description": (
        "Time tools — timer (countdown), stopwatch (start/stop/lap), "
        "pomodoro (25 min work + 5 min break), world clock, sleep timer "
        "(PC sleeps after N minutes), focus mode (notifications off + "
        "timer). Call when the user says: timer dao, stopwatch, pomodoro, "
        "world clock, sleep timer, focus mode."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "timer | timer_status | stopwatch | pomodoro | world_clock | sleep_timer | sleep_cancel | focus_on | focus_off"},
            "minutes": {"type": "NUMBER",
                        "description": "Minutes for timer / sleep timer / focus mode (default 5 / 30 / 25)."},
            "label": {"type": "STRING",
                      "description": "Timer label."},
            "cities": {"type": "STRING",
                       "description": "Comma-separated cities for world clock (kolkata, london, dubai...)."},
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        p = parameters or {}
        action = str(p.get("action") or "timer_status").strip().lower()
        from core import utility_tools as u
        if action == "timer":
            return u.start_timer(float(p.get("minutes") or 5),
                                 str(p.get("label") or "Timer"))
        if action == "timer_status":
            return u.timer_status()
        if action == "stopwatch":
            return u.stopwatch(str(p.get("stopwatch_action") or "status"))
        if action == "pomodoro":
            return u.pomodoro(str(p.get("pomodoro_action") or "status"))
        if action == "world_clock":
            return u.world_clock(str(p.get("cities") or ""))
        if action == "sleep_timer":
            return u.sleep_timer(float(p.get("minutes") or 30))
        if action == "sleep_cancel":
            return u.sleep_timer(0, cancel=True)
        if action == "focus_on":
            return u.focus_mode(True, float(p.get("minutes") or 25))
        if action == "focus_off":
            return u.focus_mode(False)
        return u.timer_status()
    except Exception as e:
        return f"Time tool chalate parlam na: {e}"
