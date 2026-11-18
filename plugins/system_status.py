"""plugins/system_status.py — 🖥️ SYSTEM STATUS: autostart, Python, Chrome,
Playwright, Java/Gradle — the true detected state of this PC.

The Plugin Settings overlay builds the "System Status" box for this plugin
(widget "system_status" in PLUGIN_SETTINGS below): a Refresh button, the
status lines, and the Windows autostart ON/OFF toggle. The tool itself
answers by voice ("system status ki?") with the same lines.

Nothing here is guessed: autostart is the real Startup-folder shortcut,
Chrome/Java/Gradle are real detections on this PC, Playwright is a real
import check. On a PC without Java/Gradle the box says so plainly instead
of pretending a local Gradle build would work.
"""
from __future__ import annotations

PLUGIN = {
    "name": "system_status",
    "description": (
        "Show this PC's true status — Windows autostart on/off, Python "
        "version, Chrome found yes/no, Playwright installed yes/no, "
        "Java/Gradle found yes/no. Call when the user asks: system status "
        "ki, autostart on ache kina, chrome ache kina, java/gradle ache kina."
    ),
    "parameters": {"type": "OBJECT", "properties": {}, "required": []},
}

PLUGIN_SETTINGS = {
    "namespace": "system_status",
    "title": "🖥️ SYSTEM STATUS — autostart, Python, Chrome, Java/Gradle",
    # Extra box the Plugin Settings overlay builds at the end of this
    # section: status lines + Refresh + autostart toggle. The overlay only
    # knows the widget key; the box itself lives in gui/overlays.py.
    "widget": "system_status",
    "fields": [],
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """One status block. Never raises."""
    try:
        from core import autostart as _as
        return _as.environment_lines()
    except Exception as e:
        return f"System status dekhte parlam na: {e}"
