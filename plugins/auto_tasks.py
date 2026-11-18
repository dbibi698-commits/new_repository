"""plugins/auto_tasks.py — 📋 AUTOMATIC TASKS: create / list / run /
cancel custom tasks by voice/text. Wraps core/auto_tasks.py (which
builds real core/automation.py tasks that run through the Commander).

Executor honesty: PC tasks run only while Mark is running (they catch
up when Mark starts); phone tasks run on the phone even when the PC is
off; offline tasks queue and auto-retry. Never claims a task ran while
the PC was off. Never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "auto_task",
    "description": (
        "Automatic / custom tasks — create a task by voice/text (one-time "
        "or recurring: daily/weekly/monthly, e.g. 'protidin sokal 8-tay "
        "weather report dao', 'proti Robibar Downloads organize koro'), "
        "list tasks, run one now, retry the offline queue. Tasks run "
        "through the Commander; phone tasks run on the phone even when "
        "the PC is off. Call when the user says: task banao, protidin "
        "..., schedule koro, task gulo dekhao."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "create | list | run_now | retry_offline"},
            "text": {"type": "STRING",
                     "description": "Task in plain words (create)."},
            "task_id": {"type": "STRING",
                        "description": "Task id (run_now)."},
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        p = parameters or {}
        action = str(p.get("action") or "").strip().lower()
        from core import auto_tasks as at
        if action == "create":
            return at.create_task_from_text(str(p.get("text") or ""))
        if action == "list":
            return at.tasks_panel_text()
        if action == "run_now":
            from core import automation as _a
            return _a.ENGINE.run_task_now(str(p.get("task_id") or ""))
        if action == "retry_offline":
            return at.retry_offline_tasks()
        return at.tasks_panel_text()
    except Exception as e:
        return f"Task chalate parlam na: {e}"

PLUGIN_SETTINGS = {
    "namespace": "auto_tasks",
    "title": "📋 AUTOMATIC TASKS — custom tasks, queue + executor",
    "fields": [],
    # Extra box the Plugin Settings overlay builds at the end of this
    # section: the Tasks panel (queue / running / done / failed + ke
    # chalalo: phone / pc / backend) + PC-off honesty. The overlay only
    # knows the widget key; the box itself lives in gui/overlays.py.
    "widget": "auto_tasks",
}
