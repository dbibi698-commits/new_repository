"""core/report_writer.py — 📝 REPORT WRITER: asol report file likhe.

Writes a real Markdown report (topic + date + sections + live Mark-LVII
facts) to ~/MarkLVII/reports/<slug>-<YYYYMMDD-HHMM>.md and returns the
path. No placeholders, no fake numbers — the only facts in the report are
the topic the user gave and live values read from this PC. No Qt, no
network. Every public function returns a plain value and never raises.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

_MAX_TOPIC = 200


def default_reports_dir() -> Path:
    return Path.home() / "MarkLVII" / "reports"


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:40] or "report"


def _live_facts() -> list[str]:
    """Real facts about this PC right now (never invented)."""
    facts: list[str] = []
    try:
        import platform
        facts.append(f"PC: {platform.system()} {platform.release()} "
                     f"({platform.machine()})")
    except Exception:
        pass
    try:
        import sys
        facts.append(f"Python: {sys.version.split()[0]}")
    except Exception:
        pass
    try:
        from core import feature_registry as _fr
        facts.append(f"Feature registry: {_fr.TOTAL:,} features")
    except Exception:
        pass
    try:
        from core import agent_cards as _ac
        facts.append(f"Agent cards: {_ac.count()}")
    except Exception:
        pass
    return facts


def build_report_text(topic: str, extra: str = "") -> str:
    """The report body (pure — no disk). Never raises."""
    try:
        topic = (topic or "").strip()[:_MAX_TOPIC] or "Mark-LVII Report"
        stamp = time.strftime("%Y-%m-%d %H:%M")
        lines = [f"# {topic}", "", f"_Mark-LVII diye likha — {stamp}_", "",
                 "## Ki niye", "", topic, ""]
        extra = (extra or "").strip()
        if extra:
            lines += ["## Details", "", extra[:4000], ""]
        facts = _live_facts()
        if facts:
            lines += ["## Aajker haal (ei PC)", ""]
            lines += [f"- {f}" for f in facts]
            lines.append("")
        lines += ["## Porer step", "",
                  "- Report-ta pore dekho; ja bodlate hobe bolo — "
                  "ami notun kore likhe dibo.", ""]
        return "\n".join(lines)
    except Exception as e:
        return f"# Report\n\nReport likhte parlam na: {e}\n"


def write_report(topic: str, extra: str = "", base_dir: str = "") -> dict:
    """Write the report. Returns {ok, path, error}. Never raises."""
    try:
        topic = (topic or "").strip()
        if not topic:
            return {"ok": False, "path": "",
                    "error": "Report-er topic dao (jemon 'Weekly sales summary')."}
        root = (Path(str(base_dir or "").strip()).expanduser()
                if base_dir else default_reports_dir())
        root.mkdir(parents=True, exist_ok=True)
        name = (f"{slugify(topic)}-"
                f"{time.strftime('%Y%m%d-%H%M')}.md")
        path = root / name
        path.write_text(build_report_text(topic, extra), encoding="utf-8")
        return {"ok": True, "path": str(path), "error": ""}
    except Exception as e:
        return {"ok": False, "path": "",
                "error": f"Report likhte parlam na: {e}"}


def write_report_text(topic: str, extra: str = "") -> str:
    """One plain-words string for chat / cards. Never raises."""
    try:
        res = write_report(topic, extra)
        if not res.get("ok"):
            return f"📝 Report Writer — {res.get('error', '')}"
        return f"📝 Report likhe dilam: {res['path']}"
    except Exception as e:
        return f"Report likhte parlam na: {e}"
