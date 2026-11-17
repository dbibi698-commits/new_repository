"""
core/connectors.py — "🔗 Connectors": GitHub, WhatsApp, YouTube, Facebook,
Instagram, Google Drive — one requests-based module, no new dependencies
(`requests` is already in requirements.txt).

Tokens and keys live in config/api_keys.json under plugin_config["connectors"]
through memory/config_manager.py — never in this file, never in code, never
in the session log. Every function returns a short human-readable string and
never raises, so a tool call can hand the result straight to the user.

Honest limits, said up front because the user will hit them:
  * WhatsApp: the Meta API only sends from a WhatsApp BUSINESS number through
    a Meta app. A personal WhatsApp number cannot send via API at all.
  * YouTube: search + video details work with an API key. UPLOAD needs an
    OAuth access token (youtube_access_token, ~1h — Google OAuth Playground)
    and uses the resumable upload API. A plain API key can NEVER upload.
  * Instagram: posting needs a business/creator account linked to a Facebook
    Page, and a PUBLIC video URL — the API cannot take a local file. Video
    upload uses the container flow (create → poll until FINISHED → publish).
  * Facebook: video upload needs a Page token + Page id and uses the Graph
    Video resumable session flow (start → transfer chunks → finish).
  * Google Drive: needs an OAuth access token (Google OAuth Playground gives
    one). It expires in about an hour; a 401 means "notun token dao".
  * GitHub: a fine-grained personal access token (github.com/settings/tokens)
    with Contents read/write on the repos you want to touch.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import time

try:
    import requests as _requests
except Exception:  # pragma: no cover - requirements.txt lists it
    _requests = None

try:
    from memory.config_manager import get_plugin_config, save_plugin_config
except Exception:  # pragma: no cover - never on a real install
    def get_plugin_config(namespace: str) -> dict:  # type: ignore
        return {}

    def save_plugin_config(namespace: str, values: dict) -> None:  # type: ignore
        pass

_NS = "connectors"
_TIMEOUT = 15

_GH = "https://api.github.com"
_FB = "https://graph.facebook.com/v18.0"
_YT = "https://www.googleapis.com/youtube/v3"
_DRIVE = "https://www.googleapis.com/drive/v3"
_DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"


# ── config ───────────────────────────────────────────────────────────────────

def _cfg() -> dict:
    try:
        return get_plugin_config(_NS)
    except Exception:
        return {}


def _save(**values) -> None:
    try:
        save_plugin_config(_NS, values)
    except Exception:
        pass


def _token(key: str, given: str | None) -> str:
    """Explicit argument wins; otherwise the saved token for `key`."""
    if given and str(given).strip():
        return str(given).strip()
    return str(_cfg().get(key, "") or "").strip()


def get_token(key: str) -> str:
    """Stored token for `key` ("" when unset). For main.py's build_apk."""
    return str(_cfg().get(key, "") or "").strip()


def github_dispatch_workflow(token: str | None, owner: str, repo: str,
                             workflow: str, ref: str = "main") -> str:
    """Dispatch a GitHub Actions workflow (e.g. an APK build). 204 = queued."""
    tok = _token("github_token", token)
    if not tok:
        return "GitHub token set kora nei — age `github_connect` diye token dao."
    owner, repo, workflow = (owner or "").strip(), (repo or "").strip(), (workflow or "").strip()
    if not owner or not repo or not workflow:
        return "owner, repo ar workflow file — tintei lagbe."
    st, _data, err = _req(
        "POST", f"{_GH}/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches",
        headers={"Authorization": f"Bearer {tok}",
                 "Accept": "application/vnd.github+json"},
        payload={"ref": ref or "main"})
    if st == 204:
        return (f"✅ GitHub Actions-e build dispatch holo — "
                f"https://github.com/{owner}/{repo}/actions — "
                f"koyek minute pore okhane APK artifact pabe.")
    return _err("GitHub", st, err)


# ── HTTP ─────────────────────────────────────────────────────────────────────

def _req(method: str, url: str, headers: dict | None = None,
         params: dict | None = None, payload: dict | None = None,
         files: dict | None = None) -> tuple[int, dict | None, str]:
    """(status, parsed-json-or-None, error-string). Never raises."""
    if _requests is None:
        return 0, None, "requests install kora nei — `pip install requests` dao."
    try:
        r = _requests.request(method, url, headers=headers or {}, params=params,
                              json=payload, files=files, timeout=_TIMEOUT)
    except Exception as e:
        return 0, None, f"network error: {e}"
    try:
        data = r.json()
    except Exception:
        data = None
    if r.status_code >= 400:
        msg = ""
        if isinstance(data, dict):
            msg = str(data.get("message") or data.get("error", {}).get("message", "")
                      or data.get("error", "") or "")
        if not msg:
            msg = r.text[:200]
        return r.status_code, data, msg or f"HTTP {r.status_code}"
    return r.status_code, data, ""


