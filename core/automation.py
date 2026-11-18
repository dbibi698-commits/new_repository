"""core/automation.py — Task Automation ENGINE for Mark-LVII.

WHAT THIS IS
    Scheduled / triggered multi-step tasks: the user (or the model, through
    the `automation` plugin) defines a task once — a trigger plus an ordered
    list of tool steps — and the engine runs it when the trigger fires, under
    the owning worker agent for each step, and remembers the run in history.

    Triggers: time (once / daily / weekly), interval (every N minutes/hours),
    keyword (a phrase in what the user says), event (a named app event, e.g.
    "phone_connected"), webhook (fired from the dashboard only).

RULES THIS FILE LIVES BY
    * No Qt anywhere — the scheduler is a plain daemon thread.
    * No public method ever raises: bad input returns "" / False / [] and a
      failed step retries once, then the task is marked failed and logged.
    * Persistence goes through memory/config_manager.py only, under
      plugin_config["automation"] — never config/api_keys.json directly.
    * Tool execution goes through a runner callback registered with
      set_tool_runner(). main.py registers its _run_tool_for_plugin there;
      until it does, steps fail cleanly with an honest message.
    * Only the stdlib (+ requests, unused here) — nothing new in
      requirements.txt.

TOOL ARGS IN THE TEMPLATES BELOW ARE REAL — read off the declarations, not
guessed: weather_report {city, time}, web_search {query, mode},
drive_list {}, drive_upload {filename, content} (text files ONLY — it takes
content, not a folder path), facebook_post {message, page_id},
instagram_post {image_url, caption} (image_url must be a PUBLIC URL),
facebook_upload_video {file_path, title, description},
instagram_upload_video {file_path_or_url, caption}.
"""
from __future__ import annotations

import ctypes
import json
import re
import socket
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta

_NAMESPACE = "automation"
_HISTORY_CAP = 50
_CHECK_INTERVAL_S = 15.0
_NO_RUNNER_MSG = "automation tool runner not wired yet — restart Mark"

_PCT_RE = re.compile(r"(\d{1,3})\s*%")

# Weekday names accepted in a weekly trigger, 0 = Monday.
_WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2, "thursday": 3, "thu": 3, "thur": 3,
    "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


# ── small helpers (never raise) ──────────────────────────────────────────────

def _now_iso() -> str:
    try:
        return datetime.now().isoformat(timespec="seconds")
    except Exception:
        return ""


def _parse_iso(value) -> datetime | None:
    try:
        if not value:
            return None
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _parse_hhmm(value) -> tuple[int, int] | None:
    """'07:50' -> (7, 50). None when unparsable."""
    try:
        parts = str(value or "").strip().split(":")
        if len(parts) != 2:
            return None
        hh, mm = int(parts[0]), int(parts[1])
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
    except Exception:
        pass
    return None


def _parse_weekday(value) -> int | None:
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if 0 <= value <= 6 else None
        if isinstance(value, float) and value.is_integer():
            return int(value) if 0 <= value <= 6 else None
        return _WEEKDAYS.get(str(value or "").strip().lower())
    except Exception:
        return None


def _as_dict(value) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value) -> list:
    return list(value) if isinstance(value, list) else []


def _is_problem(result: str) -> bool:
    """Did a tool step fail? Uses core/outcome's own vocabulary when it is
    available (status=failed / unverified / ask); falls back to an empty
    result counting as a failure. A plain sentence is a success."""
    try:
        from core import outcome
        return outcome.is_problem(result)
    except Exception:
        pass
    return not str(result or "").strip()


def _parse_progress(result: str) -> int | None:
    """Best-effort '%' in a tool result, for the owning agent's progress bar."""
    try:
        m = _PCT_RE.search(str(result or ""))
        if m:
            return max(0, min(100, int(m.group(1))))
    except Exception:
        pass
    return None


# ── next-run computation ─────────────────────────────────────────────────────

