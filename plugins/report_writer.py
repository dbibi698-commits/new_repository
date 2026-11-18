"""plugins/report_writer.py — 📝 REPORT WRITER: asol report file likhe.

Writes a real Markdown report (topic + date + sections + live PC facts)
to ~/MarkLVII/reports/. Runs on a worker thread. Returns a short string,
never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "report_writer",
    "description": (
        "Write a real report file from a topic: Markdown report with the "
        "topic, date, details and live facts about this PC, saved under "
        "MarkLVII/reports. Call when the user asks: report likho, summary "
        "likhe dao, report banao."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "topic": {"type": "STRING",
                      "description": "Report-er topic, e.g. 'Weekly sales summary'."},
            "extra": {"type": "STRING",
                      "description": "Extra details to include in the report."},
        },
        "required": ["topic"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Write the report. Short string, never raises."""
    try:
        params = parameters or {}
        topic = str(params.get("topic") or "").strip()
        if not topic:
            return "📝 Report Writer — topic dao (jemon 'Weekly sales summary')."
        from core import report_writer as _rw
        return _rw.write_report_text(topic, str(params.get("extra") or ""))
    except Exception as e:
        return f"Report likhte parlam na: {e}"