def _err(service: str, status: int, err: str) -> str:
    if status == 401:
        return (f"⚠️ {service}: token-ta kaj korche na (401) — notun token dao, "
                f"ar purono-ta expire hoyeche kina dekho.")
    if status == 403:
        return (f"⚠️ {service}: permission nei (403) — token-er scope thik ache "
                f"kina dekho. Details: {err[:150]}")
    if status == 422:
        return (f"⚠️ {service}: request-ta invalid (422) — {err[:200]}")
    if status == 404:
        return f"⚠️ {service}: jeta khujcho seta pelam na (404). {err[:150]}"
    if status == 0:
        return f"⚠️ {service}: {err[:200]}"
    return f"⚠️ {service}: {err[:200]} (HTTP {status})"


# ── video upload helpers ─────────────────────────────────────────────────────

_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".3gp",
               ".flv", ".wmv"}
_CHUNK = 8 * 1024 * 1024  # 8 MB chunks for resumable uploads
_UPLOAD_TIMEOUT = 180     # seconds per chunk request (uploads are slow)
_FB_VIDEO = "https://graph-video.facebook.com/v18.0"


def _call_progress(cb, pct: int) -> None:
    """Call progress_cb(pct) safely — a bad callback never breaks an upload."""
    if not callable(cb):
        return
    try:
        cb(max(0, min(100, int(pct))))
    except Exception:
        pass


def _validate_video_file(path: str) -> str:
    """"" (empty) when `path` is an existing non-empty video file, else why not."""
    path = (path or "").strip()
    if not path:
        return "video file-er path dao."
    if path.startswith("http://") or path.startswith("https://"):
        return "eta URL — local file-er path dao (URL shudhu Instagram-e chole)."
    if not os.path.isfile(path):
        return f"file-ta pelam na: {path}"
    if os.path.splitext(path)[1].lower() not in _VIDEO_EXTS:
        return (f"eta video file mone hocche na ({path}) — "
                f"mp4/mov/avi/mkv/webm-er ekta dao.")
    if os.path.getsize(path) == 0:
        return f"file-ta khali (0 bytes): {path}"
    return ""


def _video_mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "video/mp4"


def _raw(method: str, url: str, headers: dict | None = None,
         data: bytes | None = None, payload: dict | None = None,
         timeout: int = _UPLOAD_TIMEOUT) -> tuple[int, dict | None, str, dict]:
    """Raw request for uploads: (status, parsed-json-or-None, error, headers).
    Unlike _req, this sends raw bytes (not json=) and returns response headers
    — resumable sessions need both. Never raises. A 308 is returned as-is
    (the caller handles "Resume Incomplete")."""
    if _requests is None:
        return 0, None, "requests install kora nei — `pip install requests` dao.", {}
    try:
        r = _requests.request(method, url, headers=headers or {}, data=data,
                              json=payload, timeout=timeout)
    except Exception as e:
        return 0, None, f"network error: {e}", {}
    try:
        parsed = r.json()
    except Exception:
        parsed = None
    if r.status_code >= 400:
        msg = ""
        if isinstance(parsed, dict):
            err = parsed.get("error") or {}
            msg = str(err.get("message", "") if isinstance(err, dict)
                      else err) or str(parsed.get("message", "") or "")
        if not msg:
            msg = r.text[:200]
        return r.status_code, parsed, msg or f"HTTP {r.status_code}", dict(r.headers)
    return r.status_code, parsed, "", dict(r.headers)


def _multipart(url: str, data_fields: dict, file_field: str,
               file_tuple: tuple) -> tuple[int, dict | None, str]:
    """POST multipart/form-data (file chunk + text fields). Never raises."""
    if _requests is None:
        return 0, None, "requests install kora nei — `pip install requests` dao."
    try:
        r = _requests.post(url, data=data_fields,
                           files={file_field: file_tuple},
                           timeout=_UPLOAD_TIMEOUT)
    except Exception as e:
        return 0, None, f"network error: {e}"
    try:
        parsed = r.json()
    except Exception:
        parsed = None
    if r.status_code >= 400:
        msg = ""
        if isinstance(parsed, dict):
            err = parsed.get("error") or {}
            msg = str(err.get("message", "") if isinstance(err, dict)
                      else err) or str(parsed.get("message", "") or "")
        if not msg:
            msg = r.text[:200]
        return r.status_code, parsed, msg or f"HTTP {r.status_code}"
    return r.status_code, parsed, ""