def compute_next_run(task: dict, now: datetime | None = None) -> str | None:
    """Next ISO time a task should fire, or None for non-scheduled triggers
    (keyword / event / webhook) and for a once-off time already past."""
    try:
        now = now or datetime.now()
        trigger = _as_dict(task.get("trigger"))
        ttype = str(trigger.get("type") or "").strip().lower()
        if ttype == "time":
            # A single ISO datetime in "at" stands alone: no HH:MM needed.
            # (Without this, an "at"-only once-off trigger returned None.)
            at = _parse_iso(trigger.get("at"))
            if at is not None:
                return at.isoformat(timespec="seconds") if at > now else None
            hhmm = _parse_hhmm(trigger.get("time"))
            if hhmm is None:
                return None
            hh, mm = hhmm
            kind = str(trigger.get("kind") or "").strip().lower()
            if not kind:
                # Infer the kind from what was given: a date means once,
                # a weekday means weekly, otherwise daily.
                if trigger.get("date"):
                    kind = "once"
                elif trigger.get("weekday") is not None:
                    kind = "weekly"
                else:
                    kind = "daily"
            if kind == "once":
                date_s = str(trigger.get("date") or "").strip()
                if not date_s:
                    # A single ISO datetime in "at" is accepted too.
                    at = _parse_iso(trigger.get("at"))
                    if at is not None:
                        return at.isoformat(timespec="seconds") if at > now else None
                    return None
                try:
                    day = datetime.strptime(date_s, "%Y-%m-%d").date()
                except Exception:
                    return None
                when = datetime(day.year, day.month, day.day, hh, mm)
                return when.isoformat(timespec="seconds") if when > now else None
            if kind == "weekly":
                wd = _parse_weekday(trigger.get("weekday"))
                if wd is None:
                    return None
                days_ahead = (wd - now.weekday()) % 7
                when = (now + timedelta(days=days_ahead)).replace(
                    hour=hh, minute=mm, second=0, microsecond=0)
                if when <= now:
                    when += timedelta(days=7)
                return when.isoformat(timespec="seconds")
            if kind == "monthly":
                # trigger.day = day-of-month (1-31); clamp to the month's
                # length (e.g. 31 -> 30 in April, 28/29 in February).
                try:
                    day = int(trigger.get("day") or 1)
                except Exception:
                    return None
                day = max(1, min(31, day))
                import calendar as _cal
                y, m = now.year, now.month
                last = _cal.monthrange(y, m)[1]
                when = now.replace(day=min(day, last), hour=hh, minute=mm,
                                   second=0, microsecond=0)
                if when <= now:
                    m += 1
                    if m > 12:
                        m, y = 1, y + 1
                    last = _cal.monthrange(y, m)[1]
                    when = when.replace(year=y, month=m,
                                        day=min(day, last))
                return when.isoformat(timespec="seconds")
            # daily
            when = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if when <= now:
                when += timedelta(days=1)
            return when.isoformat(timespec="seconds")
        if ttype == "interval":
            try:
                every = float(trigger.get("every") or 0)
            except Exception:
                return None
            if every <= 0:
                return None
            unit = str(trigger.get("unit") or "minutes").strip().lower()
            delta = (timedelta(hours=every) if unit.startswith("hour")
                     else timedelta(minutes=every))
            base = (_parse_iso(task.get("last_run"))
                    or _parse_iso(task.get("created_at")) or now)
            nxt = base + delta
            # Never schedule in the past: advance in whole steps (capped so
            # a task created months ago does not loop forever).
            for _ in range(10000):
                if nxt > now:
                    break
                nxt += delta
            return nxt.isoformat(timespec="seconds")
        return None
    except Exception:
        return None


# ── task normalisation ───────────────────────────────────────────────────────

