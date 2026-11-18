"""plugins/app_editor.py — 🖥️ ALL-APPLICATION EDITING (App Editor).

Voice path for core/mouse_video_edit.app_editor. Open ANY desktop app by
name and drive it with clicks + typing: photo editing (Photos/Paint),
document editing (Word/Notepad — open, type, edit, save), any app's UI.
Every step is verified after it runs; a failed step names itself and the
run stops — never click blindly.

Slow work runs on a background thread: run() returns in seconds,
progress is reported live in the activity log. Never raises. The app
must be installed on the PC — if it is not there, the message says so
plainly.
"""
from __future__ import annotations

import threading

PLUGIN = {
    "name": "app_editor",
    "description": (
        "Open ANY desktop app by name and drive it with clicks + typing, "
        "like a human: photo editing (Photos/Paint), document editing "
        "(Word/Notepad — open, type, edit, save), any app's UI. Give "
        "app_name and the text to type (optional). Every step is verified "
        "after it runs. Call when the user asks: Notepad khule ... likho / "
        "Word-e ... likho / Paint kholo / kono app khule kaj koro. Do NOT "
        "use for video editing — that is mouse_video_edit."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "app_name": {"type": "STRING",
                         "description": "App name to open (e.g. Notepad, Word, Paint, Photos)."},
            "text": {"type": "STRING",
                     "description": "Text to type into the app after it opens (optional)."},
        },
        "required": ["app_name"],
    },
}


def _log(player, text: str) -> None:
    if player is None:
        return
    try:
        player.write_log(text)
    except Exception:
        pass


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        from core import mouse_video_edit as mve
    except Exception as e:
        return f"App Editor korte parlam na (core load hoy ni): {e}"
    params = parameters or {}
    app_name = str(params.get("app_name") or "").strip()
    text = str(params.get("text") or "").strip()
    if not app_name:
        return "Kon app khulbo bolo — naam dao (jemon: Notepad, Word, Paint)."

    actions = []
    if text:
        actions.append({"label": "Text likhlam", "kind": "type",
                        "text": text})

    def _work():
        try:
            ok, msg = mve.app_editor(app_name, actions,
                                     log_fn=lambda m: _log(player, m))
            _log(player, msg)
        except Exception as e:
            _log(player, f"App Editor-e error: {e}")
    threading.Thread(target=_work, daemon=True,
                     name="app-editor").start()
    return f"🖥️ {app_name} khulchi — result log-e dekhabe."
