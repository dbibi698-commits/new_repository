"""plugins/file_edit.py — ✏️ FILE EDIT: edit any PC file by path + patch.
Shows a diff first, keeps a .bak backup, writes only when confirmed.
Wraps core/file_edit.py. Never touches api_keys.json / jarvis_link.json
(the module refuses them). Never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "file_edit",
    "description": (
        "Edit a file on the PC — replace one exact piece of text, or append "
        "lines. Shows a diff first and keeps a .bak backup; writes only "
        "when confirmed. Call when the user says: file edit koro, file-ta "
        "bodlao, file-e likho. Never edits api_keys.json or jarvis_link.json."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "preview | edit | append | read"},
            "path": {"type": "STRING", "description": "File path."},
            "old": {"type": "STRING", "description": "Exact old text to replace."},
            "new": {"type": "STRING", "description": "New text."},
            "text": {"type": "STRING", "description": "Lines to append."},
            "confirmed": {"type": "BOOLEAN",
                          "description": "True after the user confirmed the diff."},
            "start": {"type": "NUMBER", "description": "First line to read (read)."},
            "lines": {"type": "NUMBER", "description": "How many lines to read."},
        },
        "required": ["action", "path"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        p = parameters or {}
        action = str(p.get("action") or "preview").strip().lower()
        from core import file_edit as fe
        path = str(p.get("path") or "")
        if action == "preview":
            return fe.preview_diff(path, str(p.get("old") or ""),
                                   str(p.get("new") or ""))
        if action == "edit":
            return fe.edit_file(path, str(p.get("old") or ""),
                                str(p.get("new") or ""),
                                confirmed=bool(p.get("confirmed")))
        if action == "append":
            return fe.append_file(path, str(p.get("text") or ""),
                                  confirmed=bool(p.get("confirmed")))
        if action == "read":
            return fe.read_snippet(path, int(p.get("start") or 1),
                                   int(p.get("lines") or 20))
        return ("Ki korbo — preview, edit, append, read-er ekta bolo.")
    except Exception as e:
        return f"File edit korte parlam na: {e}"
