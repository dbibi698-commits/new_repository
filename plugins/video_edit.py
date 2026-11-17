"""plugins/video_edit.py — trim / cut / merge / text / thumbnail / probe.

One tool, one `action` argument, dispatching to core/video_edit.py
(ffmpeg). Runs on a worker thread — never touches Qt (see AGENTS.md).
Returns a short string, never raises.

ffmpeg is downloaded on first use on the PC (gyan.dev static build, into
<Mark folder>/ffmpeg/) — it is NOT bundled with the app. If ffmpeg is not
there yet, the tool says so plainly instead of failing silently.
"""
from __future__ import annotations

import json

PLUGIN = {
    "name": "video_edit",
    "description": (
        "Edit a video: trim a clip (start-end), cut out and keep only listed "
        "segments, merge several videos into one, burn text onto a video, "
        "save a thumbnail frame, or get a video's duration and resolution. "
        "Call when the user asks: video trim/cut/merge koro, video-te text "
        "bosau, thumbnail nao, video-r info dao. Needs ffmpeg — it downloads "
        "automatically on first use on the PC."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "What to do: trim, cut, merge, add_text, "
                                      "thumbnail, probe, or ffmpeg_status."},
            "input": {"type": "STRING",
                      "description": "Input video file path (trim/cut/add_text/"
                                     "thumbnail/probe). For merge, leave empty "
                                     "and use inputs."},
            "inputs": {"type": "STRING",
                       "description": "For merge: video file paths separated "
                                      "by commas."},
            "output": {"type": "STRING",
                       "description": "Output file path (trim/cut/merge/add_text/"
                                      "thumbnail)."},
            "start": {"type": "STRING",
                      "description": "Start time in seconds or HH:MM:SS "
                                     "(trim/thumbnail)."},
            "end": {"type": "STRING",
                    "description": "End time in seconds or HH:MM:SS (trim)."},
            "segments": {"type": "STRING",
                         "description": "For cut: JSON list of [start, end] "
                                        "pairs, e.g. [[0, 10], [20, 30]] — "
                                        "seconds or HH:MM:SS."},
            "text": {"type": "STRING",
                     "description": "Text to burn onto the video (add_text)."},
            "at": {"type": "STRING",
                   "description": "Time for the thumbnail frame, seconds or "
                                  "HH:MM:SS (thumbnail)."},
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Dispatch `action` to core/video_edit.py. Short string, never raises."""
    try:
        from core import video_edit as _ve
    except Exception as e:
        return f"Video edit load holo na: {e}"
    try:
        params = parameters or {}
        action = str(params.get("action") or "").strip().lower()
        inp = params.get("input") or ""
        out = params.get("output") or ""
        if action == "trim":
            ok, msg = _ve.trim(inp, params.get("start"), params.get("end"), out)
        elif action == "cut":
            segs = params.get("segments") or ""
            if isinstance(segs, str):
                try:
                    segs = json.loads(segs)
                except Exception:
                    ok, msg = False, ("segments JSON-ta thik na — e.g. "
                                      "[[0, 10], [20, 30]] dao.")
                    segs = None
            if segs is not None:
                ok, msg = _ve.cut(inp, segs, out)
        elif action == "merge":
            raw = params.get("inputs") or ""
            if isinstance(raw, str):
                files = [p.strip() for p in raw.split(",") if p.strip()]
            else:
                files = list(raw)
            ok, msg = _ve.merge(files, out)
        elif action == "add_text":
            ok, msg = _ve.add_text(inp, params.get("text") or "", out)
        elif action == "thumbnail":
            ok, msg = _ve.thumbnail(inp, params.get("at"), out)
        elif action == "probe":
            ok, msg = _ve.probe(inp)
        elif action == "ffmpeg_status":
            msg = _ve.ffmpeg_status()
            ok = True
        elif not action:
            ok, msg = False, ("Ki korbo — action dao: trim, cut, merge, "
                              "add_text, thumbnail, probe, ba ffmpeg_status.")
        else:
            ok, msg = False, (f"'{action}' bujhlam na — action trim, cut, "
                              "merge, add_text, thumbnail, probe, ba "
                              "ffmpeg_status-er ekta hobe.")
    except Exception as e:
        ok, msg = False, f"Video edit failed: {e}"
    if player:
        try:
            player.write_log(f"JARVIS: {msg}")
        except Exception:
            pass
    return msg
