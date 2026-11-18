"""plugins/software_builder.py — 🛠️ SOFTWARE BUILDER: boro software banao.

The user describes the software (desktop app, web app, utility tool,
dashboard) and Mark builds the FULL project — file structure + complete
code — tests it, runs it on localhost, fixes errors (max 3 attempts),
and offers one-click Render deploy. The Plugin Settings overlay builds
the "Software Builder" box for this plugin (widget "software_builder"):
spec field + kind picker + Build & Run button + live state + servers list.

Runs on a worker thread (the callers — agent card, Commander, overlay —
run plugin.run off the Qt thread). Returns a short string, never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "software_builder",
    "description": (
        "Build a whole software project from a description — desktop app, "
        "web app, utility tool or dashboard: full file structure + complete "
        "code, tested, run on localhost (opened in Chrome), errors fixed "
        "(max 3 attempts), one-click Render deploy. Call when the user asks: "
        "software banao, app banao, dashboard banao, website banao, tool "
        "banao, localhost-e chalao, deploy koro."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "spec": {"type": "STRING",
                     "description": "What to build, e.g. 'ekta todo dashboard banao'."},
            "kind": {"type": "STRING",
                     "description": "'web', 'desktop' or 'tool' (empty = auto)."},
            "template": {"type": "STRING",
                         "description": "Template id (optional): "
                                        "'flask_dashboard', 'fastapi_sqlite', "
                                        "'pyqt_desktop', 'static_site', "
                                        "'telegram_bot' or 'file_organizer'. "
                                        "Empty = auto (spec names a stack) or "
                                        "the stdlib starter."},
            "deploy": {"type": "BOOLEAN",
                       "description": "True = also deploy to Render (needs repo)."},
            "repo": {"type": "STRING",
                     "description": "GitHub repo owner/name for deploy."},
            "open_browser": {"type": "BOOLEAN",
                             "description": "True = open the localhost URL in Chrome (default)."},
        },
        "required": ["spec"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "software_builder",
    "title": "🛠️ SOFTWARE BUILDER — software banao, localhost-e chalao",
    "widget": "software_builder",
    "fields": [],
}


def _ask_fn():
    """Gemini as the code generator (ask_fn for core.software_builder)."""
    try:
        from core import gemini
        import json as _json

        def _ask(prompt: str):
            data = gemini.as_json(prompt, tier=gemini.SMART, default=None)
            if isinstance(data, dict) and data.get("files"):
                return _json.dumps(data)
            text = gemini.text(prompt, tier=gemini.SMART)
            return text or ""
        return _ask
    except Exception:
        return None


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Build → test → run on localhost → (deploy). Short string, never raises."""
    try:
        params = parameters or {}
        spec = str(params.get("spec") or "").strip()
        if not spec:
            return "Ki banabo — spec dao (jemon 'ekta todo dashboard banao')."
        from core import software_builder as _sb
        return _sb.build_and_run_text(
            spec,
            kind=str(params.get("kind") or ""),
            template=str(params.get("template") or ""),
            deploy=bool(params.get("deploy")),
            repo=str(params.get("repo") or ""),
            ask_fn=_ask_fn(),
            open_browser=bool(params.get("open_browser", True)))
    except Exception as e:
        return f"Software build korte parlam na: {e}"
