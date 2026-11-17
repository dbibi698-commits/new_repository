"""plugins/automation_fix.py — Self-healing automation plugin.

"automation_fix" — run an automation, and if it fails, diagnose the failure
(timeout vs step error vs missing input), apply the matching fix, and retry
(up to 3 attempts). Use this instead of plain `automation` run when an
automation has failed and should be fixed, not just re-run.

The run happens on a background thread so run() returns at once; the result
lands in the activity log / content panel. Never raises. No Qt here.
"""
from __future__ import annotations

import threading

PLUGIN = {
    "name": "automation_fix",
    "description": (
        "Run an automation WITH self-healing: if it fails, Mark diagnoses "
        "the failure (timeout, step error, or missing input), applies the "
        "matching fix (bigger timeout, retry, or asking for the missing "
        "value) and retries, up to 3 attempts. Use when an automation "
        "failed, or when asked to run one and fix it if it breaks. Do NOT "
        "use to create or list automations — that is the automation tool."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "automation_id": {"type": "STRING",
                              "description": "Id of the automation to run and fix, from the automation list"},
        },
        "required": ["automation_id"],
    },
}


def _run_bg(automation_id: str, player) -> None:
    """Background worker: an automation run can take a while."""
    try:
        from core import automation_fix
        result = automation_fix.run_automation_with_fix(automation_id)
    except Exception as e:
        result = f"Automation self-heal chalate parlam na: {e}"
    if player:
        try:
            player.write_log(f"JARVIS: {result}")
        except Exception:
            pass
        try:
            player.show_content("Automation self-heal", result)
        except Exception:
            pass


def run(parameters: dict, player=None, session_memory=None) -> str:
    parameters = parameters or {}
    automation_id = str(parameters.get("automation_id") or "").strip()
    if not automation_id:
        return "Kon automation chalabo — automation_id dao (automation list theke id nao)."
    try:
        threading.Thread(target=_run_bg, args=(automation_id, player),
                         daemon=True, name="automation-fix").start()
    except Exception as e:
        return f"Automation self-heal start korte parlam na: {e}"
    result = (f"Automation self-heal cholche — '{automation_id}': fail hole "
              "nije diagnose kore fix kore abar chalabo (max 3 bar). "
              "Sesh hole ekhane janabo.")
    if player:
        try:
            player.write_log(f"JARVIS: {result}")
        except Exception:
            pass
    return result