def _normalise_task(raw: dict, task_id: str | None = None) -> dict | None:
    """Shape a user-supplied dict into a stored task. None when unusable."""
    try:
        raw = _as_dict(raw)
        name = str(raw.get("name") or "").strip()
        trigger = _as_dict(raw.get("trigger"))
        steps = [_as_dict(s) for s in _as_list(raw.get("steps"))
                 if isinstance(s, dict) and str(s.get("tool") or "").strip()]
        if not name or not trigger or not steps:
            return None
        task = {
            "id": task_id or str(raw.get("id") or "").strip()
                  or uuid.uuid4().hex[:12],
            "name": name,
            "enabled": raw.get("enabled", True) not in
                       (False, 0, "0", "false", "False", "no"),
            "trigger": trigger,
            "steps": [{"tool": str(s.get("tool")).strip(),
                       "args": _as_dict(s.get("args"))} for s in steps],
            "condition": _as_dict(raw.get("condition"))
                         if raw.get("condition") is not None else None,
            "created_at": str(raw.get("created_at") or _now_iso()),
            "last_run": raw.get("last_run"),
            "next_run": raw.get("next_run"),
        }
        if raw.get("description"):
            task["description"] = str(raw.get("description"))
        task["next_run"] = compute_next_run(task)
        return task
    except Exception:
        return None


# ── templates ────────────────────────────────────────────────────────────────
# Every template is a REAL, enabled task the user can edit afterwards.
# Placeholder values are labelled [EDIT ...] and explained in "description".

def _workspace_default() -> str:
    """The Mark-LVII folder, for template descriptions that name a path."""
    try:
        from pathlib import Path
        return str(Path(__file__).resolve().parent.parent)
    except Exception:
        return "the Mark-LVII folder"


TEMPLATES: dict[str, dict] = {
    "morning_briefing": {
        "name": "Morning briefing",
        "description": (
            "Daily 07:50 — weather + today's top news. "
            "Edit the city in the weather step if Kolkata is not home."
        ),
        "trigger": {"type": "time", "kind": "daily", "time": "07:50"},
        "steps": [
            {"tool": "weather_report",
             "args": {"city": "Kolkata", "time": "today"}},
            {"tool": "web_search",
             "args": {"query": "top news today", "mode": "news"}},
        ],
    },
    "daily_backup": {
        "name": "Daily backup",
        "description": (
            "Daily 02:00 — saves a backup note to Google Drive. HONEST LIMIT: "
            "drive_upload only uploads a TEXT file (filename + content) — it "
            "cannot upload a whole folder, so this template saves a text "
            "backup note. Edit the content below, or swap the step for a "
            "file step once a folder-upload tool exists. Workspace folder: "
            + _workspace_default()
        ),
        "trigger": {"type": "time", "kind": "daily", "time": "02:00"},
        "steps": [
            {"tool": "drive_upload",
             "args": {"filename": "mark-lvii-daily-backup.txt",
                      "content": "[EDIT: paste the text to back up here — "
                                 "drive_upload takes text content, not a folder]"}},
        ],
    },
    "evening_upload": {
        "name": "Evening upload",
        "description": (
            "Daily 18:00 — uploads today's video to Facebook + Instagram. "
            "EDIT the file_path in both steps to today's real video file "
            "before the first run (e.g. C:/Videos/todays-video.mp4)."
        ),
        "trigger": {"type": "time", "kind": "daily", "time": "18:00"},
        "steps": [
            {"tool": "facebook_upload_video",
             "args": {"file_path": "C:/Videos/todays-video.mp4",
                      "title": "Today's video",
                      "description": ""}},
            {"tool": "instagram_upload_video",
             "args": {"file_path_or_url": "C:/Videos/todays-video.mp4",
                      "caption": "Today's video"}},
        ],
    },
    "weekly_drive_sync": {
        "name": "Weekly Drive sync",
        "description": (
            "Every Monday 09:00 — lists Drive, then uploads a weekly sync "
            "note. HONEST LIMIT: drive_upload only uploads a TEXT file "
            "(filename + content), so edit the content step with what should "
            "be synced; it cannot upload a whole folder."
        ),
        "trigger": {"type": "time", "kind": "weekly",
                    "weekday": 0, "time": "09:00"},
        "steps": [
            {"tool": "drive_list", "args": {}},
            {"tool": "drive_upload",
             "args": {"filename": "weekly-sync-note.txt",
                      "content": "[EDIT: what to sync this week]"}},
        ],
    },
    "social_post_fixed_time": {
        "name": "Social post (fixed time)",
        "description": (
            "Daily 12:00 — posts to Facebook + Instagram. EDIT the message "
            "and caption before the first run. NOTE: instagram_post needs a "
            "PUBLIC image URL — a local file will not work, so replace the "
            "example URL with a real public one."
        ),
        "trigger": {"type": "time", "kind": "daily", "time": "12:00"},
        "steps": [
            {"tool": "facebook_post",
             "args": {"message": "[EDIT: your Facebook post text]"}},
            {"tool": "instagram_post",
             "args": {"image_url": "https://example.com/your-image.jpg",
                      "caption": "[EDIT: your caption]"}},
        ],
    },
}


