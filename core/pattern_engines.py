"""core/pattern_engines.py — the 20 PATTERN ENGINES (Phase 2).

Each of the 20 patterns in the 23,720,000-feature registry
(data/feature_structure.py) gets one engine function here. An engine is a
REAL working implementation that delegates to the capability that already
exists in Mark-LVII — the automation scheduler, the agent router, the
dashboard/live status, the file tools, Gemini, the Jarvis Link relay, the
action queue, the security flags — never a stub that just returns the
pattern name.

    run_pattern(pattern, record, player) -> str | None

`pattern` is the pattern TEMPLATE name from the record, e.g. "Auto {t}".
Returns a short result string when the engine handled the record, or
None when it cannot handle it — the caller (plugins/jarvis_features.py)
then falls back to its existing direct dispatch. An engine never raises
and never fakes success: no runner / no key / no phone / no history all
produce an honest sentence, not a made-up "done".

Two patterns had no existing capability, so they are implemented here,
small and honest:
  * Family sharing — a member list in config_manager's "family"
    namespace (add / list / remove member + share a note/file with a
    member, per-member visibility flag).
  * Widgets — a registry of the existing HUD panels (Agents, Automation,
    Main Agent, Features), each with live data from REGISTRY / ENGINE /
    mark_status; a listing plus a per-widget snapshot.

Rules, same as everywhere in this project:
  * stdlib + existing project modules only; no Qt (engines run on worker
    threads); nothing here ever raises.
  * Settings/keys go through memory/config_manager.py, never by writing
    config/api_keys.json directly.
  * `player` may be None (tests, phone dashboard). When a runner is
    needed: player.run_tool first, else the automation engine's runner
    (ENGINE.get_tool_runner()); when neither is wired the engine says
    so instead of pretending.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------
# Pattern templates (exact strings from data/feature_structure.py).
# --------------------------------------------------------------------------
PATTERNS = [
    "Auto {t}",
    "Voice control for {t}",
    "Live dashboard for {t}",
    "Smart scheduler for {t}",
    "One-click share for {t}",
    "AI summary for {t}",
    "Search & history for {t}",
    "Auto backup for {t}",
    "Predictive {t}",
    "Remote control for {t}",
    "Templates for {t}",
    "Bulk actions for {t}",
    "Offline mode for {t}",
    "Multi-device sync for {t}",
    "Alerts & reminders for {t}",
    "Quick actions for {t}",
    "Privacy lock for {t}",
    "Export & reports for {t}",
    "Family sharing for {t}",
    "Widgets for {t}",
]

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_RENDER_DASHBOARD_URL = "https://mark-lvii-dashboard.onrender.com"
_LOCAL_DASHBOARD_URL = "https://localhost:8000"

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


# --------------------------------------------------------------------------
# Small shared helpers (never raise).
# --------------------------------------------------------------------------
def _rec(record) -> dict:
    return record if isinstance(record, dict) else {}


def _tool(record) -> str:
    return str(_rec(record).get("tool") or "").strip()


def _args(record) -> dict:
    args = _rec(record).get("args")
    return dict(args) if isinstance(args, dict) else {}


def _target(record) -> str:
    return str(_rec(record).get("target") or "").strip()


def _name(record) -> str:
    return str(_rec(record).get("name") or _target(record)).strip()


def _runner(player):
    """Best available tool runner: player.run_tool, else the automation
    engine's runner. None when neither is wired. Never raises."""
    try:
        if player is not None:
            fn = getattr(player, "run_tool", None)
            if callable(fn):
                return fn
        from core.automation import ENGINE
        fn = ENGINE.get_tool_runner()
        return fn if callable(fn) else None
    except Exception:
        return None


def _call(runner, tool, args) -> str | None:
    """Run one tool through a runner. The result string, or None when
    there is no runner / it raised / it answered empty. Never raises."""
    if runner is None or not tool:
        return None
    try:
        result = runner(str(tool), dict(args or {}))
    except Exception:
        return None
    if result is None:
        return None
    text = str(result).strip()
    return text or None


def _arg_str(args, *keys, default=""):
    for key in keys:
        value = args.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _hhmm(args, default="09:00") -> str:
    """A HH:MM time from the record args, or the default. Never raises."""
    try:
        for key in ("time", "at_time", "daily_time"):
            value = str(args.get(key) or "").strip()
            if value and _HHMM_RE.match(value):
                return value
    except Exception:
        pass
    return default


