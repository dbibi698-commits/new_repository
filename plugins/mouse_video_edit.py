"""plugins/mouse_video_edit.py — ✂️ MOUSE-DRIVEN VIDEO EDITING like a
real human (CapCut / Premiere / Clipchamp / DaVinci) + ffmpeg fast ops.

Voice path for core/mouse_video_edit.py. The rule: small jobs = ffmpeg
(trim/cut/merge/text/thumbnail — fast, reliable); big creative editing =
mouse in the editor app (split, text, transitions/effects, export),
step-verified after every click. The UI always says which path ran.
  * operation "trim" / "cut" / "text" / "thumbnail": ffmpeg path.
  * operation "split" / "transition" / "effect" / "edit": mouse path.
  * operation "upload": edit first, then upload the edited video to
    Instagram/Facebook/YouTube via the browser upload flow.

Slow work runs on a background thread: run() returns in seconds,
progress is reported live in the activity log. Never raises. An editor
app must be installed for the mouse path — if none is installed, the
message says so plainly and offers the ffmpeg path.
"""
from __future__ import annotations

import threading

PLUGIN = {
    "name": "mouse_video_edit",
    "description": (
        "Edit a video like a real human with the mouse in a real editor "
        "app (CapCut first, then Premiere Pro / Clipchamp / DaVinci "
        "Resolve — whichever is installed), or fast with ffmpeg for small "
        "jobs. Operations: 'trim', 'cut', 'text', 'thumbnail' (ffmpeg — "
        "fast); 'split', 'transition', 'effect', 'edit' (mouse in the "
        "editor app — step-verified after every click); 'upload' (edit "
        "then upload to Instagram/Facebook/YouTube via the browser). "
        "Call when the user asks: video-ta mouse diye edit koro / CapCut-e "
        "trim koro / text lagao / export koro. Do NOT use for the ffmpeg "
        "batch ops directly — those are video_edit."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "video": {"type": "STRING",
                      "description": "Local path of the video file to edit."},
            "operation": {"type": "STRING",
                          "description": "'trim', 'cut', 'text', 'thumbnail', 'split', 'transition', 'effect', 'edit', 'upload'."},
            "text": {"type": "STRING",
                     "description": "Text to add on the video (for 'text' / 'edit')."},
            "editor": {"type": "STRING",
                       "description": "Editor app to use (CapCut, Premiere Pro, Clipchamp, DaVinci Resolve) — empty = auto-detect."},
            "site": {"type": "STRING",
                     "description": "Upload site for operation 'upload': Instagram, Facebook or YouTube."},
            "caption": {"type": "STRING",
                        "description": "Caption for the upload (operation 'upload')."},
        },
        "required": ["video", "operation"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "mouse_video_edit",
    "title": "✂️ MOUSE VIDEO EDITOR — CapCut / Premiere / Clipchamp",
    "widget": "mouse_video_edit",
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
        from core import mouse_video_edit as mve
    except Exception as e:
        return f"Video edit korte parlam na (core load hoy ni): {e}"
    params = parameters or {}
    video = str(params.get("video") or "").strip()
    operation = str(params.get("operation") or "").strip().lower()
    text = str(params.get("text") or "").strip()
    editor = str(params.get("editor") or "").strip()
    site = str(params.get("site") or "").strip()
    caption = str(params.get("caption") or "").strip()

    if action := str(params.get("action") or "").strip().lower():
        if action == "status":
            try:
                return mve.editor_status_text()
            except Exception as e:
                return f"Status dekhte parlam na: {e}"
    if not video:
        return "Kon video edit korbo — file path dao."
    if not operation:
        return ("Ki korbo bolo — trim / cut / text / thumbnail (ffmpeg) "
                "na split / transition / effect / edit (mouse)?")

    def _work():
        try:
            if operation == "upload":
                ok, msg = mve.edit_then_upload(
                    video, ["trim"], site or "instagram", caption=caption,
                    text=text, log_fn=lambda m: _log(player, m))
            elif operation in ("trim", "cut", "text", "thumbnail"):
                ok, msg = mve.ffmpeg_edit(video, operation, text=text)
            else:
                ops = [operation] if operation != "edit" else \
                    ["split", "text", "transition"]
                ok, msg = mve.mouse_edit(
                    video, ops, text=text, editor=editor,
                    log_fn=lambda m: _log(player, m))
            _log(player, msg)
        except Exception as e:
            _log(player, f"Video edit-e error: {e}")
    threading.Thread(target=_work, daemon=True,
                     name="mouse-video-edit").start()
    return (f"✂️ Video edit shuru korlam ({operation}) — kon path-e "
            "cholche (ffmpeg na mouse) log-e dekhabe.")
