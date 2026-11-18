"""plugins/video_upload_browser.py — 📤 VIDEO UPLOAD via manual browser
control (Instagram / Facebook / YouTube).

Voice path for core/video_upload.py. The browser flow — NOT the Graph
API: Mark drives the user's logged-in Chrome and clicks like a human
(Create -> Select from computer -> caption -> Share/Post/Publish), with
a real file-input (Playwright set_input_files, no OS file picker).

Modes:
  * action "upload" (default, auto): Mark does the whole upload.
  * action "open": MANUAL MODE — open the upload page, the USER clicks in
    the real browser while Mark watches and narrates.
  * action "take_over": "tumi koro" — Mark takes the mouse from the
    current page and finishes the upload.
  * action "hand_back": "ami korbo" — hand the mouse back to the user.
  * action "limits": show the site's file size / length limits.

Slow work runs on a background thread: run() returns in seconds,
progress is reported live in the activity log. Never raises. Login is
required on the site (the user's own account, already logged in on
Chrome — Mark never sees or stores the site password).
"""
from __future__ import annotations

import threading

PLUGIN = {
    "name": "video_upload_browser",
    "description": (
        "Upload a video to Instagram, Facebook or YouTube THROUGH THE "
        "BROWSER (manual browser control — NOT the Graph API). Mark opens "
        "the user's logged-in Chrome and clicks like a human: Create -> "
        "Select from computer -> caption/title -> Share/Post/Publish. "
        "Modes: 'upload' (Mark does it all), 'open' (manual — the page "
        "opens and the USER clicks while Mark watches and narrates), "
        "'take_over' ('tumi koro' — Mark takes over from the current "
        "page), 'hand_back' ('ami korbo' — hand the mouse back). Login is "
        "required on the site (the user's own account in Chrome). Call "
        "when the user asks: Instagram/Facebook/YouTube-e video upload "
        "koro / reel dao / video-ta post koro (browser diye). Do NOT use "
        "for API uploads — those are instagram_upload_video / "
        "facebook_upload_video. Do NOT use for playing videos — that is "
        "youtube_play."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "site": {"type": "STRING",
                     "description": "Instagram, Facebook or YouTube."},
            "file_path": {"type": "STRING",
                          "description": "Local path of the video file to upload."},
            "caption": {"type": "STRING",
                        "description": "Caption for Instagram/Facebook (optional)."},
            "title": {"type": "STRING",
                      "description": "Title for YouTube (optional)."},
            "description": {"type": "STRING",
                            "description": "Description for YouTube (optional)."},
            "action": {"type": "STRING",
                       "description": "'upload' (default, auto), 'open' (manual mode), 'take_over', 'hand_back', 'limits'."},
        },
        "required": ["site"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "video_upload",
    "title": "📤 VIDEO UPLOAD — Instagram / Facebook / YouTube (browser)",
    "widget": "video_upload_browser",
    "fields": [],
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
        from core import video_upload as vu
    except Exception as e:
        return f"Video upload korte parlam na (core load hoy ni): {e}"
    params = parameters or {}
    site = str(params.get("site") or "").strip().lower()
    file_path = str(params.get("file_path") or "").strip()
    caption = str(params.get("caption") or "").strip()
    title = str(params.get("title") or "").strip()
    description = str(params.get("description") or "").strip()
    action = str(params.get("action") or "upload").strip().lower()

    if action == "limits":
        if site not in vu.SITES:
            return ("Limit dekhte site-ta bolo — Instagram, Facebook, na "
                    "YouTube? Instagram: reel 90 min / 4 GB. Facebook: "
                    "video 240 min / 10 GB. YouTube: 12 ghonta / 256 GB "
                    "(verified), unverified 15 min.")
        return f"📏 {vu.SITES[site]['label']} limit: {vu.site_limit(site)}"
    if action == "hand_back":
        try:
            return vu.hand_back()
        except Exception as e:
            return f"Hand-back korte parlam na: {e}"
    if action == "open":
        def _work_open():
            try:
                ok, msg = vu.open_upload_page(site)
                _log(player, msg)
            except Exception as e:
                _log(player, f"Page khulte giye error: {e}")
        threading.Thread(target=_work_open, daemon=True,
                         name="video-upload-open").start()
        return "🌐 Upload page khulchi — tumi nije click koro, ami dekhchi."
    if action == "take_over":
        if not file_path:
            return "Kon video upload korbo — file path dao."

        def _work_take():
            try:
                ok, msg = vu.take_over(site, file_path, caption, title,
                                       description,
                                       log_fn=lambda m: _log(player, m))
                _log(player, msg)
            except Exception as e:
                _log(player, f"Take-over-e error: {e}")
        threading.Thread(target=_work_take, daemon=True,
                         name="video-upload-takeover").start()
        return "👉 Thik ache, ami ekhan theke chalacchi — log-e dekho."

    # upload (default, auto)
    if site not in vu.SITES:
        return "Site-ta bolo — Instagram, Facebook, na YouTube?"
    if not file_path:
        return "Kon video upload korbo — file path dao."

    def _work_upload():
        try:
            ok, msg = vu.upload_video(site, file_path, caption, title,
                                      description,
                                      log_fn=lambda m: _log(player, m))
            _log(player, msg)
        except Exception as e:
            _log(player, f"Upload-e error: {e}")
    threading.Thread(target=_work_upload, daemon=True,
                     name="video-upload-auto").start()
    return (f"📤 {vu.SITES[site]['label']}-e upload shuru korlam — prottek "
            "step log-e dekhabe.")
