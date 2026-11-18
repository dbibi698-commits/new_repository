"""plugins/youtube_agent.py — 📺 YOUTUBE AGENT: search + play on Mark's
own video screen, like, comment. Wraps core/youtube_agent.py.

- play: search (needs a YouTube Data API key) or a direct URL -> the
  video plays on the HUD video screen (player.show_video) when a player
  is available, else in Chrome via the no-extension browser driver.
- like / comment: REAL YouTube Data API v3 calls. They need a FRESH
  OAuth access token (youtube_access_token, ~1 h). When the token is
  missing or expired the reply says plainly "YouTube login/token
  lagbe" and offers the OAuth flow — a like or a comment is NEVER
  faked. Never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "youtube_play",
    "description": (
        "YouTube agent — search + play a video on Mark's own video screen "
        "(HUD player, else Chrome), like a video, comment on a video. "
        "Like/comment need a fresh YouTube OAuth token; without one Mark "
        "says plainly 'login/token lagbe' and never fakes it. Call when "
        "the user says: YouTube-e ... chalao, video chalao, like dao, "
        "comment koro."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "play | search | like | comment | status"},
            "query": {"type": "STRING",
                      "description": "Video name / search text."},
            "url": {"type": "STRING",
                    "description": "Direct YouTube URL."},
            "video_id": {"type": "STRING",
                         "description": "Video id or URL (like/comment)."},
            "text": {"type": "STRING",
                     "description": "Comment text."},
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        p = parameters or {}
        action = str(p.get("action") or "play").strip().lower()
        from core import youtube_agent as yt
        if action == "search":
            hits, err = yt.search_videos(str(p.get("query") or ""), 5)
            if err:
                return err
            lines = [f"📺 YouTube — {len(hits)} ta pelam:"]
            for h in hits:
                lines.append(f"  • {h.get('title')} — {h.get('url')}")
            return "\n".join(lines)
        if action == "like":
            return yt.like_video(str(p.get("video_id") or p.get("url") or ""))
        if action == "comment":
            return yt.comment_video(
                str(p.get("video_id") or p.get("url") or ""),
                str(p.get("text") or ""))
        if action == "status":
            return yt.youtube_status()
        q = str(p.get("url") or p.get("query") or "").strip()
        if not q:
            return "Ki chalabo — video-r naam ba URL dao."
        return yt.play_video(q, player=player)
    except Exception as e:
        return f"YouTube chalate parlam na: {e}"

PLUGIN_SETTINGS = {
    "namespace": "youtube_agent",
    "title": "📺 VIDEO — Mark-er nijer video screen",
    "fields": [],
    # Extra box the Plugin Settings overlay builds at the end of this
    # section: what is playing now + play/pause + the YouTube token state
    # (like/comment need a fresh OAuth token — never faked). The overlay
    # only knows the widget key; the box itself lives in gui/overlays.py.
    "widget": "video_panel",
}