# ── GitHub ───────────────────────────────────────────────────────────────────

def github_verify(token: str | None = None) -> str:
    tok = _token("github_token", token)
    if not tok:
        return ("GitHub token set kora nei. github.com/settings/tokens khule "
                "fine-grained token banao (Contents: read+write), tarpor "
                "`github_connect` diye token-ta dao.")
    st, data, err = _req("GET", f"{_GH}/user",
                         headers={"Authorization": f"Bearer {tok}",
                                  "Accept": "application/vnd.github+json"})
    if st != 200 or not data:
        return _err("GitHub", st, err)
    login = str(data.get("login", ""))
    _save(github_token=tok, github_login=login)
    return f"✅ GitHub connected: {login} ({data.get('html_url', '')})"


def github_list_repos(token: str | None = None) -> str:
    tok = _token("github_token", token)
    if not tok:
        return "GitHub token set kora nei — age `github_connect` diye token dao."
    st, data, err = _req("GET", f"{_GH}/user/repos",
                         headers={"Authorization": f"Bearer {tok}",
                                  "Accept": "application/vnd.github+json"},
                         params={"per_page": 20, "sort": "updated"})
    if st != 200 or not isinstance(data, list):
        return _err("GitHub", st, err)
    if not data:
        return "GitHub-e kono repo pelam na."
    lines = [f"• {r.get('full_name')} ({'🔒 private' if r.get('private') else '🌐 public'})"
             for r in data]
    return "GitHub repos (notun 20-ta):\n" + "\n".join(lines)


def github_create_repo(token: str | None = None, name: str = "",
                       private: bool = False,
                       description: str | None = None) -> str:
    """Create a repo with a PAT (POST /user/repos). The GitHub App cannot
    create repos (403) — a personal access token CAN. Never raises; never
    logs or returns the token. `description` is optional."""
    tok = _token("github_token", token)
    if not tok:
        return "GitHub token set kora nei — age `github_connect` diye token dao."
    name = (name or "").strip()
    if not name:
        return "Repo-r naam dao."
    payload: dict = {"name": name, "private": bool(private)}
    desc = (description or "").strip()
    if desc:
        payload["description"] = desc
    st, data, err = _req("POST", f"{_GH}/user/repos",
                         headers={"Authorization": f"Bearer {tok}",
                                  "Accept": "application/vnd.github+json"},
                         payload=payload)
    if st == 422:
        # Name taken or invalid — GitHub puts the detail in errors[0].message.
        detail = ""
        if isinstance(data, dict):
            errs = data.get("errors") or []
            if errs and isinstance(errs[0], dict):
                detail = str(errs[0].get("message", ""))
        if not detail:
            detail = err
        return (f"⚠️ GitHub: repo banano gelo na — naam '{name}' hoyto "
                f"already ache ba invalid (422). Onno naam dao. "
                f"{detail[:150]}".rstrip())
    if st not in (200, 201) or not data:
        return _err("GitHub", st, err)
    return (f"✅ Repo banalam: {data.get('full_name')} — "
            f"{data.get('html_url', '')}")


def github_push_file(token: str | None, owner: str, repo: str, path: str,
                     content: str, message: str = "Update via Jarvis") -> str:
    tok = _token("github_token", token)
    if not tok:
        return "GitHub token set kora nei — age `github_connect` diye token dao."
    owner, repo, path = (owner or "").strip(), (repo or "").strip(), (path or "").strip()
    if not owner or not repo or not path:
        return "owner, repo ar path — tintei lagbe."
    hdrs = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    url = f"{_GH}/repos/{owner}/{repo}/contents/{path}"
    # Existing file? Its sha is needed to update it.
    st, data, _ = _req("GET", url, headers=hdrs)
    sha = data.get("sha") if st == 200 and isinstance(data, dict) else None
    body = {
        "message": message or "Update via Jarvis",
        "content": base64.b64encode(str(content or "").encode("utf-8")).decode("ascii"),
    }
    if sha:
        body["sha"] = sha
    st, data, err = _req("PUT", url, headers=hdrs, payload=body)
    if st not in (200, 201) or not data:
        return _err("GitHub", st, err)
    return (f"✅ GitHub-e {owner}/{repo}/{path} "
            f"{'update' if sha else 'banano'} holo — "
            f"{(data.get('content') or {}).get('html_url', '')}")


# ── WhatsApp (Meta Business API) ─────────────────────────────────────────────

