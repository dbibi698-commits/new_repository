"""plugins/commander.py — 🎖️ COMMANDER: Mark nijei Commander.

The user tells the Commander, the Commander commands the worker agents
(Builder, Browser, Desktop, Media, Phone, Research, Social + the new
Python / Software / Render / Firebase / Hosting workers) and reports the
result back. The live panel on the master screen shows the order, the
plan, which worker is doing what, and the result.

Runs on a worker thread (callers run plugin.run off the Qt thread).
Returns a short string, never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "commander",
    "description": (
        "Give an order to the Commander (Mark, the main agent): he plans "
        "it, delegates each step to the right worker agent (Builder, "
        "Browser, Desktop, Media, Phone, Research, Social), tracks them "
        "live, and reports the result. Call when the user asks: 'commander, "
        "ekta dashboard banao', 'python run koro', 'apk build koro', "
        "'deploy koro', or any multi-step job."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "order": {"type": "STRING",
                      "description": "The order, e.g. 'ekta todo dashboard banao'."},
            "intent": {"type": "STRING",
                       "description": "Optional: python_run, software_build, apk_build, "
                                      "render_deploy, firebase_connect, hosting_autofix, "
                                      "browser_control, photo_edit."},
            "code": {"type": "STRING",
                     "description": "Python code (for a python_run order)."},
            "spec": {"type": "STRING",
                     "description": "Software spec (for a software_build order)."},
            "repo": {"type": "STRING",
                     "description": "GitHub repo owner/name (apk_build / deploy)."},
        },
        "required": ["order"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "commander",
    "title": "🎖️ COMMANDER — order dao, Mark worker-ke pathabe",
    "widget": "commander",
    "fields": [],
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Take an order, delegate, report. Short string, never raises."""
    try:
        params = parameters or {}
        order = str(params.get("order") or "").strip()
        if not order:
            return "Commander-ke order dao — ki korte hobe bolo."
        from core import commander as _cmd
        payload = {"code": str(params.get("code") or ""),
                   "spec": str(params.get("spec") or ""),
                   "repo": str(params.get("repo") or "")}
        res = _cmd.issue_order(order, intent=str(params.get("intent") or ""),
                               payload=payload)
        return res.get("result_text") or "Order nilam."
    except Exception as e:
        return f"Commander order nite parlam na: {e}"