def _link_status_line() -> str:
    """One line about the Jarvis Link phone pairing — from the already
    attached link only (core.jarvis_link.status()). "" when the link was
    never attached in this process: starting it here (attach()) would
    spin up its pairing/heartbeat loops as a side effect, so this
    deliberately does not. Never raises."""
    try:
        from core import jarvis_link
        if getattr(jarvis_link, "LINK", None) is None:
            return ""
        status = jarvis_link.status()
        if status.get("paired"):
            e2e = "E2E ON" if status.get("e2e") else "plaintext"
            return (f"📱 Jarvis Link: paired ({e2e}) • "
                    f"Mark ID: {status.get('mark_id') or '?'}")
        return "📱 Jarvis Link: phone pair kora nei — QR scan koro."
    except Exception:
        return ""


def _history_lines(limit=5) -> list[str]:
    """Recent automation runs, newest first. Never raises."""
    try:
        from core.automation import ENGINE
        lines = []
        for entry in list(ENGINE.history())[-limit:][::-1]:
            task = str(entry.get("task_name") or entry.get("task_id") or "?")
            status = str(entry.get("status") or "?")
            when = str(entry.get("started_at") or entry.get("at") or "")[:16]
            lines.append(f"• {task} — {status}" + (f" ({when})" if when else ""))
        return lines
    except Exception:
        return []


# --------------------------------------------------------------------------
# 1. Auto — automation scheduler: build a one-off task for the owning
#    tool and run it right now (ENGINE.create_task + run_task_now).
# --------------------------------------------------------------------------
def engine_auto(record, player=None):
    try:
        tool = _tool(record)
        if not tool:
            return None
        from core.automation import ENGINE
        task = {
            "name": f"Auto: {_target(record) or _name(record)}",
            "trigger": {"type": "manual"},
            "steps": [{"tool": tool, "args": _args(record)}],
            "description": f"Auto pattern for #{_rec(record).get('number')}",
        }
        task_id = ENGINE.create_task(task)
        if not task_id:
            return (f"Auto task banate parlam na — '{_name(record)}' "
                    "er jonno automation task toiri holo na.")
        return ENGINE.run_task_now(task_id)
    except Exception as exc:
        return f"Auto chalate parlam na: {exc}"


# --------------------------------------------------------------------------
# 2. Voice control — route the request to the right worker agent(s)
#    (core/agents.route), then run the owning tool — every tool is
#    voice-invokable, so routing + running is the voice path.
# --------------------------------------------------------------------------
def engine_voice_control(record, player=None):
    try:
        from core.agents import route
        text = f"{_name(record)} — {_target(record)}".strip(" —")
        routed = route(text) or []
        lines = []
        if routed:
            for entry in routed:
                lines.append(f"🎙️ {entry.get('agent_id')}: "
                             f"{entry.get('subtask')}")
        tool = _tool(record)
        if tool:
            result = _call(_runner(player), tool, _args(record))
            if result is not None:
                lines.append(result)
            elif not routed:
                return None
            else:
                lines.append(f"({tool} chalate parlam na — live session "
                             "lagbe, voice diye abar bolo.)")
        elif not routed:
            return None
        return "\n".join(lines) if lines else None
    except Exception as exc:
        return f"Voice control korte parlam na: {exc}"


