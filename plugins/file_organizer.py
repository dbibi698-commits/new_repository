"""plugins/file_organizer.py — 🗂️ FILE ORGANIZER: folder sajano.

Sorts a folder's files into subfolders by type (Images, Documents,
Videos, Audio, Archives, Code, Other). DRY-RUN IS THE DEFAULT: the first
run only shows the preview — nothing moves until the user confirms.
Runs on a worker thread. Returns a short string, never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "file_organizer",
    "description": (
        "Organize a folder by file type into subfolders (Images, "
        "Documents, Videos, Audio, Archives, Code, Other). First run is "
        "always a dry-run preview — nothing moves until you confirm. Call "
        "when the user asks: folder sajao, downloads sajao, file gulo "
        "guchao."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "folder": {"type": "STRING",
                       "description": "Folder path (default: Downloads)."},
            "confirm": {"type": "BOOLEAN",
                        "description": "True = actually move the files "
                                       "(preview-er pore)."},
        },
        "required": [],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Preview (default) or organize for real. Short string, never raises."""
    try:
        params = parameters or {}
        from core import file_organizer as _fo
        from pathlib import Path as _Path
        folder = str(params.get("folder") or "").strip()
        if not folder:
            folder = str(_Path.home() / "Downloads")
        confirm = params.get("confirm")
        dry_run = confirm not in (True, 1, "1", "true", "True", "yes")
        return _fo.organize_text(folder, dry_run=dry_run)
    except Exception as e:
        return f"File organize korte parlam na: {e}"
