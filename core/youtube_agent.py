"""core/youtube_agent.py — 📺 YOUTUBE AGENT + Mark's own VIDEO SCREEN.

- youtube_search is REUSED from core/connectors.py (needs a YouTube Data
  API key — honest when missing).
- youtube_play: search (or a direct URL) -> resolve a stream URL with
  yt-dlp -> play it on MARK'S OWN video screen in the HUD
  (player.show_video) when a player is available, else open the video
  in Chrome via the no-extension browser driver. Never fakes playback.
- youtube_like / youtube_comment: REAL YouTube Data API v3 calls that
  need a FRESH OAuth access token (youtube_access_token, ~1 h). The
  saved token EXPIRED before (real 401) — when it is missing or
  expired the card says plainly "YouTube login/token lagbe" and offers
  the OAuth Playground flow. A like or a comment is NEVER faked.
- current_video() / video_panel_text(): what is playing now, for the
  📺 VIDEO panel (Plugin Settings + agent card).

Nothing here imports Qt. All functions return short strings and never
raise.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from datetime import datetime

from memory.config_manager import get_plugin_config, save_plugin_config

_NS = "youtube_agent"

_YT_API = "https://www.googleapis.com/youtube/v3"
_OAUTH_HELP = (
    "YouTube login/token lagbe — Like/Comment korte Google OAuth "
    "access token dorkar (API key diye hobe na). Plugin Settings > "
    "🔗 CONNECTORS-e 'YouTube OAuth access token' field-e token dao — "
    "Google OAuth Playground (developers.google.com/oauthplayground) "
    "theke nao: scope https://www.googleapis.com/auth/youtube, tarpor "
    "'Exchange tokens'. Token ~1 ghonta cholbe; 401 mane notun nao."
)


# ── state ────────────────────────────────────────────────────────────────────

def _state() -> dict:
    try:
        return dict(get_plugin_config(_NS) or {})
    except Exception:
        return {}


def _save_state(st: dict) -> None:
    try:
        save_plugin_config(_NS, dict(st))
    except Exception:
        pass


def current_video() -> dict:
    """The video playing now (or {} when nothing)."""
    try:
        return dict(_state().get("current") or {})
    except Exception:
        return {}


def _set_current(video_id: str, title: str, url: str, source: str) -> None:
    st = _state()
    st["current"] = {"video_id": video_id, "title": title, "url": url,
                     "source": source, "at": datetime.now().isoformat(
                         timespec="seconds")}
    _save_state(st)


def video_panel_text() -> str:
    """Status text for the 📺 VIDEO panel."""
    try:
        cur = current_video()
        from core import connectors as _c
        tok = _c._token("youtube_access_token", None)
        lines = ["📺 VIDEO — Mark-er nijer screen:"]
        if cur:
            lines.append(f"  • Chalche: {cur.get('title') or cur.get('url')}")
            lines.append(f"  • {cur.get('url')}")
            lines.append(f"  • Kothay: {cur.get('source')} • "
                         f"{cur.get('at', '')}")
        else:
            lines.append("  • Ekhon kichu cholche na — YouTube card theke "
                         "ba voice-e 'YouTube-e ... chalao' bolo.")
        lines.append("  • Like/Comment: "
                     + ("✅ token ache" if tok else
                        "❌ token nei — login lagbe"))
        lines.append("  • Note: YouTube video HUD-e play hoy (show_video) "
                     "ba Chrome-e khule — kono fake like/comment hobe na.")
        return "\n".join(lines)
    except Exception as e:
        return f"Video panel dekhte parlam na: {e}"


def youtube_status() -> str:
    """One-line status for the YouTube agent card action."""
    try:
        cur = current_video()
        from core import connectors as _c
        tok = _c._token("youtube_access_token", None)
        bits = ["📺 YouTube agent"]
        if cur:
            bits.append(f"• chalche: {cur.get('title') or cur.get('url')}")
        bits.append("• Like/Comment token: "
                    + ("ache ✅" if tok else "nei ❌ — login lagbe"))
        return " ".join(bits)
    except Exception as e:
        return f"YouTube status dekhte parlam na: {e}"


# ── search / resolve ─────────────────────────────────────────────────────────

def _extract_video_id(text: str) -> str:
    """Pull a YouTube video id out of a URL or a bare id. '' if none."""
    t = str(text or "").strip()
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{11})", t)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", t):
        return t
    return ""


def search_videos(query: str, max_results: int = 5) -> tuple[list[dict], str]:
    """Search via connectors.youtube_search. Returns ([{id,title,url}], err).
    Never raises. Falls back to a plain watch-URL search when no API key."""
    try:
        from core import connectors as _c
        key = _c._token("youtube_api_key", None)
        if not key:
            return [], ("YouTube search-er jonno YouTube Data API key "
                        "lagbe (CONNECTORS-e 'YouTube API key'). Key na "
                        "thakle sudhu direct video URL chalano jabe.")
        res = _c.youtube_search(None, query, max_results=max_results)
        if isinstance(res, str) and res.startswith("YouTube API key"):
            return [], res
        if isinstance(res, str) and ("Error" in res or "holo na" in res):
            return [], res
        # youtube_search returns a formatted string; parse video ids out.
        ids = re.findall(r"(?:youtu\.be/|watch\?v=)([A-Za-z0-9_-]{11})", res or "")
        titles = re.findall(r"•\s*(.+?)\s*\n", res or "")
        out = []
        for i, vid in enumerate(dict.fromkeys(ids)):
            title = titles[i].strip() if i < len(titles) else vid
            out.append({"id": vid, "title": title,
                        "url": f"https://youtu.be/{vid}"})
        if not out and ids:
            out = [{"id": v, "title": v, "url": f"https://youtu.be/{v}"}
                   for v in dict.fromkeys(ids)]
        if not out:
            return [], (f"YouTube-e '{query}' — kichu pelam na. "
                        f"(API reply: {str(res)[:150]})")
        return out, ""
    except Exception as e:
        return [], f"YouTube search korte parlam na: {e}"


def resolve_stream_url(watch_url: str, timeout: int = 30) -> str:
    """yt-dlp -> direct stream URL Qt can play. '' when unavailable.
    Never raises."""
    try:
        if not shutil.which("yt-dlp"):
            return ""
        r = subprocess.run(
            ["yt-dlp", "-g", "-f",
             "best[height<=720]/best", watch_url],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=max(10, int(timeout or 30)))
        if r.returncode != 0:
            return ""
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.startswith("http"):
                return line
        return ""
    except Exception:
        return ""


# ── play ─────────────────────────────────────────────────────────────────────

def play_video(query_or_url: str, player=None, open_browser_fn=None) -> str:
    """Play a YouTube video. Real playback only:
    1. direct URL -> that video; else search (needs API key) -> first hit
    2. yt-dlp resolves a stream URL -> player.show_video (HUD, Mark's own
       screen) when a player is given
    3. else open the watch URL in Chrome via the no-extension browser driver
    Returns a short status string. Never raises."""
    try:
        q = str(query_or_url or "").strip()
        if not q:
            return "Ki chalabo — video-r naam ba URL dao."
        vid = _extract_video_id(q)
        title = vid
        if vid:
            url = f"https://www.youtube.com/watch?v={vid}"
        else:
            hits, err = search_videos(q, max_results=5)
            if err or not hits:
                return err or "Video pelam na."
            vid, title, url = (hits[0]["id"], hits[0]["title"],
                               hits[0]["url"])
        # 1) HUD player first — Mark's own video screen.
        if player is not None:
            try:
                stream = resolve_stream_url(url)
                src = stream or url
                player.show_video(src, title)
                _set_current(vid, title, url,
                             "HUD video screen" if stream else
                             "HUD video screen (direct URL)")
                return (f"📺 Chalacchi: {title} — Mark-er nijer video "
                        f"screen-e. (Pause/Seek HUD-ei pabe.)")
            except Exception:
                pass
        # 2) Chrome via the no-extension browser driver.
        try:
            from core import browser_driver as _bd
            driver, _backend, _msg = _bd.ensure_driver(auto_install=False)
            if driver is not None:
                ok, _m = driver.navigate(url)
                if ok:
                    _set_current(vid, title, url, "Chrome (browser driver)")
                    return (f"📺 Chalacchi: {title} — Chrome-e khullam "
                            f"(browser driver). HUD-e dekhte 'YouTube' card-er "
                            f"Play button chapo.")
        except Exception:
            pass
        if open_browser_fn is not None:
            try:
                open_browser_fn(url)
                _set_current(vid, title, url, "browser")
                return f"📺 Chalacchi: {title} — browser-e khullam."
            except Exception:
                pass
        _set_current(vid, title, url, "link")
        return (f"📺 Video: {title} — {url}\n"
                f"(HUD ba Chrome khulte parlam na — link-ta khule dekho.)")
    except Exception as e:
        return f"YouTube chalate parlam na: {e}"


# ── like / comment — real API, never faked ───────────────────────────────────

def _oauth_token() -> str:
    try:
        from core import connectors as _c
        return str(_c._token("youtube_access_token", None) or "")
    except Exception:
        return ""


def _api_post(path: str, payload: dict) -> tuple[int, dict, str]:
    """POST to the YouTube Data API. Returns (status, data, err)."""
    try:
        tok = _oauth_token()
        if not tok:
            return 0, {}, "no-token"
        from core import connectors as _c
        return _c._req("POST", f"{_YT_API}{path}",
                       headers={"Authorization": f"Bearer {tok}",
                                "Content-Type": "application/json"},
                       payload=payload)
    except Exception as e:
        return 0, {}, str(e)


def like_video(video_id: str) -> str:
    """Real Like via videos.rate. Missing/expired token -> honest message.
    Never fakes a like. Never raises."""
    try:
        vid = _extract_video_id(video_id) or str(video_id or "").strip()
        if not vid:
            return "Konta video like korbo — video id/URL dao."
        if not _oauth_token():
            return ("❌ Like holo na — " + _OAUTH_HELP)
        st, _data, err = _api_post(f"/videos/rate?rating=like&id={vid}", {})
        if st == 204:
            return f"👍 Like dilam: https://youtu.be/{vid}"
        if st == 401:
            return ("❌ Like holo na — YouTube token EXPIRED (401). "
                    "Notun token nao (OAuth Playground), tarpor abar bolo. "
                    "Fake like deini.")
        return (f"❌ Like holo na — YouTube bollo HTTP {st or '?'}: "
                f"{str(err)[:200]}")
    except Exception as e:
        return f"Like dite parlam na: {e}"


def comment_video(video_id: str, text: str) -> str:
    """Real comment via commentThreads.insert. Missing/expired token ->
    honest message. Never fakes a comment. Never raises."""
    try:
        vid = _extract_video_id(video_id) or str(video_id or "").strip()
        txt = str(text or "").strip()
        if not vid:
            return "Konta video-te comment korbo — video id/URL dao."
        if not txt:
            return "Comment-ta ki likhbo — text dao."
        if not _oauth_token():
            return ("❌ Comment holo na — " + _OAUTH_HELP)
        payload = {"snippet": {"videoId": vid,
                               "topLevelComment": {"snippet": {
                                   "textOriginal": txt}}}}
        st, data, err = _api_post("/commentThreads?part=snippet", payload)
        if st in (200, 201):
            cid = str((data or {}).get("id") or "")
            return (f"💬 Comment dilam: https://youtu.be/{vid}"
                    + (f" (id {cid[:20]})" if cid else ""))
        if st == 401:
            return ("❌ Comment holo na — YouTube token EXPIRED (401). "
                    "Notun token nao (OAuth Playground), tarpor abar bolo. "
                    "Fake comment deini.")
        return (f"❌ Comment holo na — YouTube bollo HTTP {st or '?'}: "
                f"{str(err)[:200]}")
    except Exception as e:
        return f"Comment korte parlam na: {e}"
