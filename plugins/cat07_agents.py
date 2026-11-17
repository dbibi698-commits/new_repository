"""plugins/cat07_agents.py — 🤖 AGENTS & AUTOMATION (Category 7, features 121-140).

One dispatcher tool, ``agents_automation``, with twelve actions — one plugin
file can only register one tool (core/plugin_loader.py reads a single PLUGIN
dict per file), so the category's twelve capabilities live here as actions,
the same shape as the ``automation`` plugin's list/create/enable/... actions.

Actions (``action`` parameter):
    parallel_run   — run several tools at once (or one by one on careful speed)
    task_queue     — list pending queued actions (core/action_queue.py)
    remind         — one-time reminder: an automation task that speaks (say_text)
    say_text       — speak text now through the live voice session
    timer          — one-time timer: an automation task that speaks when done
    todo           — todo list: add / list / done / clear (persisted in config)
    predict_next   — what to do next, from automation history + todos (Gemini)
    make_skill     — save a custom skill (name + rules + optional steps)
    run_skill      — run a stored skill's steps, in order
    skill_library  — list / run / delete stored skills
    agent_speed    — get / set the agent speed: fast (parallel) or careful
    good_morning   — create the daily morning-routine automation task

What this file does NOT duplicate (already working elsewhere):
    agents_status (plugins/jarvis_agents.py), automation (plugins/
    jarvis_automation.py — generic scheduled tasks + templates incl.
    morning_briefing), reminder (actions/reminder.py — OS Task Scheduler),
    the 7 worker agents + route() (core/agents.py), the 🤖 AGENTS / 🧠 MAIN
    AGENT live panels (gui/window.py), task notes (core/tasks/tools.py).

Rules honoured here:
    * run() never raises; every action returns a short string.
    * Tool execution goes through ENGINE.get_tool_runner() (the FULL runner
      main.py registers, inline tools included); player.run_tool is only the
      fallback when the engine runner is not wired yet.
    * Persistence only through memory/config_manager.py — namespaces
      "todos", "skills" and "agents" (speed). No secrets, no keys, nothing
      written to config/api_keys.json directly.
    * Dangerous tools (pc_power, shutdown_jarvis, app_uninstall) inside
      parallel_run / run_skill, and skill deletion, need confirm=true —
      the first call only asks, the second (after the user says yes) runs.
    * No Qt anywhere in this file (tools run on worker threads).
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timedelta

PLUGIN = {
    "name": "agents_automation",
    "description": (
        "Agents & automation helper (Category 7). Use it when the user asks "
        "for: running several tools at once (action parallel_run, with a "
        "tasks JSON list of {tool, args}); listing the pending action queue "
        "(task_queue); a reminder or a timer that speaks when it fires "
        "(remind / timer — NOT the OS-scheduler 'reminder' tool, and NOT "
        "the generic 'automation' tool for repeating scheduled tasks); "
        "speaking a short text now (say_text); a todo list (todo: add/list/"
        "done/clear); what to do next from past runs and todos (predict_next); "
        "saving a custom skill (make_skill) or listing/running/deleting "
        "stored skills (skill_library, run_skill); agent speed fast/careful "
        "(agent_speed); or a daily morning routine task (good_morning). "
        "Do NOT use this for agent status (use agents_status) or for "
        "creating generic scheduled tasks (use automation)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "parallel_run | task_queue | remind | say_text | timer | "
                    "todo | predict_next | make_skill | run_skill | "
                    "skill_library | agent_speed | good_morning"
                ),
            },
            "tasks": {
                "type": "STRING",
                "description": (
                    "parallel_run: JSON list of {\"tool\": name, \"args\": {...}} "
                    "to run. Example: '[{\"tool\": \"weather_report\", \"args\": "
                    "{\"city\": \"Kolkata\"}}]'."
                ),
            },
            "message": {
                "type": "STRING",
                "description": "remind / timer: the text to speak when it fires.",
            },
            "minutes": {
                "type": "NUMBER",
                "description": (
                    "remind / timer: in how many minutes it fires "
                    "(default remind 30, timer 10)."
                ),
            },
            "at": {
                "type": "STRING",
                "description": (
                    "remind / timer: ISO datetime to fire at instead of "
                    "minutes, e.g. '2026-11-17T15:30:00'."
                ),
            },
            "text": {
                "type": "STRING",
                "description": "say_text: the text to speak now.",
            },
            "todo_action": {
                "type": "STRING",
                "description": "todo: add | list | done | clear.",
            },
            "item": {
                "type": "STRING",
                "description": "todo add: the todo text.",
            },
            "todo_id": {
                "type": "STRING",
                "description": (
                    "todo done: the todo id (from list), its 1-based number, "
                    "or matching text."
                ),
            },
            "all": {
                "type": "BOOLEAN",
                "description": "todo clear: true = clear ALL todos, not just done ones.",
            },
            "name": {
                "type": "STRING",
                "description": "make_skill / run_skill: the skill name.",
            },
            "rules": {
                "type": "STRING",
                "description": "make_skill: what the skill does, in plain words.",
            },
            "steps": {
                "type": "STRING",
                "description": (
                    "make_skill: optional JSON list of {\"tool\": name, \"args\": "
                    "{...}} steps the skill runs."
                ),
            },
            "library_action": {
                "type": "STRING",
                "description": "skill_library: list | run | delete.",
            },
            "speed": {
                "type": "STRING",
                "description": (
                    "agent_speed: 'fast' (parallel) or 'careful' (sequential). "
                    "Omit to just read the current speed."
                ),
            },
            "time": {
                "type": "STRING",
                "description": "good_morning: daily time HH:MM (default 07:50).",
            },
            "city": {
                "type": "STRING",
                "description": "good_morning: city for the weather step (default Kolkata).",
            },
            "confirm": {
                "type": "BOOLEAN",
                "description": (
                    "Pass true ONLY after the user confirmed a dangerous step "
                    "(pc_power / shutdown_jarvis / app_uninstall inside "
                    "parallel_run or run_skill, or a skill delete). Default "
                    "false = only ask, run nothing dangerous."
                ),
            },
        },
        "required": ["action"],
    },
}

# Namespaces in plugin_config (memory/config_manager.py).
_NS_TODOS = "todos"
_NS_SKILLS = "skills"
_NS_AGENTS = "agents"          # shared with jarvis_agents.py toggles; merged, never replaced
_SPEED_KEY = "speed"
_DEFAULT_SPEED = "fast"

# Tools that are genuinely irreversible from a plugin's chair. Running one
# inside parallel_run / run_skill needs confirm=true (the app_install.py
# convention: first call only asks, second call after the user says yes runs).
_DANGEROUS = {"pc_power", "shutdown_jarvis", "app_uninstall"}

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-]{0,59}$")
_PARALLEL_TIMEOUT_S = 30.0
_MAX_PARALLEL = 5


# ── small helpers (never raise) ──────────────────────────────────────────────

def _as_bool(value, default=False) -> bool:
    try:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "y", "confirm")
        return bool(value)
    except Exception:
        return default


def _as_number(value, default):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _parse_json_list(text, default=None):
    """A JSON list, or a list passed through as-is. [] on bad input."""
    try:
        if isinstance(text, list):
            return list(text)
        if isinstance(text, str) and text.strip():
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
    except Exception:
        pass
    return list(default) if default is not None else []


def _short(text, limit=200) -> str:
    try:
        text = str(text or "").strip()
        return text if len(text) <= limit else text[:limit] + "…"
    except Exception:
        return ""


def _log(player, text: str) -> None:
    try:
        if player is not None and hasattr(player, "write_log"):
            player.write_log(text)
    except Exception:
        pass


def _runner(player):
    """The FULL tool runner (actions + plugins + inline tools) when the
    automation engine has one, else player.run_tool, else None."""
    try:
        from core.automation import ENGINE
        fn = ENGINE.get_tool_runner()
        if callable(fn):
            return fn
    except Exception:
        pass
    try:
        fn = getattr(player, "run_tool", None)
        if callable(fn):
            return fn
    except Exception:
        pass
    return None


def _get_speed() -> str:
    try:
        from memory.config_manager import get_plugin_config
        speed = str((get_plugin_config(_NS_AGENTS) or {}).get(_SPEED_KEY)
                    or _DEFAULT_SPEED).strip().lower()
        return speed if speed in ("fast", "careful") else _DEFAULT_SPEED
    except Exception:
        return _DEFAULT_SPEED


def _danger_note(tool: str) -> str:
    return (f"'{tool}' cholate parlam na — eta dangerous action "
            f"(PC off / shutdown / uninstall). Confirm kore abar bolle "
            f"confirm=true diye chalabo.")


# ── action: say_text ─────────────────────────────────────────────────────────

def _say_text(params: dict, player) -> str:
    text = str(params.get("text") or "").strip()
    if not text:
        return "Ki bolbo? text dao — say_text-e text lagbe."
    if player is None:
        return (f"'{text}' bolte parlam na — ekhon kono voice session ba "
                "player jora nei.")
    speak = getattr(player, "request_say", None)
    if not callable(speak):
        return (f"'{text}' bolte parlam na — ei Mark-e voice bolbar "
                "channel (request_say) nei.")
    try:
        # plugin_say takes an instruction and Gemini phrases it; ask it to
        # say this text, and say it only when a live session is open —
        # otherwise it is silently a no-op, which the reply says honestly.
        speak(f"Say this to the user, in their language: {text}")
    except Exception as exc:
        return f"'{text}' bolte giye bhul holo: {exc}"
    return (f"Voice-e bolte bollam: “{_short(text, 120)}” — live voice "
            "session khola thakle ekhoni shona jabe.")


# ── action: parallel_run ─────────────────────────────────────────────────────

def _parallel_run(params: dict, player) -> str:
    tasks = _parse_json_list(params.get("tasks"))
    if not tasks:
        return ("parallel_run-e tasks lagbe — JSON list, jemon "
                "'[{\"tool\": \"weather_report\", \"args\": {\"city\": \"Kolkata\"}}]'.")
    runner = _runner(player)
    if runner is None:
        return ("Parallel chalate parlam na — kono tool runner jora nei "
                "(Mark restart korte hobe).")
    confirm = _as_bool(params.get("confirm"), False)
    jobs = []
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            continue
        tool = str(t.get("tool") or "").strip()
        if not tool:
            continue
        args = t.get("args") if isinstance(t.get("args"), dict) else {}
        jobs.append((i, tool, args))
    if not jobs:
        return "parallel_run-e kono boidho tool pelam na — prottek task-e 'tool' naam lagbe."
    speed = _get_speed()
    results: dict[int, str] = {}
    blocked = []
    runnable = []
    for i, tool, args in jobs:
        if tool in _DANGEROUS and not confirm:
            blocked.append(tool)
            results[i] = f"BLOCKED: {_danger_note(tool)}"
        else:
            runnable.append((i, tool, args))

    def _call(job):
        i, tool, args = job
        try:
            return i, _short(runner(tool, dict(args)))
        except Exception as exc:
            return i, f"tool {tool} raised: {exc}"

    if runnable and speed == "careful":
        for job in runnable:  # sequential, one by one
            i, out = _call(job)
            results[i] = out
    elif runnable:
        try:
            with ThreadPoolExecutor(max_workers=min(len(runnable), _MAX_PARALLEL)) as pool:
                futs = {pool.submit(_call, job): job[0] for job in runnable}
                for fut, idx in futs.items():
                    try:
                        i, out = fut.result(timeout=_PARALLEL_TIMEOUT_S)
                        results[i] = out
                    except FuturesTimeout:
                        results[idx] = f"tool {jobs[idx][1]}: {int(_PARALLEL_TIMEOUT_S)}s-e sesh hoyni — ekhono cholche."
                    except Exception as exc:
                        results[idx] = f"tool {jobs[idx][1]} raised: {exc}"
        except Exception as exc:
            return f"Parallel chalate giye bhul holo: {exc}"
    lines = [f"Parallel run ({speed}, {len(jobs)} task):"]
    for i, tool, _args in jobs:
        lines.append(f"• {tool}: {results.get(i, 'kono result nei')}")
    if blocked:
        lines.append("Confirm-first: " + ", ".join(sorted(set(blocked)))
                     + " — user confirm korle confirm=true diye abar chalan.")
    return "\n".join(lines)


# ── action: task_queue ───────────────────────────────────────────────────────

def _task_queue(_params: dict, _player) -> str:
    try:
        from core.action_queue import list_pending
        pending = list_pending()
    except Exception:
        return "Queue dekhte parlam na — action_queue porte parini."
    if not pending:
        return "Queue khali — kono pending action nei."
    lines = [f"Queue-e {len(pending)} ta pending action:"]
    for n, e in enumerate(pending, 1):
        args = e.get("args") or {}
        arg_s = _short(json.dumps(args, ensure_ascii=False), 100) if args else ""
        lines.append(f"{n}. {e.get('tool')} [{e.get('id')}] {arg_s}".rstrip())
    return "\n".join(lines)


# ── one-time spoken tasks (remind / timer) ───────────────────────────────────

def _fire_time(params: dict, default_minutes: float):
    """(fire datetime, label) or (None, error)."""
    try:
        at = str(params.get("at") or "").strip()
        if at:
            when = datetime.fromisoformat(at)
            if when <= datetime.now():
                return None, "at-er somoy ta ekhon theke pore hote hobe."
            return when, when.strftime("%Y-%m-%d %H:%M")
        minutes = _as_number(params.get("minutes"), default_minutes)
        if minutes <= 0 or minutes > 60 * 24 * 7:
            return None, "minutes 0-er beshi, 1 soptaher kom hote hobe."
        when = datetime.now() + timedelta(minutes=minutes)
        return when, f"{minutes:g} min pore ({when.strftime('%H:%M')})"
    except Exception:
        return None, "Somoy ta bujhlam na — minutes (number) ba at (ISO datetime) dao."


def _create_spoken_task(name: str, message: str, when: datetime, player) -> str:
    """A one-time automation task whose only step speaks via this plugin.

    The step calls the dispatcher itself (agents_automation + say_text):
    engine steps can only name discovered tools, and this plugin IS the
    discovered tool — a bare 'say_text' step would find no such tool.
    """
    try:
        from core.automation import ENGINE
        # One-time trigger needs BOTH date + time: compute_next_run() returns
        # None unless "time" parses, so an "at"-only trigger never gets a
        # next_run and would never fire. Whole-minute granularity: the
        # scheduler fires at HH:MM:00, so a timer can fire up to 59 s early.
        task_id = ENGINE.create_task({
            "name": name,
            "trigger": {"type": "time", "kind": "once",
                        "date": when.strftime("%Y-%m-%d"),
                        "time": when.strftime("%H:%M")},
            "steps": [{"tool": "agents_automation",
                       "args": {"action": "say_text", "text": message}}],
            "description": f"One-time spoken task, fires {when.isoformat(timespec='seconds')}.",
        })
    except Exception as exc:
        return f"Task banate giye bhul holo: {exc}"
    if not task_id:
        return ("Task banate parlam na — naam/trigger/step thik ache kina "
                "dekho.")
    return task_id


def _remind(params: dict, player) -> str:
    message = str(params.get("message") or "").strip()
    if not message:
        return "Ki mone korabo? message dao — remind-e message lagbe."
    when, label = _fire_time(params, 30)
    if when is None:
        return label
    task_id = _create_spoken_task(f"Reminder: {_short(message, 40)}", message, when, player)
    if task_id.startswith("Task banate"):
        return task_id
    return (f"Reminder set — {label} bolbo: “{_short(message, 120)}” "
            f"(task {task_id}). Mark khola thakle tobei bolbe.")


def _timer(params: dict, player) -> str:
    message = str(params.get("message") or "Timer shesh!").strip()
    when, label = _fire_time(params, 10)
    if when is None:
        return label
    # The spoken message IS the alarm — there is no separate beep channel
    # from an automation step, so the step says the message out loud.
    spoken = f"{message} ⏰ Timer shesh!"
    task_id = _create_spoken_task(f"Timer: {_short(message, 40)}", spoken, when, player)
    if task_id.startswith("Task banate"):
        return task_id
    return (f"Timer set — {label} voice-e bolbo: “{_short(message, 120)}” "
            f"(task {task_id}). Eta-i alarm; alada beep sound nei.")


# ── action: todo ─────────────────────────────────────────────────────────────

def _load_todos() -> list[dict]:
    try:
        from memory.config_manager import get_plugin_config
        items = (get_plugin_config(_NS_TODOS) or {}).get("items")
        return [dict(i) for i in items if isinstance(i, dict)]
    except Exception:
        return []


def _save_todos(items: list[dict]) -> bool:
    try:
        from memory.config_manager import save_plugin_config
        save_plugin_config(_NS_TODOS, {"items": items})
        return True
    except Exception:
        return False


def _todo(params: dict, _player) -> str:
    sub = str(params.get("todo_action") or "list").strip().lower()
    if sub == "add":
        text = str(params.get("item") or "").strip()
        if not text:
            return "Ki todo add korbo? item dao."
        items = _load_todos()
        items.append({"id": uuid.uuid4().hex[:8], "text": text,
                      "done": False,
                      "created": datetime.now().isoformat(timespec="seconds")})
        if not _save_todos(items):
            return "Todo save korte parlam na — config porte/likhte parini."
        return f"Todo add holo: “{_short(text, 120)}” (mot {len(items)} ta)."
    if sub == "list":
        items = _load_todos()
        if not items:
            return "Todo list khali — kichu add kora nei."
        lines = [f"Todo ({sum(1 for i in items if not i.get('done'))} baki / {len(items)} mot):"]
        for n, it in enumerate(items, 1):
            mark = "✅" if it.get("done") else "⬜"
            lines.append(f"{n}. {mark} {it.get('text')} [{it.get('id')}]")
        return "\n".join(lines)
    if sub == "done":
        key = str(params.get("todo_id") or "").strip()
        if not key:
            return "Konta done korbo? todo_id (list-er id ba number) dao."
        items = _load_todos()
        target = None
        if key.isdigit():
            idx = int(key) - 1
            if 0 <= idx < len(items):
                target = items[idx]
        if target is None:
            for it in items:
                if str(it.get("id") or "") == key:
                    target = it
                    break
        if target is None:
            lowered = key.lower()
            for it in items:
                if lowered in str(it.get("text") or "").lower():
                    target = it
                    break
        if target is None:
            return f"'{key}' bole kono todo pelam na — list dekhe id/number dao."
        if target.get("done"):
            return f"Eta agei done: “{_short(str(target.get('text')), 100)}”."
        target["done"] = True
        if not _save_todos(items):
            return "Todo update korte parlam na — config likhte parini."
        return f"Done: “{_short(str(target.get('text')), 120)}”."
    if sub == "clear":
        items = _load_todos()
        if _as_bool(params.get("all"), False):
            from memory.config_manager import bulk_clear_guard
            if not bulk_clear_guard("todos", _as_bool(params.get("confirm"), False)):
                return ("Sob todo clear korte confirm=yes dao — data "
                        "protection ON ache, vul kore muche jabe na.")
            if not items:
                return "Todo list agei khali."
            _save_todos([])
            return f"Sob todo clear holo ({len(items)} ta)."
        kept = [i for i in items if not i.get("done")]
        removed = len(items) - len(kept)
        if removed == 0:
            return "Clear korar moto kono done todo nei."
        _save_todos(kept)
        return f"{removed} ta done todo clear holo — {len(kept)} ta baki."
    return ("todo_action bujhlam na — add | list | done | clear-er "
            "modhye ekta dao.")


# ── action: predict_next ─────────────────────────────────────────────────────

def _predict_next(_params: dict, _player) -> str:
    hist = []
    todos = []
    try:
        from core.automation import ENGINE
        hist = ENGINE.history() or []
    except Exception:
        hist = []
    try:
        todos = [i for i in _load_todos() if not i.get("done")]
    except Exception:
        todos = []
    pending_txt = "; ".join(str(i.get("text")) for i in todos[:5]) or "kono baki todo nei"
    recent = hist[-8:]
    recent_txt = "; ".join(
        f"{h.get('task_name')} ({h.get('status')})" for h in recent
    ) or "ekhono kono automation run hoyni"
    prompt = (
        "You are Mark, a desktop assistant. Based on the user's recent "
        "automation runs and pending todos, suggest the 2-3 most useful next "
        "actions, one short line each, in the user's language (Banglish is "
        "fine). Recent runs: " + recent_txt + ". Pending todos: " + pending_txt + "."
    )
    try:
        from core import gemini
        suggestion = gemini.text(prompt, tier=gemini.FAST)
    except Exception:
        suggestion = None
    if suggestion and str(suggestion).strip():
        return "Next ki korle bhalo hobe:\n" + str(suggestion).strip()
    # Honest fallback when the model is unavailable: frequency + todos.
    from collections import Counter
    names = Counter(str(h.get("task_name") or "") for h in hist if h.get("task_name"))
    lines = ["Model-er poramorsho ekhon pelam na — tothyo theke bollam:"]
    if names:
        top = names.most_common(2)
        lines.append("Sobcheye beshi chola task: " + ", ".join(f"{n} ({c} bar)" for n, c in top) + ".")
    if todos:
        lines.append("Baki todo: " + "; ".join(str(i.get("text")) for i in todos[:3]) + " — egulo age sesh korle bhalo.")
    if not names and not todos:
        lines.append("Ekhono kono automation history ba todo nei — ekta todo add kore ba ekta task chaliye suru koro.")
    return "\n".join(lines)


# ── skills (make_skill / run_skill / skill_library) ──────────────────────────

def _load_skills() -> dict:
    try:
        from memory.config_manager import get_plugin_config
        skills = (get_plugin_config(_NS_SKILLS) or {}).get("skills")
        return dict(skills) if isinstance(skills, dict) else {}
    except Exception:
        return {}


def _save_skills(skills: dict) -> bool:
    try:
        from memory.config_manager import save_plugin_config
        save_plugin_config(_NS_SKILLS, {"skills": skills})
        return True
    except Exception:
        return False


def _make_skill(params: dict, _player) -> str:
    name = str(params.get("name") or "").strip()
    rules = str(params.get("rules") or "").strip()
    if not name or not _NAME_RE.match(name):
        return ("Skill-er naam dao — akkhor/number/space/_/- diye, "
                "jemon 'morning_news'.")
    if not rules:
        return "Skill ta ki korbe? rules dao — plain bhashay likhle hobe."
    steps = _parse_json_list(params.get("steps"))
    clean_steps = []
    for s in steps:
        if isinstance(s, dict) and str(s.get("tool") or "").strip():
            clean_steps.append({"tool": str(s["tool"]).strip(),
                                "args": s.get("args") if isinstance(s.get("args"), dict) else {}})
    skills = _load_skills()
    existed = name in skills
    skills[name] = {"rules": rules, "steps": clean_steps,
                    "created": datetime.now().isoformat(timespec="seconds")}
    if not _save_skills(skills):
        return "Skill save korte parlam na — config likhte parini."
    step_txt = f", {len(clean_steps)} ta step" if clean_steps else ", kono step nei (sudhu rules)"
    return (f"Skill {'update' if existed else 'save'} holo: '{name}'{step_txt}. "
            "skill_library diye list/run/delete kora jabe.")


def _run_skill_steps(name: str, skill: dict, params: dict, player) -> str:
    steps = skill.get("steps") or []
    if not steps:
        return (f"Skill '{name}'-er kono step nei — sudhu rules ache: "
                f"{_short(str(skill.get('rules')), 200)} Chalate hole "
                "make_skill-e steps dao.")
    runner = _runner(player)
    if runner is None:
        return ("Skill chalate parlam na — kono tool runner jora nei "
                "(Mark restart korte hobe).")
    confirm = _as_bool(params.get("confirm"), False)
    lines = [f"Skill '{name}' cholche ({len(steps)} step):"]
    for n, step in enumerate(steps, 1):
        tool = str(step.get("tool") or "").strip()
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        if not tool:
            lines.append(f"{n}. (khali step — skip)")
            continue
        if tool in _DANGEROUS and not confirm:
            lines.append(f"{n}. {tool}: BLOCKED — {_danger_note(tool)}")
            continue
        try:
            lines.append(f"{n}. {tool}: {_short(runner(tool, dict(args)))}")
        except Exception as exc:
            lines.append(f"{n}. {tool}: tool raised: {exc}")
            break
    return "\n".join(lines)


def _run_skill(params: dict, player) -> str:
    name = str(params.get("name") or "").strip()
    if not name:
        return "Konta skill chalabo? name dao."
    skill = _load_skills().get(name)
    if skill is None:
        return f"'{name}' bole kono skill pelam na — skill_library-e list dekho."
    return _run_skill_steps(name, skill, params, player)


def _skill_library(params: dict, player) -> str:
    sub = str(params.get("library_action") or "list").strip().lower()
    if sub == "list":
        skills = _load_skills()
        if not skills:
            return "Skill library khali — make_skill diye prothom skill banao."
        lines = [f"Skill library ({len(skills)} ta):"]
        for name in sorted(skills):
            sk = skills[name]
            steps_n = len(sk.get("steps") or [])
            lines.append(f"• {name} — {_short(str(sk.get('rules')), 100)} [{steps_n} step]")
        return "\n".join(lines)
    if sub == "run":
        return _run_skill(params, player)
    if sub == "delete":
        name = str(params.get("name") or "").strip()
        if not name:
            return "Konta skill delete korbo? name dao."
        skills = _load_skills()
        if name not in skills:
            return f"'{name}' bole kono skill pelam na."
        if not _as_bool(params.get("confirm"), False):
            return (f"'{name}' skill delete korbo? Confirm korle abar "
                    "confirm=true diye bolo — tokhon delete hobe, ar eta "
                    "ferano jabe na.")
        del skills[name]
        if not _save_skills(skills):
            return "Skill delete korte parlam na — config likhte parini."
        return f"Skill '{name}' delete holo."
    return "library_action bujhlam na — list | run | delete-er modhye ekta dao."


# ── action: agent_speed ──────────────────────────────────────────────────────

def _agent_speed(params: dict, _player) -> str:
    speed = params.get("speed")
    if speed is None or str(speed).strip() == "":
        current = _get_speed()
        return (f"Agent speed ekhon: {current}. fast = parallel-e chalabe, "
                "careful = ekta kore sequential.")
    wanted = str(speed).strip().lower()
    if wanted not in ("fast", "careful"):
        return "Speed 'fast' ba 'careful' hote hobe."
    try:
        from memory.config_manager import save_plugin_config
        save_plugin_config(_NS_AGENTS, {_SPEED_KEY: wanted})
    except Exception:
        return "Speed save korte parlam na — config likhte parini."
    return (f"Agent speed set holo: {wanted}. "
            + ("parallel_run ekhon eksathe chalabe."
               if wanted == "fast" else
               "parallel_run ekhon ekta kore sequential chalabe."))


# ── action: good_morning ─────────────────────────────────────────────────────

def _good_morning(params: dict, _player) -> str:
    when = str(params.get("time") or "07:50").strip()
    if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", when):
        return "Somoy HH:MM format-e dao, jemon '07:50'."
    city = str(params.get("city") or "Kolkata").strip() or "Kolkata"
    try:
        from core.automation import ENGINE
        for t in ENGINE.list_tasks():
            if str(t.get("name") or "") == "Good morning routine":
                return (f"Good morning routine agei ache (task {t.get('id')}, "
                        f"roj {when}-e cholbe). Notun kore banaini.")
        task_id = ENGINE.create_task({
            "name": "Good morning routine",
            "trigger": {"type": "time", "kind": "daily", "time": when},
            "steps": [
                {"tool": "weather_report",
                 "args": {"city": city, "time": "today"}},
                {"tool": "web_search",
                 "args": {"query": "top news today", "mode": "news"}},
                {"tool": "agents_automation",
                 "args": {"action": "todo", "todo_action": "list"}},
                {"tool": "agents_automation",
                 "args": {"action": "say_text",
                          "text": f"Good morning! Ajker weather ar khobor ready, ar todo list dekhe nao."}},
            ],
            "description": (
                f"Daily {when} — weather ({city}) + top news + todo list + "
                "good-morning voice. Category 7 morning routine; NOT the "
                "morning_briefing template (seta alada)."
            ),
        })
    except Exception as exc:
        return f"Morning routine banate giye bhul holo: {exc}"
    if not task_id:
        return "Morning routine banate parlam na — task-er naam/trigger/step thik ache kina dekho."
    return (f"Good morning routine set — roj {when}-e cholbe: weather "
            f"({city}) + top news + todo list + voice greeting "
            f"(task {task_id}). Mark khola thakle tobei cholbe.")


# ── dispatcher ───────────────────────────────────────────────────────────────

_ACTIONS = {
    "parallel_run": _parallel_run,
    "task_queue": _task_queue,
    "remind": _remind,
    "say_text": _say_text,
    "timer": _timer,
    "todo": _todo,
    "predict_next": _predict_next,
    "make_skill": _make_skill,
    "run_skill": _run_skill,
    "skill_library": _skill_library,
    "agent_speed": _agent_speed,
    "good_morning": _good_morning,
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Dispatch to one of the twelve Category 7 actions. Never raises."""
    try:
        params = parameters if isinstance(parameters, dict) else {}
        action = str(params.get("action") or "").strip().lower()
        fn = _ACTIONS.get(action)
        if fn is None:
            return ("agents_automation-e action lagbe: parallel_run | "
                    "task_queue | remind | say_text | timer | todo | "
                    "predict_next | make_skill | run_skill | skill_library | "
                    "agent_speed | good_morning.")
        out = fn(params, player)
        _log(player, f"JARVIS: {action} — {_short(out, 160)}")
        return out if isinstance(out, str) and out.strip() else "Done."
    except Exception as exc:
        return f"agents_automation failed: {exc}"
