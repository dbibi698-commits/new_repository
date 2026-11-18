"""plugins/python_run.py — 🐍 PYTHON RUN: run Python code directly on this PC.

Mark IS Python, so this is the direct path: paste a snippet and it runs
here with the bundled Python (60 s default, output capped), or point at a
project folder and its main.py runs — venv + requirements.txt install
first, best-effort. Big projects are fine: no size cap on the PC.

The Plugin Settings overlay builds the "Run Python" box for this plugin
(widget "python_run" in PLUGIN_SETTINGS below) — code area + Run button,
output shown in the box. The tool itself is also callable by voice
("python run: ...") and from the Python Run agent card.

Safety: only the user's own code runs (pasted here, their own project
folder, or the paired phone's relay). Timeout + output cap on every run.
"""
from __future__ import annotations

PLUGIN = {
    "name": "python_run",
    "description": (
        "Run Python code directly on this PC — paste a snippet and it runs "
        "here with the bundled Python (60 s default, output capped), or "
        "run a whole project folder (venv + requirements.txt install, then "
        "its main.py). Call when the user asks: python code chalao/run koro, "
        "snippet chalao, project folder chalao, boro project run koro."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "code": {"type": "STRING",
                     "description": "Python code to run (snippet mode)."},
            "mode": {"type": "STRING",
                     "description": "'snippet' (default), 'project', "
                                    "'libraries' (installed packages list) "
                                    "or 'install' (one library)."},
            "folder": {"type": "STRING",
                       "description": "Project folder path (project mode)."},
            "entry": {"type": "STRING",
                      "description": "Entry file inside the folder "
                                     "(default main.py)."},
            "timeout": {"type": "NUMBER",
                        "description": "Timeout in seconds (snippet max 300, "
                                       "project max 900)."},
            "library": {"type": "STRING",
                        "description": "Library name to install "
                                       "(install mode, e.g. 'requests')."},
        },
        "required": [],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "python_run",
    "title": "🐍 RUN PYTHON — code likhe chalao",
    # Extra box the Plugin Settings overlay builds at the end of this
    # section: code area + Run Snippet / Run Project + output. The overlay
    # only knows the widget key; the box itself lives in gui/overlays.py.
    "widget": "python_run",
    "fields": [],
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Run a snippet or a project folder. Returns a short string,
    never raises."""
    try:
        params = parameters or {}
        mode = str(params.get("mode") or "snippet").strip().lower()
        timeout = params.get("timeout")
        try:
            timeout = int(timeout) if timeout is not None else None
        except Exception:
            timeout = None
        from core import python_run as _pr
        if mode == "libraries":
            return _pr.libraries_text()
        if mode == "install":
            lib = str(params.get("library") or "").strip()
            if not lib:
                return ("🐍 Library install — naam dao (jemon 'requests'). "
                        "Common: " + ", ".join(
                            l["name"] for l in _pr.COMMON_LIBRARIES))
            ok, note = _pr.install_library(lib)
            return note
        if mode == "project":
            folder = str(params.get("folder") or "").strip()
            entry = str(params.get("entry") or "main.py").strip()
            return _pr.run_project(folder, entry=entry,
                                   timeout=timeout or 300)
        code = str(params.get("code") or "")
        return _pr.run_snippet_text(code, timeout=timeout or 60)
    except Exception as e:
        return f"Python run korte parlam na: {e}"
