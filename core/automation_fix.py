"""core/automation_fix.py — Self-healing automation runs for Mark-LVII.

Wraps core/automation.py's ENGINE (``run_task_now``) with diagnose → fix
→ retry, up to 3 attempts.

WHAT IT DOES
    1. Run the automation (reuse ENGINE — never re-implement the runner).
    2. On failure, read the run's history entry and diagnose:
         missing_input → a step's arg is a "[EDIT ...]" placeholder, empty,
                         or the result says a value is missing. NOT retried
                         blindly — stops and asks the user for the value.
         timeout       → the step timed out. Fix: bump a timeout arg on the
                         failed step (x2) when one exists, else retry after
                         a short pause (slow tools often pass on retry).
         step_error    → any other step failure. Fix: re-run the task
                         (the engine already retried the failed step once
                         inside the run, so this is a fresh attempt).
         condition     → the task's "only if" condition was not met
                         (e.g. offline). NOT retried — the condition, not
                         the task, is the problem.
    3. Hard cap of 3 runs. No infinite loops, ever.

RULES
    * Every public function returns a plain-words string and never raises.
    * A fix never invents input: when a value is missing, the report names
      the tool + the arg and asks the user for it.
    * ``engine`` / ``sleep_fn`` are injectable so tests can run with a fake
      engine — no real automations are ever run by the tests.
"""
from __future__ import annotations

import re

_MAX_ATTEMPTS = 3

_TIMEOUT_RE = re.compile(
    r"(timed?\s*out|timeout|took too long|somoy sesh|time limit)", re.I)
_MISSING_RE = re.compile(
    r"(missing (input|argument|value|file|parameter)|required .*"
    r"(missing|empty|not (set|provided|given))|not provided|"
    r"no value (given|provided)|empty (value|argument|input))", re.I)
_CONDITION_RE = re.compile(r"condition not met|skipped — condition", re.I)


# ── small utilities (never raise) ────────────────────────────────────────────

def _trunc(text: str, limit: int = 300) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _is_problem(result: str) -> bool:
    """Did an automation run fail? The engine's run_task_now speaks in
    ✅/❌ sentences, NOT outcome status lines — outcome.is_problem only
    catches "status=failed ..." strings, so a "❌ ..." run result would
    slip through as a success if we trusted it alone. Treat ❌ as a
    problem, ✅ as a success, and fall back to the engine's own check."""
    text = str(result or "")
    if not text.strip():
        return True
    if text.strip().startswith("❌"):
        return True
    if text.strip().startswith("✅"):
        return False
    try:
        from core import outcome
        if outcome.is_problem(text):
            return True
    except Exception:
        pass
    try:
        from core.automation import _is_problem as _engine_problem
        return _engine_problem(text)
    except Exception:
        return False


def _as_list(value) -> list:
    return list(value) if isinstance(value, list) else []


def _as_dict(value) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _failed_step(task: dict, history: list) -> dict:
    """The first failed step of the latest run, from the history entry.
    {} when the history says nothing."""
    try:
        entries = [h for h in _as_list(history) if isinstance(h, dict)]
        if not entries:
            return {}
        steps = _as_list(entries[-1].get("steps"))
        for s in steps:
            if isinstance(s, dict) and not s.get("ok", True):
                return s
        return {}
    except Exception:
        return {}


def _find_placeholder_step(task: dict) -> tuple[str, str]:
    """(tool, arg-name) of the first step whose arg still holds an
    "[EDIT ...]" placeholder, else ("", "")."""
    try:
        for step in _as_list(task.get("steps")):
            if not isinstance(step, dict):
                continue
            args = _as_dict(step.get("args"))
            for key, value in args.items():
                if isinstance(value, str) and "[EDIT" in value:
                    return str(step.get("tool") or "?"), str(key)
    except Exception:
        pass
    return "", ""


# ── diagnosis ────────────────────────────────────────────────────────────────

def diagnose_failure(task: dict, result: str, history: list) -> dict:
    """Failure → {kind, failed_tool, detail, fix}. Pure, never raises.

    kind: missing_input | timeout | condition | step_error.
    """
    try:
        result = str(result or "")
        failed = _failed_step(task, history)
        failed_tool = str(failed.get("tool") or "")
        if not failed_tool:
            # Fall back to the task's step list: the result usually names it.
            for step in _as_list(task.get("steps")):
                tool = str(step.get("tool") or "")
                if tool and tool in result:
                    failed_tool = tool
                    break
        detail = _trunc(failed.get("result") or result, 300)
        # (1) Missing input — a placeholder arg, or the result says so.
        tool, arg = _find_placeholder_step(task)
        if tool:
            return {"kind": "missing_input", "failed_tool": tool,
                    "detail": detail,
                    "fix": (f"'{tool}' step-er '{arg}' arg-e ekhono "
                            f"[EDIT ...] lekha ache — asol value-ta bosate hobe.")}
        if _MISSING_RE.search(result) or _MISSING_RE.search(detail):
            return {"kind": "missing_input", "failed_tool": failed_tool,
                    "detail": detail,
                    "fix": "ekta step-er dorkari value missing — "
                           "ki value lagbe seta niche likhlam."}
        # (2) Condition not met — not a task failure, do not retry.
        if _CONDITION_RE.search(result):
            return {"kind": "condition", "failed_tool": failed_tool,
                    "detail": detail,
                    "fix": "task-er 'only if' condition mileni — "
                           "condition-ta thik hole nije cholbe."}
        # (3) Timeout.
        if _TIMEOUT_RE.search(result) or _TIMEOUT_RE.search(detail):
            return {"kind": "timeout", "failed_tool": failed_tool,
                    "detail": detail,
                    "fix": "timeout mone hocche — timeout bariye abar chalalam."}
        # (4) Any other step failure.
        return {"kind": "step_error", "failed_tool": failed_tool or "?",
                "detail": detail,
                "fix": "step-ta fail korlo — abar chaliye dekhlam."}
    except Exception as e:
        return {"kind": "step_error", "failed_tool": "?",
                "detail": f"diagnose korte parlam na: {e}",
                "fix": "abar chaliye dekhlam."}


