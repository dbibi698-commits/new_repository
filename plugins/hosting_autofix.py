"""plugins/hosting_autofix.py — 🛠️ Hosting Auto-Fix: Render deploy fail
hole nijei thik koro.

Checks the latest deploy of the Mark dashboard on Render; when it failed,
fetches the deploy logs, classifies the error, applies a real fix (a
missing env var with a known safe default, an unpinnable package version
in requirements.txt, or a redeploy for a transient error) and redeploys —
max 3 attempts. Anything it cannot fix safely is reported with the log
tail instead of guessed. The work runs on a worker thread (a deploy cycle
takes minutes); the result is written to the activity log when it finishes.
"""
from __future__ import annotations

import threading

PLUGIN = {
    "name": "hosting_autofix",
    "description": (
        "Auto-fix a failed Render deploy: check the latest deploy, read its "
        "logs, classify the error, apply a real fix (missing env var with a "
        "known safe default, a broken package version in requirements.txt, "
        "or a redeploy for a transient error) and redeploy — max 3 attempts. "
        "Call when the user says: deploy fail holo thik koro, hosting fix "
        "koro, Render deploy thik koro, auto-fix koro. Needs the saved "
        "Render API key; an env var with no known default is asked for, "
        "never guessed."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "service_id": {"type": "STRING",
                           "description": "Render service id (optional — auto-finds mark-lvii-dashboard when empty)."},
        },
        "required": [],
    },
}


def _run_flow(service_id: str, player=None):
    """Worker thread: run the fix loop, log the result. Never raises."""
    try:
        from core import hosting_autofix as _hf
        msg = _hf.autofix(service_id)
    except Exception as e:
        msg = f"Hosting auto-fix korte parlam na: {e}"
    if player:
        try:
            player.write_log(f"JARVIS: {msg}")
        except Exception:
            pass


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Start the hosting auto-fix in the background. Never raises."""
    try:
        params = parameters if isinstance(parameters, dict) else {}
        service_id = str(params.get("service_id") or "").strip()
        threading.Thread(target=_run_flow, args=(service_id, player),
                         daemon=True).start()
        msg = ("⏳ Hosting auto-fix cholche — latest deploy dekhe, log pore, "
               "fix kore redeploy dichhi (max 3 bar). Hole activity log-e janabo.")
        if player:
            try:
                player.write_log(f"JARVIS: {msg}")
            except Exception:
                pass
        return msg
    except Exception:
        return "Hosting auto-fix korte parlam na — kichu ekta gondogol holo."
