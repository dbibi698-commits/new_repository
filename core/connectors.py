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
  * YouTube: search + video details work with an API key. UPLOAD needs OAuth
    (a user consent flow) — deliberately not implemented here.
  * Instagram: posting needs a business/creator account linked to a Facebook
    Page, and a PUBLIC image URL — the API cannot take a local file.
  * Google Drive: needs an OAuth access token (Google OAuth Playground gives
    one). It expires in about an hour; a 401 means "notun token dao".
  * GitHub: a fine-grained personal access token (github.com/settings/tokens)
    with Contents read/write on the repos you want to touch.
"""

from __future__ import annotations

import base64
import json

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
    if status == 404:
        return f"⚠️ {service}: jeta khujcho seta pelam na (404). {err[:150]}"
    if status == 0:
        return f"⚠️ {service}: {err[:200]}"
    return f"⚠️ {service}: {err[:200]} (HTTP {status})"


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


def github_create_repo(token: str | None, name: str, private: bool = False) -> str:
    tok = _token("github_token", token)
    if not tok:
        return "GitHub token set kora nei — age `github_connect` diye token dao."
    name = (name or "").strip()
    if not name:
        return "Repo-r naam dao."
    st, data, err = _req("POST", f"{_GH}/user/repos",
                         headers={"Authorization": f"Bearer {tok}",
                                  "Accept": "application/vnd.github+json"},
                         payload={"name": name, "private": bool(private)})
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
    lines.append("• Facebook: " + ("✅ Page token set"
                                   if cfg.get("facebook_page_token") else
                                   "❌ token nei — Meta app theke Page token nao"))
    lines.append("• Instagram: " + ("✅ IG set" if cfg.get("instagram_token")
                                    else "❌ token nei — FB Page token + IG business account lagbe"))
    lines.append("• Google Drive: " + ("✅ token set (1 ghonta cholbe)"
                                       if cfg.get("drive_access_token") else
                                       "❌ token nei — OAuth Playground theke nao"))
    lines.append("Token dite: `github_connect` / ba prottek tool-e token dao — "
                 "token config/api_keys.json-er plugin_config-e save hoy, code-te na.")
    return "\n".join(lines)
