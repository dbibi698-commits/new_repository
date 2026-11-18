"""plugins/github_browser.py — 📦 GitHub repo create WITHOUT a token.

Drives the user's own logged-in Chrome (no browser helper, no API token) via
core/browser_automation.github_new_repo on top of the direct
Playwright/CDP driver (core/browser_driver.py). The browser work takes a
minute or two, so run() starts it on a worker thread and returns at once;
the result is written to the activity log when it finishes.
"""
from __future__ import annotations

import threading

PLUGIN = {
    "name": "github_repo_browser_create",
    "description": (
        "Create a new GitHub repository in the user's OWN logged-in Chrome "
        "browser — NO GitHub token, NO API. Use it when the user says: "
        "GitHub-e repo banao, notun repo kholo, repo create koro (token "
        "chara / browser diye). Do NOT use the token-based github_create_repo "
        "tool for this — this one drives the browser instead. Needs Chrome "
        "with the user logged into github.com + Playwright installed."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING",
                     "description": "Repository name, e.g. my-new-repo"},
            "description": {"type": "STRING",
                            "description": "Short description (optional)"},
            "private": {"type": "BOOLEAN",
                        "description": "True for a private repo (default false = public)"},
        },
        "required": ["name"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "browser_github",
    "title": "📦 CREATE REPOSITORY — BROWSER (NO TOKEN)",
    # Extra box the Plugin Settings overlay builds at the end of this
    # section: "Create Repository" via the user's own logged-in Chrome
    # (direct Playwright/CDP driver). The overlay only knows the
    # widget key; the box itself lives in gui/overlays.py.
    "widget": "browser_repo",
    "fields": [],
}


def _run_flow(name: str, description: str, private: bool, player=None):
    """Worker thread: run the flow, log the plain-words result. Never raises."""
    try:
        from core.browser_automation import github_new_repo
        ok, msg = github_new_repo(name, description, private)
    except Exception as e:
        ok, msg = False, f"Repo banate parlam na: {e}"
    if player:
        try:
            player.write_log(f"JARVIS: {msg}")
        except Exception:
            pass


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Start the browser repo-create in the background. Never raises."""
    try:
        params = parameters if isinstance(parameters, dict) else {}
        name = str(params.get("name") or "").strip()
        description = str(params.get("description") or "").strip()
        private = bool(params.get("private", False))
        if not name:
            return "Repo-r naam dao — ki naam-e repo banabo?"
        threading.Thread(target=_run_flow, args=(name, description, private,
                                                 player),
                         daemon=True).start()
        msg = (f"⏳ Browser-e repo banachhi: {name} "
               f"({'private' if private else 'public'}) — Chrome-e github.com "
               f"khule form bhorchi, hole activity log-e janabo.")
        if player:
            try:
                player.write_log(f"JARVIS: {msg}")
            except Exception:
                pass
        return msg
    except Exception:
        return "Repo banate parlam na — kichu ekta gondogol holo."
