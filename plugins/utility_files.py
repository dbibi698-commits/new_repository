"""plugins/utility_files.py — 📁 FILE tools: File Search, Zip Tool,
Storage Analyzer, Disk Cleanup, Download Manager, Image Resizer,
Clipboard. Thin voice wrapper over core/utility_tools.py. Never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "utility_files",
    "description": (
        "File tools — file search by name, zip create/extract, storage "
        "analyzer (disk use + biggest folders), disk cleanup (old temp "
        "files to Recycle Bin), download manager (URL -> Downloads), image "
        "resizer, clipboard get/set. Call when the user says: file khujo, "
        "zip banao/kholo, storage dekhao, disk cleanup, download koro, "
        "image resize koro, clipboard dekhao."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "search | zip_create | zip_extract | storage | cleanup | cleanup_confirm | download | resize | clipboard_get | clipboard_set"},
            "query": {"type": "STRING", "description": "File name to search."},
            "folder": {"type": "STRING", "description": "Folder to search in (default: home)."},
            "source": {"type": "STRING", "description": "File/folder path (zip, resize)."},
            "dest": {"type": "STRING", "description": "Destination path (zip)."},
            "url": {"type": "STRING", "description": "URL to download."},
            "name": {"type": "STRING", "description": "Download file name."},
            "width": {"type": "NUMBER", "description": "New width in px (resize)."},
            "height": {"type": "NUMBER", "description": "New height in px (0 = keep aspect)."},
            "text": {"type": "STRING", "description": "Text to put on the clipboard."},
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        p = parameters or {}
        action = str(p.get("action") or "").strip().lower()
        from core import utility_tools as u
        if action == "search":
            return u.file_search(str(p.get("query") or ""),
                                 str(p.get("folder") or ""))
        if action == "zip_create":
            return u.zip_tool("create", str(p.get("source") or ""),
                              str(p.get("dest") or ""))
        if action == "zip_extract":
            return u.zip_tool("extract", str(p.get("source") or ""),
                              str(p.get("dest") or ""))
        if action == "storage":
            return u.storage_analyzer(str(p.get("folder") or ""))
        if action == "cleanup":
            return u.disk_cleanup(dry_run=True)
        if action == "cleanup_confirm":
            return u.disk_cleanup(dry_run=False)
        if action == "download":
            return u.download_file(str(p.get("url") or ""),
                                   str(p.get("name") or ""))
        if action == "resize":
            return u.image_resize(str(p.get("source") or ""),
                                  int(p.get("width") or 800),
                                  int(p.get("height") or 0))
        if action == "clipboard_get":
            return u.clipboard("get")
        if action == "clipboard_set":
            return u.clipboard("set", str(p.get("text") or ""))
        return ("Ki korbo — search, zip_create, zip_extract, storage, "
                "cleanup, download, resize, clipboard_get-er ekta bolo.")
    except Exception as e:
        return f"File tool chalate parlam na: {e}"
