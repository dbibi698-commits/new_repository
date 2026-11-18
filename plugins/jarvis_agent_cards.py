"""plugins/jarvis_agent_cards.py — 🤖 AGENT CARDS: ONE Main Agent + 27
workers, as cards on the master screen / Plugin Settings.

This plugin only REPORTS the cards (core/agent_cards.py) — name, job,
live readiness, what is missing — and the Plugin Settings overlay builds
one card per agent with a Run button ("widget": "agent_cards", the box
itself lives in gui/overlays.py). Running a card calls
core/agent_cards.run_card on a worker thread; the result lands on the
card's status line. A card never pretends: its Run does its real job, or
says plainly what is missing.
"""
from __future__ import annotations

PLUGIN = {
    "name": "agent_cards",
    "description": (
        "List Mark's 28 agent cards — ONE Main Agent (orchestrator) + 27 "
        "workers (Video Upload, APK Build, Render Deploy, Browser Control, "
        "Firebase Connect, Hosting Auto-Fix, WhatsApp, Live Screen, Mouse, "
        "Video Editing, GitHub, File Transfer, Phone, Location, Memory, "
        "Mood, Music, Screenshot, Battery, Voice Notes, Calculator, "
        "Translator, Weather, News, Python Run, Software Builder, Photo Editor) — each with its job and whether it is "
        "ready or what it is missing. Call when the user asks: agent card "
        "gulo dekhao, kon agent ki kore, agent-der status ki."
    ),
    "parameters": {"type": "OBJECT", "properties": {}, "required": []},
}

PLUGIN_SETTINGS = {
    "namespace": "agent_cards",
    "title": "🤖 AGENT CARDS — 1 Main + 27 workers",
    # Extra box the Plugin Settings overlay builds at the end of this
    # section: one card per agent with a Run button. The overlay only
    # knows the widget key; the box itself lives in gui/overlays.py.
    "widget": "agent_cards",
    "fields": [],
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """One line per agent card: name, job, ready/missing. Never raises."""
    try:
        from core import agent_cards as _ac
        cards = _ac.cards()
    except Exception:
        return "Agent card gulo dekhte parlam na — registry porte parini."
    if not cards:
        return "Kono agent card khuje pelam na."
    lines = ["🤖 Agent cards (1 Main + 27 workers):"]
    for c in cards:
        mark = "✅" if c.get("ready") else "⚠️"
        extra = "" if c.get("ready") else f" — missing: {c.get('missing', '')}"
        lines.append(f"{mark} {c.get('icon', '')} {c.get('name', '?')}: "
                     f"{c.get('job', '')}{extra}")
    return "\n".join(lines)