def whatsapp_send(token: str | None, phone_number_id: str | None,
                  to: str, message: str) -> str:
    tok = _token("whatsapp_token", token)
    pnid = _token("whatsapp_phone_number_id", phone_number_id)
    if not tok:
        return ("WhatsApp token set kora nei. Meta developers.facebook.com-e app "
                "khule WhatsApp product add koro, ar Business number-er token dao. "
                "Personal WhatsApp diye API-te pathano jay na.")
    if not pnid:
        return "WhatsApp phone_number_id set kora nei — Meta app-er WhatsApp > API Setup theke nao."
    to, message = (to or "").strip(), (message or "").strip()
    if not to or not message:
        return "kar kache (to) ar ki likhbe (message) — duitoi dao."
    st, data, err = _req(
        "POST", f"{_FB}/{pnid}/messages",
        headers={"Authorization": f"Bearer {tok}"},
        payload={"messaging_product": "whatsapp", "to": to,
                 "type": "text", "text": {"body": message}})
    if st not in (200, 201) or not data:
        return _err("WhatsApp", st, err)
    _save(whatsapp_token=tok, whatsapp_phone_number_id=pnid)
    return f"✅ WhatsApp-e pathano holo {to}-te (id: {data.get('messages', [{}])[0].get('id', '')})"


# ── YouTube ──────────────────────────────────────────────────────────────────

def youtube_search(api_key: str | None, query: str, max_results: int = 5) -> str:
    key = _token("youtube_api_key", api_key)
    if not key:
        return ("YouTube API key set kora nei. Google Cloud Console-e YouTube Data "
                "API v3 chalu kore key banao, tarpor `youtube_search`-e dao.")
    query = (query or "").strip()
    if not query:
        return "Ki khujbo — query dao."
    st, data, err = _req("GET", f"{_YT}/search",
                         params={"part": "snippet", "type": "video", "q": query,
                                 "maxResults": max(1, min(int(max_results or 5), 10)),
                                 "key": key})
    if st != 200 or not data:
        return _err("YouTube", st, err)
    items = data.get("items") or []
    if not items:
        return f"YouTube-e '{query}'-r kichu pelam na."
    lines = []
    for it in items:
        vid = (it.get("id") or {}).get("videoId", "")
        sn = it.get("snippet") or {}
        lines.append(f"• {sn.get('title', '')} — {sn.get('channelTitle', '')} "
                     f"(https://youtu.be/{vid})")
    return "YouTube result:\n" + "\n".join(lines)


def youtube_video(api_key: str | None, video_id: str) -> str:
    key = _token("youtube_api_key", api_key)
    if not key:
        return "YouTube API key set kora nei — age key dao."
    video_id = (video_id or "").strip()
    if not video_id:
        return "video_id dao (youtu.be/...-r pore-r tukro-ta)."
    st, data, err = _req("GET", f"{_YT}/videos",
                         params={"part": "snippet,statistics", "id": video_id,
                                 "key": key})
    if st != 200 or not data:
        return _err("YouTube", st, err)
    items = data.get("items") or []
    if not items:
        return f"Video-ta pelam na: {video_id}"
    sn, stt = items[0].get("snippet") or {}, items[0].get("statistics") or {}
    return (f"🎬 {sn.get('title', '')}\n"
            f"Channel: {sn.get('channelTitle', '')} • "
            f"Views: {stt.get('viewCount', '?')} • Likes: {stt.get('likeCount', '?')}\n"
            f"https://youtu.be/{video_id}")