def _bump_timeout(task: dict, engine, failed_tool: str) -> str:
    """Double a timeout arg on the failed step (when one exists) via
    engine.update_task. Returns a note of what changed, else ""."""
    try:
        steps = _as_list(task.get("steps"))
        changed = False
        new_steps = []
        for step in steps:
            step = dict(step) if isinstance(step, dict) else {}
            args = _as_dict(step.get("args"))
            if str(step.get("tool") or "") == failed_tool:
                for key in list(args.keys()):
                    if "timeout" in str(key).lower():
                        try:
                            old = float(args[key])
                            args[key] = int(old * 2) if old else 60
                        except Exception:
                            args[key] = 60
                        changed = True
                step["args"] = args
            new_steps.append(step)
        if not changed:
            return ""
        task_id = str(task.get("id") or "")
        ok = False
        try:
            ok = bool(engine.update_task(task_id, {"steps": new_steps}))
        except Exception:
            ok = False
        if not ok:
            return ""
        return "failed step-er timeout double kore dilam, "
    except Exception:
        return ""


# ── the self-healing run ─────────────────────────────────────────────────────

def run_automation_with_fix(automation_id: str, max_attempts: int = 3,
                            engine=None, sleep_fn=None) -> str:
    """Run an automation; on failure diagnose, fix, retry — up to
    `max_attempts` runs (hard cap 3 by default). Returns a plain-words
    report. Never raises."""
    try:
        automation_id = str(automation_id or "").strip()
        attempts = max(1, min(int(max_attempts or 3), 3))
        if not automation_id:
            return "Kon automation chalabo — id dao."
        if engine is None:
            try:
                from core.automation import ENGINE as engine
            except Exception as e:
                return f"Automation engine pelam na: {e}"
        try:
            task = engine.get_task(automation_id)
        except Exception as e:
            return f"Automation-ta khulte parlam na: {e}"
        if not task:
            return f"'{automation_id}' id-r kono automation pelam na."
        name = str(task.get("name") or automation_id)
        lines = [f"Automation '{name}' — self-heal:"]
        for attempt in range(1, attempts + 1):
            try:
                result = engine.run_task_now(automation_id)
            except Exception as e:
                result = f"❌ {name}: failed — {e}"
            result = str(result or "")
            if not _is_problem(result):
                lines.append(f"• Attempt {attempt}: ✅ {name} sesh holo — "
                             f"{_trunc(result, 200)}")
                lines.append(f"Final: automation cholllo — attempt {attempt}/{attempts}.")
                return "\n".join(lines)
            try:
                history = engine.history(automation_id)
            except Exception:
                history = []
            diag = diagnose_failure(task, result, history)
            kind = diag.get("kind") or "step_error"
            tool = diag.get("failed_tool") or "?"
            lines.append(f"• Attempt {attempt}: fail holo — step '{tool}': "
                         f"{_trunc(diag.get('detail') or result, 200)}")
            if kind in ("missing_input", "condition"):
                lines.append(f"  Stop: {diag.get('fix')}")
                if kind == "missing_input":
                    lines.append("  Value-ta dao (task-ta edit kore), "
                                 "tarpor abar bolo — ami nije value banate parbo na.")
                lines.append(f"Final: automation choleni ({attempt}/{attempts} attempt).")
                return "\n".join(lines)
            fix_note = ""
            if kind == "timeout":
                try:
                    fix_note = _bump_timeout(task, engine, tool)
                except Exception:
                    fix_note = ""
                try:
                    task = engine.get_task(automation_id) or task
                except Exception:
                    pass
            lines.append(f"  Fix: {fix_note}abar chalalam.")
            if attempt >= attempts:
                lines.append(f"Final: {attempts} bar try korlam, automation "
                             "choleni — step-ta nije dekho, ba amake details dao.")
                return "\n".join(lines)
            if sleep_fn is not None:
                try:
                    sleep_fn(2)
                except Exception:
                    pass
        lines.append(f"Final: {attempts} bar try korlam, automation choleni.")
        return "\n".join(lines)
    except Exception as e:
        return f"Automation self-heal chalate parlam na: {e}"