# --------------------------------------------------------------------------
# 3. Live dashboard — the live panels: dashboard URLs + a live snapshot
#    (Mark status, agents, tasks, feature counts). All local, no runner.
# --------------------------------------------------------------------------
def engine_live_dashboard(record, player=None):
    try:
        lines = [f"📊 Live dashboard: {_RENDER_DASHBOARD_URL} "
                 f"(Render) • {_LOCAL_DASHBOARD_URL} (local, dashboard "
                 "server cholle)"]
        try:
            from core import mark_status
            snap = mark_status.snapshot()
            lines.append(f"Mark: {snap.get('current_task') or 'Idle'} • "
                         f"queue: {snap.get('queue_len', 0)}")
            last = str(snap.get("last_response") or "").strip()
            if last:
                lines.append(f"Last: {last[:120]}")
        except Exception:
            pass
        try:
            from core.agents import REGISTRY
            states = REGISTRY.snapshot()
            working = [s for s in states
                       if str(s.get("status") or "") == "working"]
            lines.append(f"Agents: {len(working)}/{len(states)} working"
                         + (f" — {', '.join(s.get('id', '?') for s in working)}"
                            if working else ""))
        except Exception:
            pass
        try:
            from core.automation import ENGINE
            tasks = ENGINE.list_tasks()
            enabled = [t for t in tasks if t.get("enabled", True)]
            lines.append(f"Automation: {len(enabled)}/{len(tasks)} tasks "
                         "enabled")
        except Exception:
            pass
        try:
            from core import feature_registry
            counts = feature_registry.counts()
            lines.append(f"Features: {counts.get('WORKING', 0)} WORKING / "
                         f"{counts.get('total', 23720000)} total")
        except Exception:
            pass
        target = _target(record)
        if target:
            lines.append(f"Feature: {_name(record)}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Live dashboard dekhate parlam na: {exc}"


# --------------------------------------------------------------------------
# 4. Smart scheduler — create a scheduled task for the owning tool
#    (time daily / interval trigger from the record args).
# --------------------------------------------------------------------------
def engine_smart_scheduler(record, player=None):
    try:
        tool = _tool(record)
        if not tool:
            return None
        args = _args(record)
        every = None
        for key in ("interval_minutes", "every_minutes", "every"):
            try:
                value = float(args.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value and value > 0:
                every = value
                break
        if every:
            trigger = {"type": "interval", "every": every,
                       "unit": "minutes"}
            when = f"proti {int(every)} minute"
        else:
            trigger = {"type": "time", "kind": "daily",
                       "time": _hhmm(args)}
            when = f"protidin {_hhmm(args)}"
        from core.automation import ENGINE
        task_id = ENGINE.create_task({
            "name": f"Scheduled: {_target(record) or _name(record)}",
            "trigger": trigger,
            "steps": [{"tool": tool, "args": args}],
            "description": f"Smart scheduler for #{_rec(record).get('number')}",
        })
        if not task_id:
            return ("Scheduler-e task banate parlam na — "
                    f"'{_name(record)}' schedule holo na.")
        task = ENGINE.get_task(task_id) or {}
        nxt = str(task.get("next_run") or "").replace("T", " ")[:16]
        return (f"⏰ Schedule korlam: {_name(record)} — {when}"
                + (f" (next: {nxt})" if nxt else "")
                + f" [task {task_id}]")
    except Exception as exc:
        return f"Schedule korte parlam na: {exc}"


# --------------------------------------------------------------------------
# 5. One-click share — share the owning tool's thing: a file to the phone
#    (phone_send_file), a Drive share link (drive_share), or the phone
#    screen (phone_screen).
# --------------------------------------------------------------------------
def engine_one_click_share(record, player=None):
    try:
        tool = _tool(record)
        args = _args(record)
        runner = _runner(player)
        ref = _arg_str(args, "file", "path", "file_path", "file_path_or_url")
        if tool == "phone_send_file" or (ref and tool in ("", "phone_send_file")):
            result = _call(runner, "phone_send_file",
                           dict(args, **({"file": ref} if ref else {})))
            if result is not None:
                return result
            return ("Phone-e file pathate parlam na — live session lagbe "
                    "(phone_send_file).")
        if ref:
            result = _call(runner, "files_drive_cloud",
                           {"action": "share_link", "file": ref})
            if result is not None:
                return result
            try:
                from core import cat06_files
                return cat06_files.drive_share(ref)
            except Exception:
                pass
        if tool == "phone_screen":
            result = _call(runner, tool, args)
            if result is not None:
                return result
            return ("Phone screen share korte parlam na — live session "
                    "lagbe (phone_screen).")
        if tool:
            result = _call(runner, tool, args)
            if result is not None:
                return result
        return None
    except Exception as exc:
        return f"Share korte parlam na: {exc}"


# --------------------------------------------------------------------------
# 6. AI summary — Gemini summarises the feature (its description, plus
#    any text the record args carry).
# --------------------------------------------------------------------------
def engine_ai_summary(record, player=None):
    try:
        from core import gemini
        args = _args(record)
        extra = _arg_str(args, "text", "content", "message", "query")
        subject = f"{_name(record)} — {str(_rec(record).get('description') or '')}"
        if extra:
            subject += f"\nText: {extra[:2000]}"
        summary = gemini.text(
            "Summarise this in 2-3 short lines, plain language, no "
            f"markdown headings:\n{subject}",
            tier=gemini.FAST)
        if summary and str(summary).strip():
            return str(summary).strip()
        return ("Summary korte parlam na — Gemini theke kono uttor pelam "
                "na. Gemini key / Settings check koro.")
    except Exception:
        return None


# --------------------------------------------------------------------------
# 7. Search & history — smart file search (core/cat06_files) + the
#    automation run history. Both local, no runner needed.
# --------------------------------------------------------------------------
def engine_search_history(record, player=None):
    try:
        lines = []
        query = _target(record)
        try:
            from core import cat06_files
            found = cat06_files.smart_search(_PROJECT_ROOT, query)
            if found:
                lines.append(str(found).strip())
        except Exception:
            pass
        hist = _history_lines(limit=5)
        if hist:
            lines.append("Automation history (recent):")
            lines.extend(hist)
        try:
            from core import cat06_files
            file_hist = cat06_files.read_history(limit=5)
            if file_hist:
                lines.append("File history (recent):")
                for entry in file_hist[-5:][::-1]:
                    lines.append(f"• {entry.get('operation', '?')} — "
                                 f"{str(entry.get('detail', ''))[:100]}")
        except Exception:
            pass
        if not lines:
            return ("Kono history pelam na — ekhono kichhu run ba file "
                    "operation hoy ni.")
        return "\n".join(lines)
    except Exception as exc:
        return f"Search/history dekhate parlam na: {exc}"


# --------------------------------------------------------------------------
# 8. Auto backup — create a daily backup task (files_drive_cloud
#    run_backup on the record's folder, else the project folder).
# --------------------------------------------------------------------------
def engine_auto_backup(record, player=None):
    try:
        args = _args(record)
        folder = _arg_str(args, "folder", "path", "file",
                          default=str(_PROJECT_ROOT))
        from core.automation import ENGINE
        task_id = ENGINE.create_task({
            "name": f"Auto backup: {_target(record) or _name(record)}",
            "trigger": {"type": "time", "kind": "daily",
                        "time": _hhmm(args, default="02:00")},
            "steps": [{"tool": "files_drive_cloud",
                       "args": {"action": "run_backup", "folder": folder}}],
            "description": f"Auto backup for #{_rec(record).get('number')}",
        })
        if not task_id:
            return ("Auto backup task banate parlam na — "
                    f"'{_name(record)}' backup schedule holo na.")
        task = ENGINE.get_task(task_id) or {}
        nxt = str(task.get("next_run") or "").replace("T", " ")[:16]
        return (f"💾 Auto backup schedule korlam: {folder}"
                + (f" — protidin {_hhmm(args, default='02:00')}"
                   + (f" (next: {nxt})" if nxt else ""))
                + f" [task {task_id}]")
    except Exception as exc:
        return f"Auto backup korte parlam na: {exc}"


# --------------------------------------------------------------------------
# 9. Predictive — what to do next, from automation history: the
#    voice_tools suggest_next action when a runner is wired, else the
#    same count done locally over ENGINE.history().
# --------------------------------------------------------------------------
def engine_predictive(record, player=None):
    try:
        runner = _runner(player)
        if runner is not None:
            result = _call(runner, "voice_tools",
                           {"action": "suggest_next"})
            if result is not None:
                return result
        from core.automation import ENGINE
        counts: dict[str, int] = {}
        for entry in ENGINE.history():
            for step in (entry.get("steps") or []):
                tool = str((step or {}).get("tool") or "").strip()
                if tool:
                    counts[tool] = counts.get(tool, 0) + 1
        if not counts:
            return ("Predict korte parlam na — ekhono kono automation "
                    "history nei, tai next step bojha jachhe na.")
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        lines = ["Erpor ja korte paro (ager run history theke):"]
        for tool, n in top:
            lines.append(f"• {tool} — {n} bar run hoyeche")
        return "\n".join(lines)
    except Exception as exc:
        return f"Predict korte parlam na: {exc}"


# --------------------------------------------------------------------------
# 10. Remote control — Jarvis Link relay: phone tools run straight
#     through the runner (phone_command / phone_open_app / ...); anything
#     else is queued in the action queue, which is exactly how the
#     dashboard / HUD sends remote commands to Mark.
# --------------------------------------------------------------------------
def engine_remote_control(record, player=None):
    try:
        tool = _tool(record)
        args = _args(record)
        lines = []
        status = _link_status_line()
        if status:
            lines.append(status)
        if not tool:
            if lines:
                return "\n".join(lines)
            return None
        runner = _runner(player)
        if tool.startswith("phone_") and runner is not None:
            result = _call(runner, tool, args)
            if result is not None:
                lines.append(result)
                return "\n".join(lines)
            lines.append(f"Phone-e '{tool}' chalate parlam na — live "
                         "session lagbe.")
            return "\n".join(lines)
        from core import action_queue
        entry_id = action_queue.enqueue(tool, args)
        if not entry_id:
            return ("Remote queue-e dite parlam na — queue bhora ba "
                    f"tool-ta khali ('{tool}').")
        lines.append(f"📡 Remote control: '{tool}' queue-e dilam "
                     f"(id {entry_id}) — Mark chalabe, dashboard-e dekhte "
                     f"pabe. Pending: {action_queue.pending_count()}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Remote control korte parlam na: {exc}"


# --------------------------------------------------------------------------
# 11. Templates — create a real task from a named automation template
#     (ENGINE.create_from_template). The template is picked from the
#     record args, else from the target's keywords.
# --------------------------------------------------------------------------
_TEMPLATE_KEYWORDS = (
    ("morning", "morning_briefing"),
    ("briefing", "morning_briefing"),
    ("backup", "daily_backup"),
    ("evening", "evening_upload"),
    ("upload", "evening_upload"),
    ("drive sync", "weekly_drive_sync"),
    ("sync", "weekly_drive_sync"),
    ("social post", "social_post_fixed_time"),
    ("post", "social_post_fixed_time"),
)


def engine_templates(record, player=None):
    try:
        args = _args(record)
        name = _arg_str(args, "template", "template_name").lower()
        if not name:
            low = f"{_target(record)} {_name(record)}".lower()
            for keyword, tpl in _TEMPLATE_KEYWORDS:
                if keyword in low:
                    name = tpl
                    break
        if not name:
            return None
        from core.automation import ENGINE
        task_id = ENGINE.create_from_template(name)
        if not task_id:
            return (f"Template '{name}' pelam na — ei template diye "
                    "task banano gelo na.")
        task = ENGINE.get_task(task_id) or {}
        return (f"📋 Template '{name}' theke task banlam: "
                f"'{task.get('name') or name}' [task {task_id}]")
    except Exception as exc:
        return f"Template theke task banate parlam na: {exc}"


# --------------------------------------------------------------------------
# 12. Bulk actions — batch file ops (batch_rename / organize_folder)
#     through the files tool, or background_tasks for a parallel batch.
# --------------------------------------------------------------------------
def engine_bulk_actions(record, player=None):
    try:
        tool = _tool(record)
        args = _args(record)
        runner = _runner(player)
        if tool == "background_tasks":
            result = _call(runner, tool, args)
            if result is not None:
                return result
            return None
        folder = _arg_str(args, "folder", "path")
        pattern = _arg_str(args, "pattern", "rename_pattern")
        if folder and runner is not None:
            if pattern:
                result = _call(runner, "files_drive_cloud",
                               {"action": "batch_rename", "folder": folder,
                                "pattern": pattern})
            else:
                result = _call(runner, "files_drive_cloud",
                               {"action": "organize_folder",
                                "folder": folder})
            if result is not None:
                return result
        return None
    except Exception as exc:
        return f"Bulk action korte parlam na: {exc}"


# --------------------------------------------------------------------------
# 13. Offline mode — the offline cache (core/cat06_files): add / list /
#     remove files, all local, no runner needed.
# --------------------------------------------------------------------------
def engine_offline_mode(record, player=None):
    try:
        from core import cat06_files
        args = _args(record)
        mode = _arg_str(args, "mode", "action", default="list").lower()
        ref = _arg_str(args, "file", "path", "name")
        if mode in ("add", "cache") and ref:
            return cat06_files.cache_add(Path(ref).expanduser())
        if mode in ("remove", "delete") and ref:
            return cat06_files.cache_remove(ref)
        if mode == "add" and not ref:
            return ("Offline cache-e ki file rakhbo bolo — file path dao "
                    "(mode=add, file=<path>).")
        return cat06_files.cache_list()
    except Exception as exc:
        return f"Offline cache korte parlam na: {exc}"


# --------------------------------------------------------------------------
# 14. Multi-device sync — file transfer to the phone when a runner is
#     wired, else a live sync status (Jarvis Link pairing + queue).
# --------------------------------------------------------------------------
def engine_multi_device_sync(record, player=None):
    try:
        tool = _tool(record)
        args = _args(record)
        runner = _runner(player)
        ref = _arg_str(args, "file", "path", "file_path")
        if tool == "phone_send_file" and runner is not None:
            result = _call(runner, "phone_send_file",
                           dict(args, **({"file": ref} if ref else {})))
            if result is not None:
                return result
        if ref and runner is not None:
            result = _call(runner, "phone_send_file",
                           {"file": ref})
            if result is not None:
                return result
        lines = []
        status = _link_status_line()
        if status:
            lines.append(status)
        try:
            from core import action_queue
            lines.append(f"Sync queue: {action_queue.pending_count()} "
                         "pending action")
        except Exception:
            pass
        lines.append("Clipboard sync: phone <-> PC — computer_control "
                     "(clipboard get/paste) diye chole, live session-e.")
        if not lines:
            return None
        if tool == "phone_send_file" and runner is None:
            lines.append("File pathate live session lagbe "
                         "(phone_send_file).")
        return "\n".join(lines)
    except Exception as exc:
        return f"Multi-device sync korte parlam na: {exc}"


# --------------------------------------------------------------------------
# 15. Alerts & reminders — create a scheduled reminder task (the owning
#     tool, else the reminder action) at the record's time.
# --------------------------------------------------------------------------
def engine_alerts_reminders(record, player=None):
    try:
        tool = _tool(record) or "reminder"
        args = dict(_args(record))
        when = _hhmm(args)
        step_args = dict(args)
        if tool == "reminder":
            step_args.setdefault("message",
                                 _target(record) or _name(record))
            step_args.setdefault("time", when)
            step_args.setdefault("date",
                                datetime.now().strftime("%Y-%m-%d"))
        from core.automation import ENGINE
        task_id = ENGINE.create_task({
            "name": f"Reminder: {_target(record) or _name(record)}",
            "trigger": {"type": "time", "kind": "daily", "time": when},
            "steps": [{"tool": tool, "args": step_args}],
            "description": f"Alerts & reminders for "
                           f"#{_rec(record).get('number')}",
        })
        if not task_id:
            return ("Reminder task banate parlam na — "
                    f"'{_name(record)}' remind korano holo na.")
        task = ENGINE.get_task(task_id) or {}
        nxt = str(task.get("next_run") or "").replace("T", " ")[:16]
        return (f"⏰ Reminder dilam: {_name(record)} — protidin {when}"
                + (f" (next: {nxt})" if nxt else "")
                + f" [task {task_id}]")
    except Exception as exc:
        return f"Reminder dite parlam na: {exc}"


# --------------------------------------------------------------------------
# 16. Quick actions — enqueue the owning tool in the action queue
#     (core/action_queue): the HUD/dashboard quick-action path.
# --------------------------------------------------------------------------
def engine_quick_actions(record, player=None):
    try:
        tool = _tool(record)
        if not tool:
            return None
        from core import action_queue
        entry_id = action_queue.enqueue(tool, _args(record))
        if not entry_id:
            return ("Quick action queue-e dite parlam na — queue bhora ba "
                    f"tool-ta khali ('{tool}').")
        return (f"⚡ Quick action queue-e dilam: '{tool}' "
                f"(id {entry_id}) — Mark ektu porei chalabe. "
                f"Pending: {action_queue.pending_count()}")
    except Exception as exc:
        return f"Quick action dite parlam na: {exc}"


# --------------------------------------------------------------------------
# 17. Privacy lock — guest mode / incognito flags (core/cat09_security),
#     persisted through config_manager. Default: lock ON (guest mode).
# --------------------------------------------------------------------------
def engine_privacy_lock(record, player=None):
    try:
        from core import cat09_security
        args = _args(record)
        raw = str(args.get("enabled", args.get("on", True))).strip().lower()
        on = raw not in ("false", "0", "no", "off")
        mode = _arg_str(args, "mode", default="guest").lower()
        if mode == "incognito":
            ok = cat09_security.set_incognito(on)
            state = cat09_security.incognito_enabled()
            what = "Incognito mode"
        else:
            ok = cat09_security.set_guest_mode(on)
            state = cat09_security.guest_mode_enabled()
            what = "Guest mode (privacy lock)"
        if not ok:
            return f"{what} bodlate parlam na — settings save holo na."
        return (f"🔒 {what} {'ON' if state else 'OFF'}: "
                + ("Mark ekhon locked — mutating action gulo guest mode-e "
                   "atke jabe." if state and mode != "incognito" else
                   "Incognito ON — ei session-e kono history save hobe na."
                   if state else
                   "Lock khule dilam — normal mode-e cholbe."))
    except Exception as exc:
        return f"Privacy lock korte parlam na: {exc}"


# --------------------------------------------------------------------------
# 18. Export & reports — a PDF from images (files_drive_cloud make_pdf)
#     or the end-of-day report (smartlife daily_report); without a
#     runner, a local report from automation history + tasks.
# --------------------------------------------------------------------------
def engine_export_reports(record, player=None):
    try:
        args = _args(record)
        runner = _runner(player)
        images = _arg_str(args, "images", "file", "path")
        if images and runner is not None:
            result = _call(runner, "files_drive_cloud",
                           {"action": "make_pdf", "file": images,
                            "images": images})
            if result is not None:
                return result
        if runner is not None:
            result = _call(runner, "smartlife",
                           {"action": "daily_report"})
            if result is not None:
                return result
        lines = [f"📄 Report — {_name(record)} "
                 f"(#{_rec(record).get('number')})"]
        try:
            from core.automation import ENGINE
            tasks = ENGINE.list_tasks()
            lines.append(f"Tasks: {len(tasks)} "
                         f"({len([t for t in tasks if t.get('enabled', True)])} enabled)")
        except Exception:
            pass
        hist = _history_lines(limit=5)
        if hist:
            lines.append("Recent runs:")
            lines.extend(hist)
        else:
            lines.append("Recent runs: ekhono kono run hoy ni.")
        try:
            from core import feature_registry
            counts = feature_registry.counts()
            lines.append(f"Features: {counts.get('WORKING', 0)} WORKING / "
                         f"{counts.get('total', 23720000)} total")
        except Exception:
            pass
        return "\n".join(lines)
    except Exception as exc:
        return f"Report banate parlam na: {exc}"


# --------------------------------------------------------------------------
# 19. Family sharing — NEW minimal real implementation. Members live in
#     config_manager's "family" namespace:
#       {"members": [{"name", "role", "visible", "shared": [{kind, text, at}]}]}
#     Actions (from record args): list (default) / add / remove / share.
# --------------------------------------------------------------------------
_FAMILY_NAMESPACE = "family"


def _family_load() -> dict:
    try:
        from memory.config_manager import get_plugin_config
        data = get_plugin_config(_FAMILY_NAMESPACE) or {}
        members = data.get("members")
        if not isinstance(members, list):
            members = []
        clean = []
        for m in members:
            if isinstance(m, dict) and str(m.get("name") or "").strip():
                clean.append({
                    "name": str(m["name"]).strip(),
                    "role": str(m.get("role") or "member"),
                    "visible": bool(m.get("visible", True)),
                    "shared": list(m.get("shared") or []),
                })
        return {"members": clean}
    except Exception:
        return {"members": []}


def _family_save(data: dict) -> bool:
    try:
        from memory.config_manager import save_plugin_config
        save_plugin_config(_FAMILY_NAMESPACE, {"members": data["members"]})
        return True
    except Exception:
        return False


def engine_family_sharing(record, player=None):
    try:
        args = _args(record)
        action = _arg_str(args, "action", "mode", default="list").lower()
        data = _family_load()
        members = data["members"]

        if action == "list":
            if not members:
                return ("Family-e ekhono keu nei — add korte: member-er "
                        "naam dao (action=add, member=<naam>).")
            lines = ["👨‍👩‍👧 Family members:"]
            for m in members:
                shared = len(m.get("shared") or [])
                lines.append(f"• {m['name']} ({m.get('role', 'member')}) — "
                             f"{'visible' if m.get('visible', True) else 'hidden'}"
                             + (f", {shared} shared" if shared else ""))
            return "\n".join(lines)

        if action == "add":
            name = _arg_str(args, "member", "name")
            if not name:
                return ("Family-e ka-ke add korbo? Naam dao "
                        "(action=add, member=<naam>).")
            if any(m["name"].lower() == name.lower() for m in members):
                return f"'{name}' agei family-te ache."
            role = _arg_str(args, "role", default="member")
            visible_raw = str(args.get("visible", True)).strip().lower()
            visible = visible_raw not in ("false", "0", "no", "off")
            members.append({"name": name, "role": role,
                            "visible": visible, "shared": []})
            if not _family_save(data):
                return f"'{name}'-ke add korte parlam na — save holo na."
            return f"👨‍👩‍👧 '{name}'-ke family-te add korlam ({role})."

        if action == "remove":
            name = _arg_str(args, "member", "name")
            if not name:
                return ("Family theke ka-ke sorabo? Naam dao "
                        "(action=remove, member=<naam>).")
            before = len(members)
            members[:] = [m for m in members
                          if m["name"].lower() != name.lower()]
            if len(members) == before:
                return f"'{name}' family-te pelam na."
            if not _family_save(data):
                return f"'{name}'-ke sorate parlam na — save holo na."
            return f"'{name}'-ke family theke soralam."

        if action == "share":
            name = _arg_str(args, "member", "name")
            note = _arg_str(args, "note", "text", "message", "file")
            if not name or not note:
                return ("Share korte member-er naam ar note/file dao "
                        "(action=share, member=<naam>, note=<lekha>).")
            for m in members:
                if m["name"].lower() == name.lower():
                    if not m.get("visible", True):
                        return (f"'{name}' hidden — share korar age "
                                "visible koro.")
                    kind = "file" if _arg_str(args, "file") else "note"
                    m.setdefault("shared", []).append({
                        "kind": kind, "text": note,
                        "at": datetime.now().isoformat(timespec="seconds"),
                    })
                    if not _family_save(data):
                        return "Share korte parlam na — save holo na."
                    return (f"📤 '{name}'-er sathe share korlam "
                            f"({kind}): {note[:120]}")
            return f"'{name}' family-te pelam na — age add koro."

        return ("Family sharing action bujhlam na — use koro: list, add, "
                "remove, share.")
    except Exception as exc:
        return f"Family sharing korte parlam na: {exc}"


# --------------------------------------------------------------------------
# 20. Widgets — NEW minimal real implementation. A registry of the
#     existing HUD panels; each widget's snapshot is live data from
#     REGISTRY / ENGINE / mark_status / feature_registry. Listing by
#     default, or one widget's snapshot when args carry "widget".
# --------------------------------------------------------------------------
def _widget_agents() -> str:
    from core.agents import REGISTRY
    states = REGISTRY.snapshot()
    working = [s for s in states if str(s.get("status") or "") == "working"]
    lines = [f"🧠 Agents widget — {len(working)}/{len(states)} working:"]
    for s in states[:20]:
        task = str(s.get("task") or "")[:60]
        lines.append(f"• {s.get('id', '?')}: {s.get('status', '?')}"
                     + (f" — {task}" if task else ""))
    return "\n".join(lines)


def _widget_automation() -> str:
    from core.automation import ENGINE
    tasks = ENGINE.list_tasks()
    lines = [f"⏰ Automation widget — {len(tasks)} tasks:"]
    for t in tasks[:10]:
        nxt = str(t.get("next_run") or "")[:16].replace("T", " ")
        lines.append(f"• {t.get('name', '?')} "
                     f"({'on' if t.get('enabled', True) else 'off'})"
                     + (f" — next {nxt}" if nxt else ""))
    if not tasks:
        lines.append("• kono task nei")
    return "\n".join(lines)


def _widget_main_agent() -> str:
    from core import mark_status
    snap = mark_status.snapshot()
    lines = ["🤖 Main Agent widget:"]
    lines.append(f"• Task: {snap.get('current_task') or 'Idle'}")
    lines.append(f"• Queue: {snap.get('queue_len', 0)} pending")
    last = str(snap.get("last_response") or "").strip()
    if last:
        lines.append(f"• Last: {last[:120]}")
    return "\n".join(lines)


def _widget_features() -> str:
    from core import feature_registry
    counts = feature_registry.counts()
    lines = ["📋 Features widget:"]
    lines.append(f"• Total: {counts.get('total', 23720000)}")
    lines.append(f"• WORKING: {counts.get('WORKING', 0)} | "
                 f"NEEDS-KEY: {counts.get('NEEDS-KEY', 0)} | "
                 f"NEEDS-DEVICE: {counts.get('NEEDS-DEVICE', 0)} | "
                 f"PLANNED: {counts.get('PLANNED', 0)}")
    return "\n".join(lines)


WIDGETS = {
    "agents": ("Agents — live office panel", _widget_agents),
    "automation": ("Automation — scheduled tasks", _widget_automation),
    "main_agent": ("Main Agent — Mark status", _widget_main_agent),
    "features": ("Features — 23,720,000 registry", _widget_features),
}


def engine_widgets(record, player=None):
    try:
        args = _args(record)
        wanted = _arg_str(args, "widget", "name").lower()
        if wanted:
            entry = WIDGETS.get(wanted)
            if entry is None:
                known = ", ".join(sorted(WIDGETS))
                return (f"Widget '{wanted}' chinlam na. Available: "
                        f"{known}.")
            _title, fn = entry
            return fn()
        lines = ["🧩 Widgets (HUD panels — live data):"]
        for wid in sorted(WIDGETS):
            title, fn = WIDGETS[wid]
            try:
                snap = fn()
                first = str(snap).split("\n")[0]
            except Exception:
                first = title
            lines.append(f"• {wid}: {first}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Widgets dekhate parlam na: {exc}"


# --------------------------------------------------------------------------
# Dispatcher.
# --------------------------------------------------------------------------
_ENGINES = {
    "Auto {t}": engine_auto,
    "Voice control for {t}": engine_voice_control,
    "Live dashboard for {t}": engine_live_dashboard,
    "Smart scheduler for {t}": engine_smart_scheduler,
    "One-click share for {t}": engine_one_click_share,
    "AI summary for {t}": engine_ai_summary,
    "Search & history for {t}": engine_search_history,
    "Auto backup for {t}": engine_auto_backup,
    "Predictive {t}": engine_predictive,
    "Remote control for {t}": engine_remote_control,
    "Templates for {t}": engine_templates,
    "Bulk actions for {t}": engine_bulk_actions,
    "Offline mode for {t}": engine_offline_mode,
    "Multi-device sync for {t}": engine_multi_device_sync,
    "Alerts & reminders for {t}": engine_alerts_reminders,
    "Quick actions for {t}": engine_quick_actions,
    "Privacy lock for {t}": engine_privacy_lock,
    "Export & reports for {t}": engine_export_reports,
    "Family sharing for {t}": engine_family_sharing,
    "Widgets for {t}": engine_widgets,
}


def run_pattern(pattern, record, player=None):
    """Run one feature record through its pattern engine.

    `pattern` is the pattern template name (record["pattern"], e.g.
    "Auto {t}"). Returns a short result string when the engine handled
    the record, or None when it cannot handle it — the caller then falls
    back to its direct tool dispatch. Never raises.
    """
    try:
        tpl = str(pattern or "").strip()
        fn = _ENGINES.get(tpl)
        if fn is None:
            return None
        result = fn(_rec(record), player)
        if result is None:
            return None
        text = str(result).strip()
        return text or None
    except Exception:
        return None