# ── conditions ("only if") ───────────────────────────────────────────────────

def check_condition(condition) -> tuple[bool, str]:
    """(passes, note). Unknown types pass — they never block a task."""
    try:
        cond = _as_dict(condition)
        if not cond:
            return True, ""
        ctype = str(cond.get("type") or "").strip().lower()
        if ctype == "online":
            try:
                sock = socket.create_connection(("8.8.8.8", 53), timeout=2)
                sock.close()
                return True, ""
            except Exception:
                return False, "offline — no route to 8.8.8.8:53"
        if ctype == "idle":
            try:
                minutes = float(cond.get("minutes") or 0)
            except Exception:
                minutes = 0.0
            if sys.platform != "win32":
                return True, "idle check is Windows-only — skipped here"
            try:
                class _LASTINPUTINFO(ctypes.Structure):
                    _fields_ = [("cbSize", ctypes.c_uint),
                                ("dwTime", ctypes.c_uint)]
                info = _LASTINPUTINFO()
                info.cbSize = ctypes.sizeof(info)
                if not ctypes.windll.user32.GetLastInputInfo(
                        ctypes.byref(info)):
                    return True, "idle check unavailable — skipped"
                idle_ms = ctypes.windll.kernel32.GetTickCount() - info.dwTime
                if idle_ms >= minutes * 60 * 1000:
                    return True, ""
                return False, (f"not idle — last input "
                               f"{idle_ms // 60000} min ago "
                               f"(needs {minutes:g} min)")
            except Exception:
                return True, "idle check unavailable — skipped"
        return True, f"unknown condition {ctype!r} — ignored"
    except Exception:
        return True, "condition check failed — ignored"


# ── the engine ───────────────────────────────────────────────────────────────

