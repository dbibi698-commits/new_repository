"""plugins/render_browser.py — 🌐 Render deploy WITHOUT an API key.

Drives the user's own logged-in Chrome (no browser helper, no Render API key)
via core/browser_automation.render_deploy on top of the direct
Playwright/CDP driver (core/browser_driver.py). The deploy flow takes a
few minutes, so run() starts it on a worker thread and returns at once;
the result (service URL) is written to the activity log when it finishes.
"""
from __future__ import annotations

import threading

PLUGIN = {
    "name": "render_deploy_browser",
    "description": (
        "Deploy a web service on Render in the user's OWN logged-in Chrome "
        "browser — NO Render API key, NO token. Use it when the user says: "
        "Render-e deploy koro browser diye, Render-e service banao (API key "
        "chara / token chara). Do NOT use the API-key render_deploy tool for "
        "this — this one drives the Render dashboard in the browser instead. "
        "Needs Chrome with the user logged into dashboard.render.com + "
        "Playwright installed."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "service_name": {"type": "STRING",
                             "description": "Render service name, e.g. my-web-app"},
            "repo_url": {"type": "STRING",
                         "description": "GitHub repo URL, e.g. https://github.com/owner/repo"},
            "branch": {"type": "STRING",
                       "description": "Branch to deploy (default main)"},
        },
        "required": ["service_name", "repo_url"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "browser_render",
    "title": "🌐 DEPLOY ON RENDER — BROWSER (NO API KEY)",
    # Extra box the Plugin Settings overlay builds at the end of this
    # section: "Deploy on Render" via the user's own logged-in Chrome
    # (direct Playwright/CDP driver). The overlay only knows the
    # widget key; the box itself lives in gui/overlays.py.
    "widget": "browser_render",
    "fields": [],
}


def _run_flow(service_name: str, repo_url: str, branch: str, player=None):
    """Worker thread: run the flow, log the plain-words result. Never raises."""
    try:
        from core.browser_automation import render_deploy
        ok, msg = render_deploy(service_name, repo_url, branch)
    except Exception as e:
        ok, msg = False, f"Render deploy korte parlam na: {e}"
    if player:
        try:
            player.write_log(f"JARVIS: {msg}")
        except Exception:
            pass


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Start the browser Render deploy in the background. Never raises."""
    try:
        params = parameters if isinstance(parameters, dict) else {}
        service_name = str(params.get("service_name") or "").strip()
        repo_url = str(params.get("repo_url") or "").strip()
        branch = str(params.get("branch") or "main").strip() or "main"
        if not service_name or not repo_url:
            return "Service-er naam ar GitHub repo URL — duitoi dao."
        threading.Thread(target=_run_flow,
                         args=(service_name, repo_url, branch, player),
                         daemon=True).start()
        msg = (f"⏳ Browser-e Render deploy shuru korchi: {service_name} "
               f"({repo_url}, branch {branch}) — Chrome-e dashboard.render.com "
               f"khule service banachhi, hole activity log-e janabo.")
        if player:
            try:
                player.write_log(f"JARVIS: {msg}")
            except Exception:
                pass
        return msg
    except Exception:
        return "Render deploy korte parlam na — kichu ekta gondogol holo."
