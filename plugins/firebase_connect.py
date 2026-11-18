"""plugins/firebase_connect.py — 🔥 Firebase Connect: link a Firebase
project to an app/website, from the PC.

Drives the user's own logged-in Chrome (no extension) to
console.firebase.google.com — create a project, open Project Settings,
download google-services.json / the web config into the project folder —
or uses the firebase-tools CLI when it is installed. The browser work
takes a minute or two, so run() starts it on a worker thread and returns
at once; the result is written to the activity log when it finishes.
Needs the user's Google login in Chrome — Mark never sees the password.
"""
from __future__ import annotations

import threading

PLUGIN = {
    "name": "firebase_connect",
    "description": (
        "Connect a Firebase project to an app or website: open the Firebase "
        "console in the user's own logged-in Chrome (no extension), create "
        "or pick a project, and download the config (google-services.json "
        "for Android, web config for a website) into the project folder. "
        "Call when the user says: Firebase connect koro, Firebase project "
        "banao, Firebase config dao, app-er sathe Firebase lagao. Needs "
        "Chrome with the user logged into Google; the config folder is "
        "Documents/firebase-config by default."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "project_folder": {"type": "STRING",
                               "description": "Folder to save the Firebase config into (default Documents/firebase-config)."},
            "project_id": {"type": "STRING",
                           "description": "Existing Firebase project id (optional — when given, the CLI path is used if the CLI is installed)."},
            "platform": {"type": "STRING",
                         "description": "web | android | ios (default web)."},
        },
        "required": [],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "firebase",
    "title": "🔥 FIREBASE CONNECT",
    "fields": [
        {"key": "project_folder", "type": "text",
         "label": "Project folder (Firebase config ekhane save hobe)",
         "placeholder": "e.g. C:\\Users\\you\\Documents\\my-app"},
        {"key": "default_project_id", "type": "text",
         "label": "Default Firebase project id (optional)",
         "placeholder": "e.g. my-app-12345"},
    ],
}


def _run_flow(project_folder: str, project_id: str, platform: str,
              player=None):
    """Worker thread: run the flow, log the plain-words result. Never raises."""
    try:
        from core import firebase_connect as _fb
        if project_id:
            ok, msg = _fb.sdkconfig_via_cli(project_id, platform, project_folder)
            if ok:
                if player:
                    try:
                        player.write_log(f"JARVIS: {msg}")
                    except Exception:
                        pass
                return
        ok, msg = _fb.connect_flow(project_folder, project_id, platform)
    except Exception as e:
        ok, msg = False, f"Firebase connect korte parlam na: {e}"
    if player:
        try:
            player.write_log(f"JARVIS: {msg}")
        except Exception:
            pass


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Start the Firebase connect flow in the background. Never raises."""
    try:
        from pathlib import Path as _Path
        params = parameters if isinstance(parameters, dict) else {}
        folder = str(params.get("project_folder") or "").strip()
        if not folder:
            try:
                from memory.config_manager import get_plugin_config
                folder = str((get_plugin_config("firebase") or {})
                             .get("project_folder") or "").strip()
            except Exception:
                folder = ""
        if not folder:
            folder = str(_Path.home() / "Documents" / "firebase-config")
        project_id = str(params.get("project_id") or "").strip()
        if not project_id:
            try:
                from memory.config_manager import get_plugin_config
                project_id = str((get_plugin_config("firebase") or {})
                                 .get("default_project_id") or "").strip()
            except Exception:
                project_id = ""
        platform = str(params.get("platform") or "web").strip().lower()
        if platform not in ("web", "android", "ios"):
            platform = "web"
        threading.Thread(target=_run_flow,
                         args=(folder, project_id, platform, player),
                         daemon=True).start()
        msg = (f"⏳ Firebase connect korchi — Chrome-e console khule config "
               f"{folder}-e namachhi, hole activity log-e janabo.")
        if player:
            try:
                player.write_log(f"JARVIS: {msg}")
            except Exception:
                pass
        return msg
    except Exception:
        return "Firebase connect korte parlam na — kichu ekta gondogol holo."
