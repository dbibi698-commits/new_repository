"""plugins/hosting_deploy.py — 🚀 HOSTING / DEPLOY: Render Web Service +
Static Site + GitHub repo create, direct browser control (2026-11-18).

Runs in the user's own logged-in Chrome session (their GitHub/Render
login) — Mark never asks for or stores a site password. The token-based
github_create_repo stays as an alternative; this plugin drives the
WEBSITE like a person.

Modes: AUTO (Mark clicks) and MANUAL (user clicks, Mark watches +
narrates; "tumi koro" hands it back to Mark). Each step is reported
live; a failed step names itself and the page stays open.

Runs on a worker thread. Returns a short string, never raises.
"""
from __future__ import annotations

import threading as _threading

PLUGIN = {
    "name": "hosting_deploy",
    "description": (
        "Deploy + hosting through the browser: Render Web Service deploy, "
        "Render Static Site deploy, GitHub repo create (name + description "
        "+ private/public) — in the user's own logged-in Chrome, AUTO or "
        "MANUAL mode. Call when the user asks: Render-e deploy koro, "
        "static site deploy koro, GitHub-e repo banao, hosting koro."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "'deploy_web', 'deploy_static', "
                                      "'create_repo', 'manual' or 'status'."},
            "service_name": {"type": "STRING",
                             "description": "Render service name (deploy)."},
            "repo_url": {"type": "STRING",
                         "description": "GitHub repo URL "
                                        "(https://github.com/owner/repo)."},
            "branch": {"type": "STRING",
                       "description": "Branch (default main)."},
            "repo_name": {"type": "STRING",
                          "description": "New repo name (create_repo)."},
            "description": {"type": "STRING",
                            "description": "Repo description (create_repo)."},
            "private": {"type": "BOOLEAN",
                        "description": "Private repo? (create_repo, default false)."},
            "mode": {"type": "STRING",
                     "description": "'auto' (Mark clicks) or 'manual' "
                                    "(user clicks, Mark watches + narrates)."},
            "url": {"type": "STRING",
                    "description": "Page URL to watch (manual)."},
        },
        "required": [],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "hosting_deploy",
    "title": "🚀 HOSTING / DEPLOY — Render + GitHub repo create",
    "widget": "hosting_deploy",
    "fields": [],
}


_MANUAL = {"stop": _threading.Event(), "thread": None}


def _narrate(player, text):
    try:
        if player is not None:
            player.write_log(f"🚀 {text}")
    except Exception:
        pass
    try:
        if player is not None and hasattr(player, "request_say"):
            player.request_say(text)
    except Exception:
        pass


def _start_manual(url, player):
    from core import browser_flows as _bf
    _MANUAL["stop"].clear()

    def _watch():
        ok, msg = _bf.run_manual(
            url, (), narrate_fn=lambda t: _narrate(player, t),
            stop_fn=lambda: _MANUAL["stop"].is_set())
        _narrate(player, msg)

    t = _threading.Thread(target=_watch, daemon=True, name="hosting-manual")
    _MANUAL["thread"] = t
    t.start()
    return (f"👀 Manual mode chalu — {url} khullam, tumi click koro, ami "
            f"dekhchi ar bolbo. 'Tumi koro' bolle ami baki-ta korbo.")


def status_text() -> str:
    from core import browser_flows as _bf
    return ("🚀 Hosting / Deploy — Render Web Service + Static Site + "
            "GitHub repo create, tomar logged-in Chrome-e.\n"
            "  • AUTO: Mark nije click korbe, prottek step verify kore.\n"
            "  • MANUAL: tumi click korbe, Mark dekhbe ar bolbe.\n"
            "  • " + _bf.BROWSER_LIMITS)


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Dispatch one hosting/deploy action. Short string, never raises."""
    try:
        params = parameters or {}
        action = str(params.get("action") or "").strip().lower()
        mode = str(params.get("mode") or "auto").strip().lower()
        if action == "status":
            return status_text()
        if action == "manual":
            url = str(params.get("url") or "").strip()
            if not url:
                return "Manual mode-er jonno URL dao."
            return _start_manual(url, player)
        if action == "takeover":
            _MANUAL["stop"].set()
            return "AUTO mode-e nilam — baki step ami korchi."
        if action == "deploy_web":
            service = str(params.get("service_name") or "").strip()
            repo = str(params.get("repo_url") or "").strip()
            branch = str(params.get("branch") or "main").strip() or "main"
            if not service or not repo:
                return "Deploy-er jonno service naam + repo URL dao."
            if mode == "manual":
                return _start_manual("https://dashboard.render.com", player)
            from core import browser_automation as _ba
            ok, msg = _ba.render_deploy(service, repo, branch)
            return msg
        if action == "deploy_static":
            service = str(params.get("service_name") or "").strip()
            repo = str(params.get("repo_url") or "").strip()
            branch = str(params.get("branch") or "main").strip() or "main"
            if not service or not repo:
                return "Static Site deploy-er jonno service naam + repo URL dao."
            if mode == "manual":
                return _start_manual("https://dashboard.render.com", player)
            from core import browser_flows as _bf
            ok, msg = _bf.render_static_deploy(service, repo, branch)
            return msg
        if action == "create_repo":
            name = str(params.get("repo_name") or "").strip()
            desc = str(params.get("description") or "").strip()
            private = bool(params.get("private") or False)
            if not name:
                return "Repo create-er jonno repo naam dao."
            if mode == "manual":
                return _start_manual("https://github.com/new", player)
            from core import browser_automation as _ba
            ok, msg = _ba.github_new_repo(name, desc, private)
            return msg
        return ("Hosting / Deploy — action dao: 'deploy_web', "
                "'deploy_static', 'create_repo', 'manual' ba 'status'.")
    except Exception as e:
        return f"Hosting / Deploy korte parlam na: {e}"