def youtube_upload(file_path: str, title: str, description: str = "",
                   privacy: str = "private", progress_cb=None,
                   access_token: str | None = None) -> str:
    """Upload a video to YouTube (Data API v3, resumable upload, 8 MB chunks).

    Needs an OAuth access token — a plain API key can NEVER upload. Returns
    the video URL on success, else an honest error string. Never raises.
    progress_cb(pct) is called after every chunk (0-100)."""
    try:
        tok = _token("youtube_access_token", access_token)
        if not tok:
            return ("YouTube upload-er jonno OAuth access token set kora nei. "
                    "Plugin Settings > 🔗 CONNECTORS-e 'YouTube OAuth access token' "
                    "field-e token dao — Google OAuth Playground "
                    "(developers.google.com/oauthplayground) theke nao: scope "
                    "https://www.googleapis.com/auth/youtube.upload, tarpor "
                    "Exchange tokens. Token ~1 ghonta cholbe; 401 mane notun nao.")
        bad = _validate_video_file(file_path)
        if bad:
            return f"⚠️ YouTube upload: {bad}"
        title = (title or "").strip()
        if not title:
            return "⚠️ YouTube upload: video-r title dao."
        privacy = (privacy or "private").strip().lower()
        if privacy not in ("private", "public", "unlisted"):
            return "⚠️ YouTube upload: privacy private / public / unlisted-er ekta hobe."
        size = os.path.getsize(file_path)
        mime = _video_mime(file_path)

        # Step 1: start a resumable session — the response Location is the
        # session URL the chunks go to.
        st, _data, err, hdrs = _raw(
            "POST",
            "https://www.googleapis.com/upload/youtube/v3/videos"
            "?uploadType=resumable&part=snippet,status",
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json; charset=UTF-8",
                     "X-Upload-Content-Type": mime,
                     "X-Upload-Content-Length": str(size)},
            payload={"snippet": {"title": title,
                                 "description": description or ""},
                     "status": {"privacyStatus": privacy}},
            timeout=_TIMEOUT)  # session init is a small call; chunks use 180 s
        if st != 200 or not hdrs.get("Location"):
            return _err("YouTube", st, err or "upload session start holo na")
        session_url = hdrs["Location"]

        # Step 2: PUT the file in 8 MB chunks. 308 = "Resume Incomplete",
        # keep going from the byte the server says it has.
        offset = 0
        with open(file_path, "rb") as f:
            while offset < size:
                f.seek(offset)
                chunk = f.read(_CHUNK)
                if not chunk:
                    break
                end = offset + len(chunk)
                st, data, err, hdrs = _raw(
                    "PUT", session_url,
                    headers={"Content-Length": str(len(chunk)),
                             "Content-Range": f"bytes {offset}-{end - 1}/{size}"},
                    data=chunk)
                if st in (200, 201):
                    _call_progress(progress_cb, 100)
                    vid = (data or {}).get("id", "")
                    if not vid:
                        return "⚠️ YouTube: upload sesh holo kintu video id pelam na."
                    _save(youtube_access_token=tok)
                    return (f"✅ YouTube-e upload holo: {title} "
                            f"({privacy}) — https://youtu.be/{vid}")
                if st == 308:
                    ranged = hdrs.get("Range", "")
                    if ranged.startswith("bytes=0-"):
                        try:
                            offset = int(ranged[len("bytes=0-"):]) + 1
                        except ValueError:
                            offset = end
                    else:
                        offset = end
                    _call_progress(progress_cb, offset * 100 // size)
                    continue
                return _err("YouTube", st, err)
        return "⚠️ YouTube: upload sesh holo na — file-er sob chunk gelo na."
    except Exception as e:
        return f"⚠️ YouTube upload: {e}"


# ── Facebook ─────────────────────────────────────────────────────────────────

def facebook_pages(page_token: str | None = None) -> str:
    tok = _token("facebook_page_token", page_token)
    if not tok:
        return ("Facebook Page token set kora nei. Meta developers.facebook.com-e "
                "app khule Page-er token nao, tarpor `facebook_post`-e dao.")
    st, data, err = _req("GET", f"{_FB}/me/accounts",
                         params={"fields": "name,access_token",
                                 "access_token": tok})
    if st != 200 or not data:
        return _err("Facebook", st, err)
    pages = data.get("data") or []
    if not pages:
        return "Ei token-e kono Page pelam na."
    _save(facebook_page_token=tok)
    lines = [f"• {p.get('name')} (id: {p.get('id')})" for p in pages]
    return "Facebook Pages:\n" + "\n".join(lines)


def facebook_post(page_id: str | None, page_token: str | None,
                  message: str) -> str:
    cfg = _cfg()
    pid = (page_id or "").strip() or str(cfg.get("facebook_page_id", "") or "").strip()
    tok = _token("facebook_page_token", page_token)
    message = (message or "").strip()
    if not tok:
        return "Facebook Page token set kora nei — age `facebook_pages` diye Page dekho."
    if not pid:
        return "Page id dao — `facebook_pages` diye Page-er id dekhe nao."
    if not message:
        return "Ki post korbo — message dao."
    # The page access token lives inside /me/accounts; the caller can pass it,
    # or the stored user token is used and Facebook accepts it for the feed.
    st, data, err = _req("POST", f"{_FB}/{pid}/feed",
                         headers={"Authorization": f"Bearer {tok}"},
                         payload={"message": message})
    if st not in (200, 201) or not data:
        return _err("Facebook", st, err)
    _save(facebook_page_id=pid, facebook_page_token=tok)
    return f"✅ Facebook Page-e post holo (post id: {data.get('id', '')})"


def facebook_upload_video(file_path: str, title: str = "",
                          description: str = "", progress_cb=None,
                          page_token: str | None = None,
                          page_id: str | None = None) -> str:
    """Upload a video to a Facebook Page (Graph Video API, resumable session:
    start → transfer chunks → finish). Needs the Page token + Page id.
    Returns the video URL on success, else an honest error string.
    Never raises. progress_cb(pct) is called after every chunk (0-100)."""
    try:
        cfg = _cfg()
        pid = (page_id or "").strip() or str(cfg.get("facebook_page_id", "") or "").strip()
        tok = _token("facebook_page_token", page_token)
        if not tok:
            return ("Facebook video upload-er jonno Page token set kora nei. "
                    "Plugin Settings > 🔗 CONNECTORS-e 'Facebook Page token' "
                    "field-e token dao — Meta developers.facebook.com-e app khule "
                    "Page-er token nao (pages_manage_posts + pages_read_engagement).")
        if not pid:
            return ("Facebook Page id set kora nei — Plugin Settings > 🔗 CONNECTORS-e "
                    "'Facebook Page id' bosao, ba `facebook_pages` diye Page-er id dekhe nao.")
        bad = _validate_video_file(file_path)
        if bad:
            return f"⚠️ Facebook video upload: {bad}"
        size = os.path.getsize(file_path)

        # Step 1: start the session — Facebook tells us the chunk boundaries.
        st, data, err = _req(
            "POST", f"{_FB_VIDEO}/{pid}/videos",
            payload={"upload_phase": "start", "file_size": size,
                     "access_token": tok})
        if st not in (200, 201) or not data or not data.get("upload_session_id"):
            return _err("Facebook", st, err or "upload session start holo na")
        session_id = data["upload_session_id"]
        video_id = str(data.get("video_id", ""))
        start = int(data.get("start_offset", 0) or 0)
        end = int(data.get("end_offset", 0) or 0)
        if end <= start:
            end = min(size, start + _CHUNK)

        # Step 2: transfer chunks; each reply gives the next offsets.
        with open(file_path, "rb") as f:
            while start < size:
                f.seek(start)
                chunk = f.read(end - start)
                if not chunk:
                    break
                st, data, err = _multipart(
                    f"{_FB_VIDEO}/{pid}/videos",
                    {"upload_phase": "transfer",
                     "upload_session_id": session_id,
                     "start_offset": str(start),
                     "access_token": tok},
                    "video_file_chunk",
                    (os.path.basename(file_path), chunk, _video_mime(file_path)))
                if st not in (200, 201) or not data:
                    return _err("Facebook", st, err or "chunk transfer holo na")
                start = int(data.get("start_offset", end) or end)
                end = int(data.get("end_offset", 0) or 0)
                if end <= start and start < size:
                    end = min(size, start + _CHUNK)
                _call_progress(progress_cb, start * 100 // size)

        # Step 3: finish — title/description go here, not at the start.
        st, data, err = _req(
            "POST", f"{_FB_VIDEO}/{pid}/videos",
            payload={"upload_phase": "finish",
                     "upload_session_id": session_id,
                     "title": title or os.path.basename(file_path),
                     "description": description or "",
                     "access_token": tok})
        if st not in (200, 201) or not data:
            return _err("Facebook", st, err or "upload finish holo na")
        video_id = str(data.get("video_id", "") or video_id)
        _call_progress(progress_cb, 100)
        _save(facebook_page_id=pid, facebook_page_token=tok)
        if video_id:
            return (f"✅ Facebook Page-e video upload holo"
                    + (f": {title}" if title else "") +
                    f" — https://www.facebook.com/watch/?v={video_id}")
        return "✅ Facebook Page-e video upload holo (video id pelam na)."
    except Exception as e:
        return f"⚠️ Facebook video upload: {e}"


# ── Instagram ────────────────────────────────────────────────────────────────

def instagram_post(ig_user_id: str | None, page_token: str | None,
                   image_url: str, caption: str = "") -> str:
    cfg = _cfg()
    igid = (ig_user_id or "").strip() or str(cfg.get("instagram_user_id", "") or "").strip()
    tok = _token("instagram_token", page_token)
    image_url = (image_url or "").strip()
    if not tok:
        return ("Instagram token set kora nei — Facebook Page-er token lage "
                "(IG business account Page-er sathe linked thakte hoy).")
    if not igid:
        return "IG user id dao — Meta Graph API Explorer-e /me/accounts theke nao."
    if not image_url.startswith("http"):
        return ("Instagram-e post korte PUBLIC image URL lagbe — local file cholbe "
                "na. Age chobi-ta Drive-e ba kothao upload kore link dao.")
    # Step 1: media container.
    st, data, err = _req("POST", f"{_FB}/{igid}/media",
                         payload={"image_url": image_url,
                                  "caption": caption or "",
                                  "access_token": tok})
    if st not in (200, 201) or not data or not data.get("id"):
        return _err("Instagram", st, err)
    container = data["id"]
    # Step 2: publish it.
    st, data, err = _req("POST", f"{_FB}/{igid}/media_publish",
                         payload={"creation_id": container, "access_token": tok})
    if st not in (200, 201) or not data:
        return _err("Instagram", st, err)
    _save(instagram_user_id=igid, instagram_token=tok)
    return f"✅ Instagram-e post holo (media id: {data.get('id', '')})"


def instagram_upload_video(file_path_or_url: str, caption: str = "",
                           progress_cb=None, access_token: str | None = None,
                           ig_user_id: str | None = None) -> str:
    """Upload a video to Instagram (Graph API container flow:
    create container → poll until FINISHED → publish).

    HONEST LIMIT: the Graph API only accepts a PUBLIC video URL — it cannot
    take a local file. Pass an http(s) URL and it uploads for real; pass a
    local path and you get clear guidance instead of fake success (upload the
    file to Drive / your server first, then call again with the direct URL).
    Needs an IG Business/Creator account linked to a Facebook Page, its user
    id, and a Graph access token. Returns the media id on success, else an
    honest error string. Never raises. progress_cb(pct) reports each stage."""
    try:
        # instagram_access_token is the new upload field; fall back to the
        # older instagram_token (a Page token) which the Graph API also accepts.
        tok = _token("instagram_access_token", access_token) or _token("instagram_token", None)
        if not tok:
            return ("Instagram video upload-er jonno access token set kora nei. "
                    "Plugin Settings > 🔗 CONNECTORS-e 'Instagram Graph access token' "
                    "field-e token dao — Meta developers.facebook.com-e app khule "
                    "Graph API Explorer theke nao (instagram_basic + "
                    "instagram_content_publish scope, IG Business account "
                    "Facebook Page-er sathe linked thakte hoy).")
        cfg = _cfg()
        igid = (ig_user_id or "").strip() or str(cfg.get("instagram_user_id", "") or "").strip()
        if not igid:
            return ("Instagram user id set kora nei — Plugin Settings > 🔗 CONNECTORS-e "
                    "'Instagram Business user id' bosao (Meta Graph API Explorer-e "
                    "/me/accounts theke nao).")
        target = (file_path_or_url or "").strip()
        if not target:
            return "⚠️ Instagram video upload: video file-er path ba public URL dao."
        if target.startswith("http://") or target.startswith("https://"):
            video_url = target
        else:
            bad = _validate_video_file(target)
            if bad:
                return f"⚠️ Instagram video upload: {bad}"
            # Local file: the API has no way to receive it. Say so plainly.
            return ("⚠️ Instagram Graph API local file ney na — shudhu PUBLIC video "
                    "URL ney. Tai ei file-ta ekhono upload hoy ni (fake success na). "
                    "Age file-ta Google Drive-e upload koro (`drive_upload`), "
                    "tarpor sei file-er DIRECT public video link (drive-er share "
                    "link na — direct download/stream link) diye abar "
                    "`instagram_upload_video` call koro, ba file-ta nijer server-e "
                    "rekhe tar public URL dao.")
        caption = caption or ""

        # Step 1: media container.
        st, data, err = _req("POST", f"{_FB}/{igid}/media",
                             payload={"media_type": "VIDEO",
                                      "video_url": video_url,
                                      "caption": caption,
                                      "access_token": tok})
        if st not in (200, 201) or not data or not data.get("id"):
            return _err("Instagram", st, err or "media container banalo na")
        container = data["id"]
        _call_progress(progress_cb, 10)

        # Step 2: poll until Instagram finishes processing the video
        # (IN_PROGRESS → FINISHED, or ERROR). Max ~2 minutes.
        status = ""
        for i in range(24):
            st, data, err = _req("GET", f"{_FB}/{container}",
                                 params={"fields": "status_code,status",
                                         "access_token": tok})
            if st != 200 or not data:
                return _err("Instagram", st, err or "container status pelam na")
            status = str(data.get("status_code", ""))
            if status == "FINISHED":
                break
            if status == "ERROR":
                detail = str((data.get("status") or {}).get("error_message", "")
                             if isinstance(data.get("status"), dict) else "")
                return (f"⚠️ Instagram: video process korte parlo na "
                        f"(container {container}). {detail[:150]} "
                        f"URL-ta public ar video format thik ache kina dekho.")
            _call_progress(progress_cb, 10 + min(80, (i + 1) * 3))
            time.sleep(5)
        else:
            return (f"⚠️ Instagram: video process hote 2 minute-er beshi lagche "
                    f"(container {container}) — pore abar try koro.")
        if status != "FINISHED":
            return (f"⚠️ Instagram: video ready holo na (status: {status}) — "
                    f"pore abar try koro.")

        # Step 3: publish it.
        st, data, err = _req("POST", f"{_FB}/{igid}/media_publish",
                             payload={"creation_id": container,
                                      "access_token": tok})
        if st not in (200, 201) or not data:
            return _err("Instagram", st, err or "publish holo na")
        _call_progress(progress_cb, 100)
        _save(instagram_user_id=igid, instagram_access_token=tok)
        return f"✅ Instagram-e video post holo (media id: {data.get('id', '')})"
    except Exception as e:
        return f"⚠️ Instagram video upload: {e}"


# ── Google Drive ─────────────────────────────────────────────────────────────

def drive_list(access_token: str | None = None) -> str:
    tok = _token("drive_access_token", access_token)
    if not tok:
        return ("Drive token set kora nei. Google OAuth Playground "
                "(developers.google.com/oauthplayground) theke Drive scope-e "
                "access token nao, tarpor `drive_list`-e dao. Token ~1 ghonta cholbe.")
    st, data, err = _req("GET", _DRIVE,
                         headers={"Authorization": f"Bearer {tok}"},
                         params={"pageSize": 20,
                                 "fields": "files(id,name,mimeType,size)",
                                 "orderBy": "modifiedTime desc"})
    if st != 200 or not data:
        return _err("Google Drive", st, err)
    files = data.get("files") or []
    if not files:
        return "Drive-e kono file pelam na."
    lines = [f"• {f.get('name')} ({f.get('mimeType', '')}, "
             f"{f.get('size', '?')} bytes)" for f in files]
    return "Google Drive (notun 20-ta):\n" + "\n".join(lines)


def drive_upload(access_token: str | None, filename: str,
                 data_bytes: bytes, mime: str = "text/plain") -> str:
    tok = _token("drive_access_token", access_token)
    if not tok:
        return "Drive token set kora nei — age OAuth Playground theke access token nao."
    filename = (filename or "").strip()
    if not filename:
        return "filename dao."
    if _requests is None:
        return "requests install kora nei — `pip install requests` dao."
    try:
        r = _requests.post(
            _DRIVE_UPLOAD,
            headers={"Authorization": f"Bearer {tok}"},
            files={"metadata": (None, json.dumps({"name": filename}),
                                "application/json"),
                   "media": (filename, data_bytes, mime or "application/octet-stream")},
            timeout=_TIMEOUT)
    except Exception as e:
        return f"⚠️ Google Drive: network error: {e}"
    try:
        data = r.json()
    except Exception:
        data = None
    if r.status_code not in (200, 201) or not data:
        msg = ""
        if isinstance(data, dict):
            msg = str((data.get("error") or {}).get("message", "") or "")
        return _err("Google Drive", r.status_code, msg or r.text[:200])
    _save(drive_access_token=tok)
    return (f"✅ Drive-e upload holo: {data.get('name')} "
            f"(id: {data.get('id', '')}) — "
            f"https://drive.google.com/file/d/{data.get('id', '')}/view")


# ── status ───────────────────────────────────────────────────────────────────

def connectors_status() -> str:
    cfg = _cfg()
    lines = ["🔗 Connectors:"]
    lines.append("• GitHub: " + (f"✅ connected ({cfg.get('github_login', '')})"
                                 if cfg.get("github_token") else
                                 "❌ token nei — github.com/settings/tokens theke nao"))
    lines.append("• WhatsApp: " + ("✅ Business number set"
                                   if cfg.get("whatsapp_token") else
                                   "❌ token nei — Meta app + Business number lagbe"))
    lines.append("• YouTube: " + ("✅ API key set" if cfg.get("youtube_api_key")
                                  else "❌ key nei — Google Cloud Console theke nao"))
    lines.append("• YouTube upload: " + ("✅ OAuth token set (~1h cholbe)"
                                         if cfg.get("youtube_access_token") else
                                         "❌ OAuth token nei — OAuth Playground theke nao"))
    lines.append("• Facebook: " + ("✅ Page token set"
                                   if cfg.get("facebook_page_token") else
                                   "❌ token nei — Meta app theke Page token nao"))
    lines.append("• Instagram: " + ("✅ IG set" if cfg.get("instagram_token")
                                    else "❌ token nei — FB Page token + IG business account lagbe"))
    lines.append("• Instagram upload: " + ("✅ token + user id set"
                                           if cfg.get("instagram_access_token")
                                           and cfg.get("instagram_user_id") else
                                           "❌ token/user id nei — Meta app theke nao"))
    lines.append("• Google Drive: " + ("✅ token set (1 ghonta cholbe)"
                                       if cfg.get("drive_access_token") else
                                       "❌ token nei — OAuth Playground theke nao"))
    lines.append("Token dite: `github_connect` / ba prottek tool-e token dao — "
                 "token config/api_keys.json-er plugin_config-e save hoy, code-te na.")
    return "\n".join(lines)
