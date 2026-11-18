"""plugins/utility_media.py — 🎬 MEDIA tools: Audio Converter, Video
Downloader. Thin voice wrapper over core/utility_tools.py. Never raises.
(YouTube play/like/comment live in plugins/youtube_agent.py.)
"""
from __future__ import annotations

PLUGIN = {
    "name": "utility_media",
    "description": (
        "Media tools — audio converter (ffmpeg: mp3/wav/ogg/m4a/flac) and "
        "video downloader (yt-dlp, PUBLIC videos only). Call when the user "
        "says: audio convert koro, video download koro."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "audio_convert | video_download"},
            "path": {"type": "STRING", "description": "Audio file path."},
            "fmt": {"type": "STRING", "description": "Target format: mp3 | wav | ogg | m4a | flac."},
            "url": {"type": "STRING", "description": "Public video URL."},
            "quality": {"type": "STRING", "description": "best | 720p."},
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        p = parameters or {}
        action = str(p.get("action") or "").strip().lower()
        from core import utility_tools as u
        if action == "audio_convert":
            return u.audio_convert(str(p.get("path") or ""),
                                   str(p.get("fmt") or "mp3"))
        if action == "video_download":
            return u.video_download(str(p.get("url") or ""),
                                    str(p.get("quality") or "best"))
        return ("Ki korbo — audio_convert ba video_download bolo.")
    except Exception as e:
        return f"Media tool chalate parlam na: {e}"
