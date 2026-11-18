"""core/auto_tasks.py — 📋 AUTOMATIC TASKS / CUSTOM TASKS.

The user creates a task by voice/text ("protidin sokal 8-tay weather
report dao", "proti Robibar Downloads organize koro", "1 minute pore
ekta test report banao") — this module parses it into a real
core/automation.py task whose steps run through the COMMANDER
(Commander -> worker -> result), stores it in config, and reports every
completion (done + result) in the Tasks panel (queue / running / done /
failed + reason).

EXECUTOR — the honest part:
- "pc": the task runs on THIS PC, only while Mark is running. While
  the PC is fully off nothing runs; the scheduler catches the task up
  the moment Mark starts (autostart is already there).
- "phone": the task is sent to the PHONE (TASK_SCHEDULE:: over the
  relay) and the PHONE's background service fires it at its time — even
  when the PC is off. When the PC comes back online the phone reports
  the completion (TASK_REPORT::) and it lands in the same history.
- "auto": PC if the task needs the PC, else the phone when the action
  is phone-capable (message / upload / call / reminder).
- "backend": reserved for backend-run tasks (not used yet — said plainly
  when asked).

OFFLINE MODE: tasks that need no internet run offline. Internet tasks
that fail for no-network are queued and auto-retried when connectivity
returns (retry_offline_tasks, called by the scheduler tick + the panel
refresh).

Never claims a task ran while the PC was off. Never raises.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import datetime, timedelta

from memory.config_manager import get_plugin_config, save_plugin_config

_NS = "auto_tasks"
_META_NS = "auto_tasks_meta"

PC_OFF_NOTE = ("⚠️ PC OFF thakle PC-r task cholbe na — PC chalu hole "
               "automatically cholbe. Phone-er task phone-e cholbe, PC "
               "off thakleo.")

_WEEKDAY_BN = {"sombar": 0, "som": 0, "monday": 0, "mon": 0,
               "mongolbar": 1, "mongol": 1, "tuesday": 1, "tue": 1,
               "budhbar": 2, "budh": 2, "wednesday": 2, "wed": 2,
               "brihospotibar": 3, "brihospoti": 3, "thursday": 3, "thu": 3,
               "shukrobar": 4, "shukro": 4, "friday": 4, "fri": 4,
               "shonibar": 5, "shoni": 5, "saturday": 5, "sat": 5,
               "robibar": 6, "robi": 6, "sunday": 6, "sun": 6}

# Order words that are phone-capable (message / upload / call / reminder).
_PHONE_CAPABLE = ("message", "sms", "whatsapp", "call", "upload", "video",
                  "reminder", "alarm", "pathao", "pathabo", "dak", "bajao",
                  "photo", "chobi", "ring", "bajbe")


def _meta() -> dict:
    try:
        return dict(get_plugin_config(_META_NS) or {})
    except Exception:
        return {}


def _save_meta(m: dict) -> None:
    try:
        save_plugin_config(_META_NS, dict(m))
    except Exception:
        pass


def _parse_time(text: str) -> tuple[int, int] | None:
    """HH:MM from '8-tay', '8:30', 'sokal 8', 'rat 9:15', '20:00'."""
    t = str(text or "").lower()
    m = re.search(r"(\d{1,2})[:\.](\d{2})", t)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
    m = re.search(r"(\d{1,2})\s*(?:-?ta|-?tay|-?te)?\s*(?:sokal|dupur|bikal|sandhya|rat)?", t)
    if m:
        hh = int(m.group(1))
        if 0 <= hh <= 23:
            if "rat" in t and hh < 12:
                hh += 12
            if "dupur" in t and hh < 12:
                hh += 12
            return hh, 0
    return None


def parse_task_text(text: str) -> dict:
    """Parse Bengali/English task speech into a task spec. Never raises.
    Returns {name, kind, time, weekday, day, at, order, executor}."""
    try:
        t = str(text or "").strip()
        low = t.lower()
        spec: dict = {"name": t[:120], "kind": "once", "time": None,
                      "weekday": None, "day": None, "at": None,
                      "order": t, "executor": "auto"}
        # ── recurrence ──
        if "protidin" in low or "prottek din" in low or "every day" in low \
                or "daily" in low or "roj" in low:
            spec["kind"] = "daily"
        elif "proti" in low and ("masher" in low or "month" in low or
                                 "mash" in low):
            spec["kind"] = "monthly"
            m = re.search(r"(\d{1,2})\s*(?:tarikh|tarik|th)", low)
            if m:
                spec["day"] = max(1, min(31, int(m.group(1))))
        else:
            for name, wd in _WEEKDAY_BN.items():
                if re.search(rf"\b{name}\b", low) and \
                        ("proti" in low or "every" in low or "har" in low):
                    spec["kind"] = "weekly"
                    spec["weekday"] = wd
                    break
        # ── one-off delay: "1 minute pore" / "10 min pore" / "in 5 minutes" ──
        m = re.search(r"(\d+)\s*(?:minute|min|mint|minute-e)\s*pore", low) or \
            re.search(r"in\s+(\d+)\s*min", low)
        if m and spec["kind"] == "once":
            at = datetime.now() + timedelta(minutes=int(m.group(1)))
            spec["at"] = at.isoformat(timespec="seconds")
            spec["name"] = t[:120]
        # ── time of day ──
        hhmm = _parse_time(t)
        if hhmm:
            spec["time"] = f"{hhmm[0]:02d}:{hhmm[1]:02d}"
        # ── executor ──
        if "phone" in low or "phone-e" in low or "mobile" in low:
            spec["executor"] = "phone"
        elif "pc" in low or "computer" in low or "pc-te" in low:
            spec["executor"] = "pc"
        elif any(w in low for w in _PHONE_CAPABLE):
            spec["executor"] = "auto"  # phone-capable; auto decides
        # ── order text: strip the scheduling words ──
        order = t
        for pat in (r"protidin\s*", r"prottek din\s*", r"proti\s+\w+\s*",
                    r"every day\s*", r"daily\s*",
                    r"\d+\s*(?:minute|min|mint)\s*pore\s*",
                    r"in\s+\d+\s*min\s*"):
            order = re.sub(pat, "", order, flags=re.IGNORECASE)
        spec["order"] = order.strip() or t
        if not spec["time"] and spec["kind"] in ("daily", "weekly", "monthly"):
            spec["time"] = "08:00"
        return spec
    except Exception:
        return {"name": str(text or "")[:120], "kind": "once", "time": None,
                "weekday": None, "day": None, "at": None,
                "order": str(text or ""), "executor": "auto"}


def create_task_from_text(text: str) -> str:
    """Create a real automation task from voice/text. Runs via the
    Commander (step tool 'commander'). Sends phone-side tasks to the
    phone as well. Never raises."""
    try:
        spec = parse_task_text(text)
        from core import automation as _a
        engine = _a.ENGINE
        trigger: dict = {"type": "time", "kind": spec["kind"]}
        if spec.get("time"):
            trigger["time"] = spec["time"]
        if spec.get("weekday") is not None:
            trigger["weekday"] = spec["weekday"]
        if spec.get("day"):
            trigger["day"] = spec["day"]
        if spec.get("at"):
            trigger["at"] = spec["at"]
        task_id = engine.create_task({
            "name": spec["name"][:120],
            "trigger": trigger,
            "steps": [{"tool": "commander",
                       "args": {"order": spec["order"]}}],
            "description": f"executor={spec['executor']} — "
                           f"auto task ({spec['kind']})",
        })
        if not task_id:
            return ("📋 Task banate parlam na — naam + kokhon cholbe "
                    "(time/recurrence) bolo.")
        meta = _meta()
        meta[str(task_id)] = {"executor": spec["executor"],
                              "order": spec["order"],
                              "created_at": datetime.now().isoformat(
                                  timespec="seconds")}
        _save_meta(meta)
        note = ""
        if spec["executor"] == "phone":
            note = send_task_to_phone(task_id, spec)
        elif spec["executor"] == "auto" and any(
                w in spec["order"].lower() for w in _PHONE_CAPABLE):
            note = " (phone-eo cholte pare — PC off thakle phone korbe)"
        when = spec.get("at") or (f"{spec['kind']} {spec.get('time') or ''}")
        return (f"📋 Task banalam: {spec['name'][:80]}\n"
                f"  • Kokhon: {when}\n"
                f"  • Executor: {spec['executor']}{note}\n"
                f"  • Kaj: {spec['order'][:120]}")
    except Exception as e:
        return f"Task banate parlam na: {e}"


def executor_of(task_id: str) -> str:
    try:
        return str(_meta().get(str(task_id), {}).get("executor") or "auto")
    except Exception:
        return "auto"


def send_task_to_phone(task_id: str, spec: dict | None = None) -> str:
    """Send a TASK_SCHEDULE:: payload to the phone over the relay
    (text-prefix fallback — the reliable path). The phone fires it at
    its time and reports back TASK_REPORT::. Never raises."""
    try:
        from core import jarvis_link as _jl
        link = _jl.LINK
        if link is None or not getattr(link, "paired", False):
            return " (⚠️ phone pair kora nei — phone-e pathate parlam na)"
        spec = spec or {}
        payload = {"task_id": str(task_id),
                   "name": str(spec.get("name") or "")[:120],
                   "kind": str(spec.get("kind") or "once"),
                   "time": spec.get("time"), "weekday": spec.get("weekday"),
                   "day": spec.get("day"), "at": spec.get("at"),
                   "order": str(spec.get("order") or "")[:300]}
        ok = link.send_text("TASK_SCHEDULE::" + json.dumps(payload))
        return (" — phone-e pathalam ✅" if ok else
                " — phone-e pathate parlam na (relay)")
    except Exception as e:
        return f" — phone-e pathate parlam na: {e}"


def handle_task_report(payload: dict | str) -> str:
    """A TASK_REPORT:: from the phone (it ran a task while the PC was
    off). Records it in the automation history with executor=phone.
    Never raises."""
    try:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {"name": payload, "status": "ok", "result": ""}
        payload = dict(payload or {})
        name = str(payload.get("name") or payload.get("task_id") or "phone task")
        status = str(payload.get("status") or "ok").lower()
        result = str(payload.get("result") or "")[:300]
        from core import automation as _a
        _a.ENGINE.record_external_run(name, status, result, executor="phone")
        return (f"📱 Phone task complete: {name} — {status} "
                f"({result[:120]})")
    except Exception as e:
        return f"Phone report record korte parlam na: {e}"


def check_internet(timeout: int = 3) -> bool:
    """Quick connectivity probe (backend). Never raises."""
    try:
        req = urllib.request.Request(
            "https://jarvis-backend-8ray.onrender.com/api/live-status",
            headers={"User-Agent": "Mark-LVII/1.0"})
        with urllib.request.urlopen(req, timeout=max(2, int(timeout or 3))):
            return True
    except Exception:
        return False


def mark_offline(task_id: str, reason: str = "no internet") -> None:
    """Queue a failed internet task for auto-retry. Never raises."""
    try:
        cfg = dict(get_plugin_config(_NS) or {})
        q = list(cfg.get("offline_queue") or [])
        q = [e for e in q if str(e.get("task_id")) != str(task_id)]
        q.append({"task_id": str(task_id), "reason": str(reason)[:200],
                  "at": datetime.now().isoformat(timespec="seconds")})
        cfg["offline_queue"] = q[-50:]
        save_plugin_config(_NS, cfg)
    except Exception:
        pass


def retry_offline_tasks() -> str:
    """Retry queued internet tasks when connectivity is back. Never raises."""
    try:
        cfg = dict(get_plugin_config(_NS) or {})
        q = list(cfg.get("offline_queue") or [])
        if not q:
            return "📋 Offline queue khali."
        if not check_internet():
            return (f"📋 Offline queue: {len(q)} ta task — ekhono internet "
                    "nei, pore abar chesta korbo.")
        from core import automation as _a
        retried, still = 0, []
        for entry in q:
            tid = str(entry.get("task_id") or "")
            res = _a.ENGINE.run_task_now(tid)
            if res and ("holo na" not in res and "pelam na" not in res):
                retried += 1
            else:
                still.append(entry)
        cfg["offline_queue"] = still
        save_plugin_config(_NS, cfg)
        return (f"📋 Offline retry: {retried} ta task cholllo, "
                f"{len(still)} ta ekhono queue-e.")
    except Exception as e:
        return f"Offline retry korte parlam na: {e}"


def tasks_panel_text() -> str:
    """Queue / running / done / failed + executor + PC-off honesty.
    Used by the master screen + Plugin Settings Tasks panel."""
    try:
        from core import automation as _a
        engine = _a.ENGINE
        tasks = engine.list_tasks()
        hist = engine.history()
        cfg = dict(get_plugin_config(_NS) or {})
        offline = list(cfg.get("offline_queue") or [])
        lines = ["📋 AUTOMATIC TASKS:"]
        if not tasks:
            lines.append("  • Kono task nei — 'protidin sokal 8-tay ...' "
                         "bolle banabo.")
        for t in tasks:
            ex = executor_of(str(t.get("id") or ""))
            nxt = str(t.get("next_run") or "")[:16]
            lines.append(f"  • {'✅' if t.get('enabled') else '⏸️'} "
                         f"{t.get('name')} — {t.get('trigger', {}).get('kind') or ''} "
                         f"{nxt} • executor: {ex}")
        lines.append("")
        lines.append("  History (ke chalalo — phone / pc / backend):")
        for h in hist[-8:]:
            ex = str(h.get("executor") or "pc")
            lines.append(f"  • [{ex}] {h.get('task_name')} — "
                         f"{h.get('status')} • {str(h.get('finished_at') or '')[:16]}"
                         + (f" • {str(h.get('note') or '')[:80]}"
                            if h.get("note") else ""))
        if offline:
            lines.append(f"  • 📶 Offline queue: {len(offline)} ta task "
                         "(net asle auto-retry)")
        lines.append("")
        lines.append("  " + PC_OFF_NOTE)
        return "\n".join(lines)
    except Exception as e:
        return f"Tasks panel dekhte parlam na: {e}"
