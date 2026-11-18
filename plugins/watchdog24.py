"""plugins/watchdog24.py — 🕐 24H RUNNING: Mark's uptime, autostart state,
and the watchdog that restarts Mark's own services if they die, plus the
phone's background status (from its heartbeat / last-seen).

Honest: a PC restart / Windows update still needs autostart; nothing
runs while the PC is fully off — the box says so. Never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "watchdog24",
    "description": (
        "24-hour running status — Mark's uptime, autostart state, watchdog "
        "status, and the phone's background status (last seen). Call when "
        "the user says: 24 ghonta cholche kina, uptime koto, phone background "
        "ki obostha."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
        "required": [],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "watchdog24",
    "title": "🕐 24H RUNNING — uptime, autostart, watchdog",
    "fields": [],
    # Extra box the Plugin Settings overlay builds at the end of this
    # section: uptime + autostart + watchdog + phone background status.
    # The overlay only knows the widget key; the box itself lives in
    # gui/overlays.py.
    "widget": "running24",
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        from core import watchdog24 as w
        return w.status_text()
    except Exception as e:
        return f"24h status dekhte parlam na: {e}"