class AutomationEngine:
    """Scheduled / triggered tasks. Thread-safe; never raises out of a
    public method. One lock guards state + the in-progress set."""

    def __init__(self):
        self._lock = threading.RLock()
        self._runner = None
        self._tasks: list[dict] = []
        self._history: list[dict] = []
        self._in_progress: set[str] = set()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._load()

    # ── persistence ──
    def _load(self) -> None:
        try:
            from memory.config_manager import get_plugin_config
            data = get_plugin_config(_NAMESPACE) or {}
            tasks = [_normalise_task(t) for t in _as_list(data.get("tasks"))]
            # _normalise_task recomputes next_run from "now", which would
            # wrongly revive a once-off task whose time passed — keep the
            # stored next_run when the stored task already had one computed
            # and the trigger is a once-off time in the past.
            self._tasks = []
            for raw, norm in zip(_as_list(data.get("tasks")), tasks):
                if norm is None:
                    continue
                stored_next = _as_dict(raw).get("next_run")
                trig = _as_dict(raw).get("trigger")
                if (str(trig.get("type") or "").lower() == "time"
                        and str(trig.get("kind") or "").lower() == "once"
                        and stored_next is None):
                    norm["next_run"] = None
                self._tasks.append(norm)
            self._history = [_as_dict(h) for h in
                             _as_list(data.get("history"))][- _HISTORY_CAP:]
        except Exception:
            self._tasks = []
            self._history = []

    def _save(self) -> None:
        try:
            from memory.config_manager import save_plugin_config
            save_plugin_config(_NAMESPACE, {
                "tasks": self._tasks,
                "history": self._history[-_HISTORY_CAP:],
            })
        except Exception:
            pass

    # ── runner ──
    def set_tool_runner(self, fn) -> None:
        """fn(tool_name, args_dict) -> str. Registered by main.py."""
        try:
            with self._lock:
                self._runner = fn if callable(fn) else None
        except Exception:
            pass

    def get_tool_runner(self):
        """The runner registered by main.py (or None if unwired). Lets
        orchestrating tools (e.g. parallel_run) run any tool, inline ones
        included, without touching main.py."""
        try:
            with self._lock:
                return self._runner
        except Exception:
            return None

    # ── task CRUD ──
    def list_tasks(self) -> list[dict]:
        try:
            with self._lock:
                return [dict(t) for t in self._tasks]
        except Exception:
            return []

    def get_task(self, task_id: str) -> dict | None:
        try:
            task_id = str(task_id or "").strip()
            with self._lock:
                for t in self._tasks:
                    if t.get("id") == task_id:
                        return dict(t)
        except Exception:
            pass
        return None

    def create_task(self, raw: dict) -> str:
        """Create a task from a dict. Returns the new id, or '' when the
        dict is unusable (no name / trigger / steps)."""
        try:
            task = _normalise_task(raw or {})
            if task is None:
                return ""
            with self._lock:
                if any(t.get("id") == task["id"] for t in self._tasks):
                    task["id"] = uuid.uuid4().hex[:12]
                self._tasks.append(task)
                self._save()
            return task["id"]
        except Exception:
            return ""

    def update_task(self, task_id: str, patch: dict) -> bool:
        try:
            task_id = str(task_id or "").strip()
            patch = _as_dict(patch)
            if not task_id or not patch:
                return False
            with self._lock:
                for i, t in enumerate(self._tasks):
                    if t.get("id") != task_id:
                        continue
                    merged = dict(t)
                    for key in ("name", "enabled", "trigger", "steps",
                                "condition", "description"):
                        if key in patch:
                            merged[key] = patch[key]
                    norm = _normalise_task(merged, task_id=task_id)
                    if norm is None:
                        return False
                    # Keep last_run from before the edit.
                    norm["last_run"] = t.get("last_run")
                    self._tasks[i] = norm
                    self._save()
                    return True
        except Exception:
            pass
        return False

    def delete_task(self, task_id: str) -> bool:
        try:
            task_id = str(task_id or "").strip()
            with self._lock:
                before = len(self._tasks)
                self._tasks = [t for t in self._tasks
                               if t.get("id") != task_id]
                if len(self._tasks) == before:
                    return False
                self._save()
                return True
        except Exception:
            return False

    def set_enabled(self, task_id: str, on: bool) -> bool:
        try:
            return self.update_task(task_id, {"enabled": bool(on)})
        except Exception:
            return False

    def create_from_template(self, name: str) -> str:
        """Create a real, enabled task from a named template. '' when the
        template name is unknown."""
        try:
            key = str(name or "").strip().lower()
            tpl = TEMPLATES.get(key)
            if tpl is None:
                return ""
            return self.create_task(json.loads(json.dumps(tpl)))
        except Exception:
            return ""

    # ── history ──
    def history(self, task_id: str | None = None) -> list[dict]:
        try:
            with self._lock:
                out = [dict(h) for h in self._history]
            if task_id:
                out = [h for h in out if h.get("task_id") == task_id]
            return out
        except Exception:
            return []

    def record_external_run(self, name: str, status: str, detail: str = "",
                            executor: str = "phone") -> None:
        """Record a task completion that happened OUTSIDE this PC — e.g.
        the phone ran a scheduled task while the PC was off and reported
        it back (TASK_REPORT::). The Tasks panel shows the executor so
        nobody can mistake a phone run for a PC run. Never raises."""
        try:
            entry = {
                "task_id": f"ext-{executor}",
                "task_name": str(name or "external task")[:120],
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "duration_s": 0,
                "status": str(status or "ok"),
                "steps": [{"tool": "external", "ok": status == "ok",
                           "result": str(detail or "")[:300]}],
                "executor": str(executor or "phone"),
                "note": str(detail or "")[:300],
            }
            with self._lock:
                self._history.append(entry)
                self._history = self._history[-_HISTORY_CAP:]
                self._save()
        except Exception:
            pass

    def _record_run(self, task: dict, started: datetime, status: str,
                    steps_log: list[dict], note: str = "") -> None:
        try:
            finished = datetime.now()
            entry = {
                "task_id": task.get("id"),
                "task_name": task.get("name"),
                "started_at": started.isoformat(timespec="seconds"),
                "finished_at": finished.isoformat(timespec="seconds"),
                "duration_s": round((finished - started).total_seconds(), 1),
                "status": status,
                "steps": steps_log,
                "executor": "pc",
            }
            if note:
                entry["note"] = str(note)[:300]
            with self._lock:
                self._history.append(entry)
                self._history = self._history[-_HISTORY_CAP:]
                self._save()
        except Exception:
            pass

    # ── step execution ──
    def _run_step(self, tool: str, args: dict) -> tuple[bool, str]:
        """One step, retried once on failure. Returns (ok, result)."""
        try:
            runner = None
            with self._lock:
                runner = self._runner
            if runner is None:
                return False, _NO_RUNNER_MSG
            last = ""
            for _attempt in (1, 2):
                try:
                    result = runner(tool, dict(args or {}))
                    last = str(result if result is not None else "")
                except Exception as exc:
                    last = f"tool {tool} raised: {exc}"
                if not _is_problem(last):
                    return True, last
            return False, last
        except Exception as exc:
            return False, f"tool {tool} raised: {exc}"

    def _execute_task(self, task: dict) -> str:
        """Run one task's steps in order. Never raises. Returns a short
        result string and records the run in history."""
        started = datetime.now()
        name = str(task.get("name") or "task")
        steps_log: list[dict] = []
        try:
            ok, note = check_condition(task.get("condition"))
            if not ok:
                self._record_run(task, started, "failed", [],
                                 note=f"condition not met: {note}")
                return f"❌ {name}: skipped — condition not met ({note})"
            for step in _as_list(task.get("steps")):
                tool = str(step.get("tool") or "").strip()
                args = _as_dict(step.get("args"))
                owner = ""
                try:
                    from core.agents import REGISTRY, owner_of
                    owner = owner_of(tool)
                    if owner:
                        REGISTRY.start(
                            owner,
                            f"{tool}: {json.dumps(args)[:120]}"
                            if args else tool)
                except Exception:
                    owner = ""
                step_ok, result = self._run_step(tool, args)
                try:
                    if owner:
                        from core.agents import REGISTRY
                        pct = _parse_progress(result)
                        if pct is not None:
                            REGISTRY.progress(owner, pct)
                        if step_ok:
                            REGISTRY.done(owner, result[:300])
                        else:
                            REGISTRY.fail(owner, result[:300])
                except Exception:
                    pass
                steps_log.append({"tool": tool, "ok": bool(step_ok),
                                  "result": str(result or "")[:500]})
                if not step_ok:
                    self._record_run(task, started, "failed", steps_log)
                    self._mark_ran(task)
                    return (f"❌ {name}: step '{tool}' failed "
                            f"(retried once) — {str(result or '')[:200]}")
            self._record_run(task, started, "ok", steps_log)
            self._mark_ran(task)
            dur = (datetime.now() - started).total_seconds()
            return (f"✅ {name}: {len(steps_log)}/{len(steps_log)} steps "
                    f"done in {dur:.1f}s")
        except Exception as exc:
            try:
                self._record_run(task, started, "failed", steps_log,
                                 note=f"engine error: {exc}")
                self._mark_ran(task)
            except Exception:
                pass
            return f"❌ {name}: failed — {exc}"

    def _mark_ran(self, task: dict) -> None:
        """Update last_run / next_run after a run and persist."""
        try:
            with self._lock:
                for t in self._tasks:
                    if t.get("id") == task.get("id"):
                        t["last_run"] = _now_iso()
                        t["next_run"] = compute_next_run(t)
                        break
                self._save()
        except Exception:
            pass

    def run_task_now(self, task_id: str) -> str:
        """Run a task synchronously, right now. Never raises."""
        try:
            task_id = str(task_id or "").strip()
            task = self.get_task(task_id)
            if task is None:
                return f"No task with id {task_id}."
            with self._lock:
                if task_id in self._in_progress:
                    return f"⏳ {task.get('name')}: already running."
                self._in_progress.add(task_id)
            try:
                return self._execute_task(task)
            finally:
                with self._lock:
                    self._in_progress.discard(task_id)
        except Exception as exc:
            return f"Could not run that task: {exc}"

    # ── keyword / event triggers ──
    def check_keyword(self, text: str) -> list[dict]:
        """Enabled tasks whose keyword phrase appears in `text`
        (case-insensitive substring). Returns the tasks — it does not run
        them; the caller runs each with run_task_now(). Never raises."""
        try:
            hay = str(text or "").lower()
            if not hay:
                return []
            out = []
            with self._lock:
                tasks = [dict(t) for t in self._tasks]
            for t in tasks:
                if not t.get("enabled"):
                    continue
                trig = _as_dict(t.get("trigger"))
                if str(trig.get("type") or "").strip().lower() != "keyword":
                    continue
                phrase = str(trig.get("phrase") or "").strip().lower()
                if phrase and phrase in hay:
                    out.append(t)
            return out
        except Exception:
            return []

    def fire_event(self, name: str, payload=None) -> list[dict]:
        """Run every enabled task whose event trigger matches `name`.
        Returns the triggered tasks (each already run, synchronously).
        The payload is accepted for future step use and recorded nowhere
        sensitive. Never raises."""
        try:
            name = str(name or "").strip()
            if not name:
                return []
            with self._lock:
                tasks = [dict(t) for t in self._tasks]
            fired = []
            for t in tasks:
                if not t.get("enabled"):
                    continue
                trig = _as_dict(t.get("trigger"))
                if str(trig.get("type") or "").strip().lower() != "event":
                    continue
                if str(trig.get("name") or "").strip() != name:
                    continue
                fired.append(t)
            for t in fired:
                self.run_task_now(str(t.get("id") or ""))
            return fired
        except Exception:
            return []

    # ── scheduler ──
    def start(self) -> bool:
        """Start the daemon scheduler thread. Idempotent — a second call
        while it is running does nothing and returns True."""
        try:
            with self._lock:
                if self._thread is not None and self._thread.is_alive():
                    return True
                self._stop.clear()
                self._thread = threading.Thread(
                    target=self._scheduler_loop, daemon=True,
                    name="automation-scheduler")
                self._thread.start()
                return True
        except Exception:
            return False

    def stop(self) -> None:
        """Stop the scheduler (for tests / shutdown). Never raises."""
        try:
            self._stop.set()
            thread = None
            with self._lock:
                thread = self._thread
            if thread is not None and thread.is_alive():
                thread.join(timeout=5)
            with self._lock:
                self._thread = None
        except Exception:
            pass

    @property
    def running(self) -> bool:
        try:
            return self._thread is not None and self._thread.is_alive()
        except Exception:
            return False

    def _scheduler_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._check_due()
            except Exception:
                pass
            self._stop.wait(_CHECK_INTERVAL_S)

    def _check_due(self) -> None:
        """Run every enabled task whose next_run has arrived. Each run goes
        on its own daemon thread so one slow tool never stalls the rest."""
        try:
            now = datetime.now()
            due: list[dict] = []
            with self._lock:
                for t in self._tasks:
                    if not t.get("enabled"):
                        continue
                    nxt = _parse_iso(t.get("next_run"))
                    if nxt is not None and nxt <= now:
                        if t.get("id") not in self._in_progress:
                            due.append(dict(t))
            for t in due:
                tid = str(t.get("id") or "")
                with self._lock:
                    if tid in self._in_progress:
                        continue
                    self._in_progress.add(tid)

                def _run_one(task=t, task_id=tid):
                    try:
                        self._execute_task(task)
                    finally:
                        with self._lock:
                            self._in_progress.discard(task_id)

                threading.Thread(target=_run_one, daemon=True,
                                 name=f"automation-run-{tid}").start()
        except Exception:
            pass


# The one engine the app, the plugin and the dashboard share.
ENGINE = AutomationEngine()
