"""core/cat05_social.py — Category 5 (Social Media & Video Upload) helpers.

Shared engine behind plugins/cat05_social.py. No Qt anywhere; every public
function returns a short string and never raises. Tokens/keys are read ONLY
through memory/config_manager.py plugin_config (namespace "connectors" for
the platform tokens, "autoreply" for the shared keyword rules, "cat05_social"
for this category's own settings) — never hardcoded, never printed.

What lives here:
  * YouTube Shorts upload (delegates to core/connectors.youtube_upload with
    the #Shorts tag — a Short is a <=60 s vertical video, same upload API).
  * Instagram Story publish (Graph API container flow, media_type=STORIES —
    verified supported: POST /{ig-user-id}/media + /media_publish).
  * Comment manager (Facebook + Instagram Graph API: list / reply / hide /
    delete).
  * YouTube analytics summary (Data API v3 statistics).
  * WhatsApp broadcast (Business template messages, approved recipients only).
  * Thumbnail maker (PIL — 1280x720, text overlay).
  * Caption / hashtag AI + content ideas (core.gemini, with fallbacks).
  * Upload queue persistence (plugin_config["upload_queue"]).
  * Facebook auto-reply engine (same rules-engine pattern as
    core/autoreply.py: shared keyword rules + default reply from the
    "autoreply" namespace; Facebook enable/verify-token in "cat05_social").
    The dashboard webhook for it is NOT in this file — see the server.py
    patch in plugins/cat05_social.py's docstring.

HONEST LIMITS (checked against the Graph API, 2026-11-17):
  * Instagram bio / website ("link in bio") is READ-ONLY via the official
    API — the IG User node only supports GET. No endpoint updates biography
    or website; that edit must be done in the Instagram app. link_in_bio()
    below therefore only READS the current bio/website and reports the
    manual steps — it never claims to have updated anything.
  * Instagram only accepts a PUBLIC media URL — never a local file.
  * YouTube upload needs an OAuth access token (~1 h); a plain API key
    can never upload. Analytics needs a YouTube Data API key.
  * WhatsApp sending only works from a WhatsApp BUSINESS number through a
    Meta app, and broadcast messages must use an APPROVED template sent to
    recipients the user approved in Settings — never a scraped list.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path

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

_FB = "https://graph.facebook.com/v18.0"
_YT = "https://www.googleapis.com/youtube/v3"
_TIMEOUT = 15
_NS = "cat05_social"
_QUEUE_NS = "upload_queue"

# ── config ───────────────────────────────────────────────────────────────────

def _conn_cfg() -> dict:
    try:
        return get_plugin_config("connectors") or {}
    except Exception:
        return {}


def _cfg() -> dict:
    try:
        return get_plugin_config(_NS) or {}
    except Exception:
        return {}


def get_cat05_config() -> dict:
    """This category's own settings (never raises)."""
    cfg = _cfg()
    return {
        "facebook_enabled": bool(cfg.get("facebook_enabled", False)),
        "facebook_verify_token": str(cfg.get("facebook_verify_token", "") or ""),
        "broadcast_recipients": str(cfg.get("broadcast_recipients", "") or ""),
        "broadcast_template": str(cfg.get("broadcast_template", "") or "hello_world"),
    }


def save_cat05_config(values: dict) -> None:
    """Merge values into plugin_config["cat05_social"]. Never raises."""
    try:
        clean = {k: v for k, v in (values or {}).items()
                 if k in ("facebook_enabled", "facebook_verify_token",
                          "broadcast_recipients", "broadcast_template")}
        if clean:
            save_plugin_config(_NS, clean)
    except Exception:
        pass


def _approved_recipients() -> list[str]:
    raw = get_cat05_config().get("broadcast_recipients", "")
    out: list[str] = []
    for part in str(raw or "").replace(";", ",").split(","):
        num = re.sub(r"[^\d+]", "", part.strip())
        if num and num not in out:
            out.append(num)
    return out


# ── tiny Graph/YouTube HTTP helpers (never raise) ────────────────────────────

def _graph(method: str, path: str, token: str, params=None, payload=None):
    """(status, data-dict-or-None, error-string). Never raises."""
    if _requests is None:
        return 0, None, "requests install kora nei."
    if not token:
        return 0, None, "token set kora nei."
    url = f"{_FB}/{path.lstrip('/')}"
    try:
        if method == "GET":
            r = _requests.get(url, params={**(params or {}), "access_token": token},
                              timeout=_TIMEOUT)
        elif method == "DELETE":
            r = _requests.delete(url, params={"access_token": token},
                                 timeout=_TIMEOUT)
        else:
            r = _requests.post(url, params={"access_token": token},
                               json=payload or {}, timeout=_TIMEOUT)
    except Exception as e:
        return 0, None, f"network error: {e}"
    try:
        data = r.json()
    except Exception:
        data = None
    if r.status_code >= 400:
        msg = ""
        if isinstance(data, dict):
            err = data.get("error") or {}
            msg = str(err.get("message", "") if isinstance(err, dict) else err)
        return r.status_code, data, msg or f"HTTP {r.status_code}"
    return r.status_code, data, ""


def _graph_err(service: str, status: int, err: str) -> str:
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


def _ig_token_and_id():
    cfg = _conn_cfg()
    tok = (str(cfg.get("instagram_access_token", "") or "").strip()
           or str(cfg.get("instagram_token", "") or "").strip())
    igid = str(cfg.get("instagram_user_id", "") or "").strip()
    return tok, igid


def _fb_token_and_page():
    cfg = _conn_cfg()
    tok = str(cfg.get("facebook_page_token", "") or "").strip()
    pid = str(cfg.get("facebook_page_id", "") or "").strip()
    return tok, pid


# ── 82 · YouTube Shorts upload ───────────────────────────────────────────────

def youtube_shorts_upload(file_path: str, title: str, description: str = "",
                          privacy: str = "private", progress_cb=None) -> str:
    """Upload a Short: same resumable upload as a normal video, with #Shorts
    in the title/description so YouTube treats it as a Short (vertical video
    up to 60 s). Delegates to core/connectors.youtube_upload. NEEDS-KEY
    (YouTube OAuth access token). Never raises."""
    try:
        from core import connectors as conn
    except Exception as e:
        return f"YouTube Shorts upload korte parlam na (connectors load hoy ni): {e}"
    try:
        file_path = (file_path or "").strip()
        title = (title or "").strip()
        description = description or ""
        if not file_path or not os.path.isfile(file_path):
            return f"⚠️ YouTube Shorts upload: file-ta pelam na: {file_path or '(khali)'}"
        if not title:
            return "⚠️ YouTube Shorts upload: video-r title dao."
        privacy = (privacy or "private").strip().lower()
        if privacy not in ("private", "public", "unlisted"):
            return "⚠️ YouTube Shorts upload: privacy private / public / unlisted-er ekta hobe."
        # A Short is recognised by YouTube from the vertical <=60 s video
        # plus the #Shorts tag — make sure the tag is there, once.
        if "#shorts" not in f"{title} {description}".lower():
            description = (description + " #Shorts").strip()
        return conn.youtube_upload(file_path, title, description, privacy,
                                   progress_cb=progress_cb)
    except Exception as e:
        return f"⚠️ YouTube Shorts upload: {e}"


# ── 84 · Instagram Story ─────────────────────────────────────────────────────

def instagram_story(media_url: str, is_video: bool = False,
                    progress_cb=None) -> str:
    """Publish an Instagram Story via the Graph API container flow
    (media_type=STORIES, then media_publish). Needs a public http(s) URL —
    the API takes no local file — plus IG token + business user id.
    No caption on stories (the API ignores it); no stickers/polls/links via
    API. Story lives 24 h. NEEDS-KEY. Never raises."""
    try:
        tok, igid = _ig_token_and_id()
        if not tok:
            return ("Instagram Story-r jonno access token set kora nei. "
                    "Plugin Settings > 🔗 CONNECTORS-e 'Instagram Graph access token' dao.")
        if not igid:
            return ("Instagram user id set kora nei — Plugin Settings > 🔗 CONNECTORS-e "
                    "'Instagram Business user id' bosao.")
        url = (media_url or "").strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            return ("⚠️ Instagram Story: PUBLIC image/video URL dao — local file "
                    "Graph API ney na. Age file-ta Drive/server-e upload kore "
                    "public link dao.")
        body = {"media_type": "STORIES",
                "access_token": tok}
        body["video_url" if is_video else "image_url"] = url
        st, data, err = _graph("POST", f"{igid}/media", tok, payload=body)
        if st not in (200, 201) or not data or not data.get("id"):
            return _graph_err("Instagram", st, err or "story container banalo na")
        container = data["id"]
        if callable(progress_cb):
            try:
                progress_cb(20)
            except Exception:
                pass
        if is_video:
            # Poll until FINISHED (same as Reels), max ~2 minutes.
            status = ""
            for i in range(24):
                st, data, err = _graph("GET", container, tok,
                                       params={"fields": "status_code,status"})
                if st != 200 or not data:
                    return _graph_err("Instagram", st, err or "container status pelam na")
                status = str(data.get("status_code", ""))
                if status == "FINISHED":
                    break
                if status == "ERROR":
                    return ("⚠️ Instagram: story video process korte parlo na "
                            f"(container {container}) — URL public ar format thik "
                            "ache kina dekho.")
                if callable(progress_cb):
                    try:
                        progress_cb(20 + min(70, (i + 1) * 3))
                    except Exception:
                        pass
                time.sleep(5)
            else:
                return (f"⚠️ Instagram: story video process hote 2 minute-er beshi "
                        f"lagche (container {container}) — pore abar try koro.")
            if status != "FINISHED":
                return f"⚠️ Instagram: story ready holo na (status: {status})."
        st, data, err = _graph("POST", f"{igid}/media_publish", tok,
                               payload={"creation_id": container})
        if st not in (200, 201) or not data:
            return _graph_err("Instagram", st, err or "story publish holo na")
        if callable(progress_cb):
            try:
                progress_cb(100)
            except Exception:
                pass
        return (f"✅ Instagram Story live holo (media id: {data.get('id', '')}) — "
                "24 ghonta thakbe.")
    except Exception as e:
        return f"⚠️ Instagram Story: {e}"


# ── 90 · Comment manager ─────────────────────────────────────────────────────

def comment_manager(platform: str, object_id: str, op: str = "list",
                    message: str = "", comment_id: str = "",
                    limit: int = 10) -> str:
    """Read / reply / hide / delete comments via the Graph API.

    Facebook: Page token (+ Page id not needed — the object id is enough).
    Instagram: IG token + media id. Hiding on IG uses ?hide=true.
    NEEDS-KEY (Page / IG token with pages_manage_engagement /
    instagram_business_manage_comments). Never raises."""
    try:
        platform = (platform or "").strip().lower()
        op = (op or "list").strip().lower()
        object_id = (object_id or "").strip()
        comment_id = (comment_id or "").strip()
        message = (message or "").strip()
        if platform not in ("facebook", "instagram"):
            return "Platform facebook ba instagram hote hobe."
        if op not in ("list", "reply", "hide", "unhide", "delete"):
            return "Op list, reply, hide, unhide, ba delete hote hobe."
        if platform == "facebook":
            tok, _pid = _fb_token_and_page()
            service = "Facebook"
        else:
            tok, _igid = _ig_token_and_id()
            service = "Instagram"
        if not tok:
            return (f"{service} token set kora nei — Plugin Settings > 🔗 CONNECTORS-e "
                    "token dao.")

        if op == "list":
            if not object_id:
                return "list-er jonno post/media id dao (object_id)."
            st, data, err = _graph(
                "GET", f"{object_id}/comments", tok,
                params={"fields": "id,from,message,created_time,like_count,is_hidden",
                        "limit": max(1, min(int(limit or 10), 25))})
            if st != 200 or not data:
                return _graph_err(service, st, err or "comment pelam na")
            items = data.get("data") or []
            if not items:
                return f"{service}-e ei post-e kono comment pelam na."
            lines = [f"{service} comments ({len(items)}-ta):"]
            for c in items:
                who = ((c.get("from") or {}).get("username")
                       or (c.get("from") or {}).get("name") or "?")
                hidden = " [hidden]" if c.get("is_hidden") else ""
                lines.append(f"• {who}: {str(c.get('message', ''))[:120]}"
                             f" (id: {c.get('id')}){hidden}")
            return "\n".join(lines)

        if op == "reply":
            target = comment_id or object_id
            if not target or not message:
                return "reply-er jonno comment/post id ar message — duitoi dao."
            st, data, err = _graph("POST", f"{target}/comments", tok,
                                   payload={"message": message})
            if st not in (200, 201) or not data:
                return _graph_err(service, st, err or "reply holo na")
            return f"✅ {service}-e reply dilam (comment id: {data.get('id', '')})."

        if op in ("hide", "unhide"):
            if not comment_id:
                return f"{op}-er jonno comment_id dao."
            hide = op == "hide"
            if platform == "instagram":
                # IG: POST /{comment-id}?hide=true|false
                if _requests is None:
                    return "requests install kora nei."
                try:
                    r = _requests.post(
                        f"{_FB}/{comment_id}",
                        params={"access_token": tok, "hide": str(hide).lower()},
                        timeout=_TIMEOUT)
                    st, data, err = r.status_code, r.json() if r.text else {}, ""
                    if st >= 400:
                        err = str(((data or {}).get("error") or {}).get("message", "")) or f"HTTP {st}"
                        return _graph_err(service, st, err)
                except Exception as e:
                    return f"⚠️ {service}: {e}"
            else:
                st, data, err = _graph("POST", comment_id, tok,
                                       payload={"is_hidden": hide})
                if st not in (200, 201) or not data:
                    return _graph_err(service, st, err or "hide/unhide holo na")
            return (f"✅ Comment {'lukano' if hide else 'abar dekhano'} holo "
                    f"({comment_id}).")

        # delete
        if not comment_id:
            return "delete-er jonno comment_id dao."
        st, data, err = _graph("DELETE", comment_id, tok)
        if st not in (200, 201) or not data:
            return _graph_err(service, st, err or "delete holo na")
        return f"✅ Comment delete holo ({comment_id})."
    except Exception as e:
        return f"⚠️ Comment manager: {e}"


# ── 97 · Analytics summary ───────────────────────────────────────────────────

def youtube_analytics(video_id: str = "", channel_id: str = "") -> str:
    """Basic YouTube stats via Data API v3 (views / likes / comments, plus
    subscribers for a channel). NEEDS-KEY (YouTube Data API key).
    Never raises."""
    try:
        cfg = _conn_cfg()
        key = str(cfg.get("youtube_api_key", "") or "").strip()
        if not key:
            return ("YouTube analytics-er jonno API key set kora nei — Plugin "
                    "Settings > 🔗 CONNECTORS-e 'YouTube Data API key' dao.")
        if _requests is None:
            return "requests install kora nei."
        video_id = (video_id or "").strip()
        channel_id = (channel_id or "").strip()
        if channel_id or video_id.startswith("UC"):
            cid = channel_id or video_id
            try:
                r = _requests.get(f"{_YT}/channels",
                                  params={"part": "snippet,statistics", "id": cid,
                                          "key": key}, timeout=_TIMEOUT)
                data = r.json()
            except Exception as e:
                return f"⚠️ YouTube analytics: network error: {e}"
            if r.status_code != 200 or not data:
                return _graph_err("YouTube", r.status_code,
                                  str(((data or {}).get("error") or {}).get("message", "")))
            items = data.get("items") or []
            if not items:
                return f"Channel-ta pelam na: {cid}"
            sn, stt = items[0].get("snippet") or {}, items[0].get("statistics") or {}
            return (f"📊 {sn.get('title', '')}\n"
                    f"Subscribers: {stt.get('subscriberCount', '?')} • "
                    f"Total views: {stt.get('viewCount', '?')} • "
                    f"Videos: {stt.get('videoCount', '?')}")
        if not video_id:
            return "analytics-er jonno video_id (youtu.be/...-r pore-r tukro) ba channel_id dao."
        try:
            r = _requests.get(f"{_YT}/videos",
                              params={"part": "snippet,statistics", "id": video_id,
                                      "key": key}, timeout=_TIMEOUT)
            data = r.json()
        except Exception as e:
            return f"⚠️ YouTube analytics: network error: {e}"
        if r.status_code != 200 or not data:
            return _graph_err("YouTube", r.status_code,
                              str(((data or {}).get("error") or {}).get("message", "")))
        items = data.get("items") or []
        if not items:
            return f"Video-ta pelam na: {video_id}"
        sn, stt = items[0].get("snippet") or {}, items[0].get("statistics") or {}
        return (f"📊 {sn.get('title', '')}\n"
                f"Channel: {sn.get('channelTitle', '')} • "
                f"Views: {stt.get('viewCount', '?')} • "
                f"Likes: {stt.get('likeCount', '?')} • "
                f"Comments: {stt.get('commentCount', '?')}\n"
                f"https://youtu.be/{video_id}")
    except Exception as e:
        return f"⚠️ YouTube analytics: {e}"


# ── 98 · WhatsApp broadcast (approved template + approved list only) ────────

def whatsapp_broadcast(template_name: str, body_text: str = "",
                       recipients: str = "", language: str = "en_US") -> str:
    """Send a WhatsApp Business TEMPLATE message to approved recipients only.

    Policy (also stated in the tool description): only recipients listed in
    Settings > 📱 SOCIAL MEDIA > "Broadcast recipients (approved only)" ever
    receive anything; any other number in `recipients` is skipped and named
    in the result. Only an approved Meta template (template_name) is used —
    never free-form bulk text. NEEDS-KEY (WhatsApp Business token +
    phone_number_id). Never raises."""
    try:
        cfg = _conn_cfg()
        tok = str(cfg.get("whatsapp_token", "") or "").strip()
        pnid = str(cfg.get("whatsapp_phone_number_id", "") or "").strip()
        if not tok:
            return ("WhatsApp token set kora nei — Meta app + Business number lagbe. "
                    "Personal WhatsApp diye API-te pathano jay na.")
        if not pnid:
            return "WhatsApp phone_number_id set kora nei — Meta app-er WhatsApp > API Setup theke nao."
        template_name = (template_name or "").strip() or \
            get_cat05_config().get("broadcast_template", "") or "hello_world"
        approved = _approved_recipients()
        if not approved:
            return ("Broadcast-er jonno kono approved recipient nei — Settings > "
                    "📱 SOCIAL MEDIA-e 'Broadcast recipients (approved only)' field-e "
                    "number gulo (comma diye) bosao. Approved list chara kauke "
                    "message jabe na.")
        wanted: list[str] = []
        for part in str(recipients or "").replace(";", ",").split(","):
            num = re.sub(r"[^\d+]", "", part.strip())
            if num and num not in wanted:
                wanted.append(num)
        if not wanted:
            wanted = list(approved)
        allowed = [n for n in wanted if n in approved]
        skipped = [n for n in wanted if n not in approved]
        if not allowed:
            return ("Broadcast holo na — deoa number-gulo approved list-e nei. "
                    f"Skipped: {', '.join(skipped)}. Approved list Settings-e bosao.")
        if _requests is None:
            return "requests install kora nei."
        body_text = (body_text or "").strip()
        sent, failed = [], []
        for to in allowed:
            payload = {"messaging_product": "whatsapp", "to": to,
                       "type": "template",
                       "template": {"name": template_name,
                                    "language": {"code": (language or "en_US").strip() or "en_US"}}}
            if body_text:
                payload["template"]["components"] = [
                    {"type": "body", "parameters": [{"type": "text", "text": body_text}]}]
            try:
                r = _requests.post(
                    f"{_FB}/{pnid}/messages",
                    headers={"Authorization": f"Bearer {tok}"},
                    json=payload, timeout=_TIMEOUT)
                data = r.json() if r.text else {}
            except Exception as e:
                failed.append(f"{to} (network: {e})")
                continue
            if r.status_code in (200, 201) and data:
                sent.append(to)
            else:
                err = str(((data or {}).get("error") or {}).get("message", ""))[:120]
                failed.append(f"{to} ({err or r.status_code})")
        out = (f"📣 Broadcast: template '{template_name}' — {len(sent)}/{len(allowed)} "
               f"jonke gelo" + (f": {', '.join(sent)}" if sent else "") + ".")
        if failed:
            out += f" Fail: {'; '.join(failed)[:200]}"
        if skipped:
            out += (f" Approved list-e nei bole pathano hoy ni: {', '.join(skipped)}.")
        return out
    except Exception as e:
        return f"⚠️ Broadcast: {e}"


# ── 92 · Thumbnail maker ─────────────────────────────────────────────────────

def thumbnail_make(image_path: str = "", title_text: str = "",
                   output_path: str = "") -> str:
    """Build a 1280x720 thumbnail PNG with PIL: cover-crop of the source
    image (or a plain gradient when none is given) + a dark band + bold
    title text. Returns the saved file path. Never raises."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return "Thumbnail banate parlam na — Pillow install kora nei."
    try:
        title_text = (title_text or "").strip()
        src = (image_path or "").strip()
        if src and not os.path.isfile(src):
            return f"⚠️ Thumbnail: image-ta pelam na: {src}"
        if src:
            img = Image.open(src).convert("RGB")
        else:
            img = Image.new("RGB", (1280, 720), (18, 24, 48))
        # Cover-crop to 16:9.
        w, h = img.size
        target = 16 / 9
        if w / h > target:
            nw = int(h * target)
            x0 = (w - nw) // 2
            img = img.crop((x0, 0, x0 + nw, h))
        else:
            nh = int(w / target)
            y0 = (h - nh) // 2
            img = img.crop((0, y0, w, y0 + nh))
        img = img.resize((1280, 720), Image.LANCZOS)
        # Dark gradient band at the bottom for readable text.
        overlay = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for y in range(360, 720):
            alpha = int(150 * (y - 360) / 360)
            od.line([(0, y), (1280, y)], fill=(0, 0, 0, alpha))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)
        font = None
        for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                     "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
                     "C:/Windows/Fonts/arialbd.ttf",
                     "/System/Library/Fonts/Helvetica.ttc"):
            try:
                font = ImageFont.truetype(cand, 72)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()
        # Word-wrap the title to fit.
        words = (title_text or "Thumbnail").split()
        lines, cur = [], ""
        for word in words:
            trial = f"{cur} {word}".strip()
            try:
                tw = draw.textlength(trial, font=font)
            except Exception:
                tw = len(trial) * 36
            if tw > 1120 and cur:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        if cur:
            lines.append(cur)
        lines = lines[:3]
        try:
            line_h = int(font.size * 1.15) if hasattr(font, "size") else 80
        except Exception:
            line_h = 80
        y = 720 - 40 - line_h * len(lines)
        for line in lines:
            draw.text((60, y), line, font=font, fill=(255, 255, 255),
                      stroke_width=3, stroke_fill=(0, 0, 0))
            y += line_h
        out = (output_path or "").strip()
        if not out:
            base = Path(src).stem if src else "thumbnail"
            folder = Path(src).parent if src else Path.cwd()
            out = str(folder / f"{base}_thumb.png")
        img.save(out, "PNG")
        return f"✅ Thumbnail banalam: {out} (1280x720 PNG)"
    except Exception as e:
        return f"⚠️ Thumbnail banate parlam na: {e}"


# ── 91 · Caption + hashtag AI ────────────────────────────────────────────────

def caption_generate(topic: str, platform: str = "instagram",
                     tone: str = "friendly") -> str:
    """Gemini (core.gemini.text) writes a caption + hashtags for a title /
    topic. Falls back to a plain caption + hashtags built from the topic
    words when Gemini does not answer. Never raises."""
    try:
        topic = (topic or "").strip()
        if not topic:
            return "Caption-er jonno title / topic dao."
        platform = (platform or "instagram").strip().lower() or "instagram"
        tone = (tone or "friendly").strip()
        prompt = (f"Write a short {tone} social media caption for {platform} "
                  f"about: {topic}. Then on a new line list 8-10 relevant "
                  f"hashtags, space-separated, starting with #. Keep the "
                  f"caption under 40 words. Reply with the caption first, "
                  f"then the hashtags — nothing else.")
        text = ""
        try:
            from core import gemini
            text = gemini.text(prompt, tier=gemini.FAST, default="") or ""
        except Exception:
            text = ""
        text = str(text or "").strip()
        if text:
            return f"✍️ Caption ({platform}):\n{text[:600]}"
        words = [re.sub(r"[^a-zA-Z0-9]", "", w) for w in topic.split()]
        tags = " ".join(f"#{w.lower()}" for w in words if w) or "#video"
        return (f"✍️ Caption ({platform}): {topic}\n"
                f"{tags} #reels #viral #foryou\n"
                "(Gemini uttor dilo na — tai topic theke hashtag banalam.)")
    except Exception as e:
        return f"⚠️ Caption banate parlam na: {e}"


# ── 100 · Content idea generator ─────────────────────────────────────────────

def content_ideas_generate(topic: str, count: int = 5) -> str:
    """Trending angles via web_search + Gemini ideas + a script outline.
    Falls back to Gemini-only, then to a plain template, when a leg fails.
    Never raises."""
    try:
        topic = (topic or "").strip()
        if not topic:
            return "Idea-r jonno topic dao (e.g. 'cooking', 'cricket')."
        try:
            count = max(1, min(int(count or 5), 10))
        except Exception:
            count = 5
        trends = ""
        try:
            from actions.web_search import _search as _ws
            trends = str(_ws(f"trending {topic} videos topics 2026") or "")[:800]
        except Exception:
            trends = ""
        prompt = (f"Give {count} fresh video content ideas about '{topic}' "
                  f"for YouTube/Instagram. Trending context: {trends or 'none'}. "
                  f"For each idea give: a catchy title, one line on the hook, "
                  f"and a 3-beat script outline (setup, twist, payoff). "
                  f"Number them 1-{count}. Keep it tight.")
        text = ""
        try:
            from core import gemini
            text = gemini.text(prompt, tier=gemini.SMART, default="") or ""
        except Exception:
            text = ""
        text = str(text or "").strip()
        if text:
            return f"💡 Content ideas — {topic}:\n{text[:1500]}"
        fallback = [f"{i}. {topic} — idea {i}: hook diye shuru, tarpor "
                    f"demo, seshe call-to-action." for i in range(1, count + 1)]
        return ("💡 Content ideas — " + topic + ":\n" + "\n".join(fallback) +
                "\n(Gemini / search uttor dilo na — tai basic list dilam.)")
    except Exception as e:
        return f"⚠️ Content idea banate parlam na: {e}"


# ── 99 · Link in bio helper (API-limited — read-only) ────────────────────────

def link_in_bio(action: str = "check", link: str = "") -> str:
    """READ the current Instagram bio/website via the Graph API and report
    the manual steps to change it.

    The official Instagram Graph API has NO endpoint to update biography or
    website — the IG User node is GET-only for profile fields. So this
    function never claims to have changed the bio: it shows the current
    bio + website (when readable), saves a desired link in Settings as a
    reminder, and tells the user exactly where to paste it in the Instagram
    app. NEEDS-KEY (IG token). Never raises."""
    try:
        action = (action or "check").strip().lower()
        tok, igid = _ig_token_and_id()
        if not tok or not igid:
            return ("Link-in-bio dekhte IG token + user id lagbe (Plugin Settings > "
                    "🔗 CONNECTORS). Note: Graph API diye bio/website CHANGE kora "
                    "jay na — IG User node shudhu GET; edit korte Instagram app-e "
                    "Edit Profile korte hoy.")
        if action == "save":
            link = (link or "").strip()
            if not link.startswith("http"):
                return "save-er jonno ekta http(s) link dao."
            try:
                save_plugin_config(_NS, {"desired_bio_link": link})
            except Exception:
                pass
            return (f"✅ Bio link reminder save holo: {link}\n"
                    "⚠️ Eta shudhu ekta reminder — API diye bio change kora jay na. "
                    "Instagram app khule Edit Profile → Website-e ei link-ta paste koro.")
        st, data, err = _graph("GET", igid, tok,
                               params={"fields": "username,biography,website,"
                                                "followers_count,media_count"})
        if st != 200 or not data:
            return _graph_err("Instagram", st, err or "profile pelam na")
        desired = str(_cfg().get("desired_bio_link", "") or "")
        lines = [f"🔗 Link in bio — @{data.get('username', '')}:",
                 f"• Bio: {str(data.get('biography', '') or '(khali)')[:200]}",
                 f"• Website (akhon): {data.get('website') or '(kono link nei)'}",
                 f"• Followers: {data.get('followers_count', '?')} • "
                 f"Posts: {data.get('media_count', '?')}"]
        if desired:
            lines.append(f"• Saved reminder link: {desired}")
        lines.append("⚠️ Graph API diye bio/website bodlano jay na (IG User node "
                     "GET-only) — Instagram app-e Edit Profile → Website-e link "
                     "paste korte hobe. Notun link save korte 'save' action-e link dao.")
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Link in bio: {e}"


# ── 94 · Upload queue (persistent, plugin_config["upload_queue"]) ────────────

def _queue_load() -> list[dict]:
    try:
        data = get_plugin_config(_QUEUE_NS) or {}
        items = data.get("items")
        return [dict(i) for i in items if isinstance(i, dict)]
    except Exception:
        return []


def _queue_save(items: list[dict]) -> None:
    try:
        save_plugin_config(_QUEUE_NS, {"items": items})
    except Exception:
        pass


def queue_add(tool: str, args: dict) -> str:
    """Add one upload job. `tool` must be an upload tool name, `args` its
    parameters dict. Never raises."""
    try:
        tool = (tool or "").strip()
        if tool not in ("youtube_upload", "youtube_shorts_upload",
                        "instagram_upload_video", "facebook_upload_video",
                        "facebook_post", "instagram_post"):
            return ("Queue-e shudhu upload/post tool jay: youtube_upload, "
                    "youtube_shorts_upload, instagram_upload_video, "
                    "facebook_upload_video, facebook_post, instagram_post.")
        items = _queue_load()
        item = {"id": uuid.uuid4().hex[:8], "tool": tool,
                "args": dict(args or {}), "status": "queued",
                "created_at": time.strftime("%Y-%m-%d %H:%M"), "result": ""}
        items.append(item)
        _queue_save(items)
        return f"✅ Queue-e add holo: {tool} (id {item['id']}) — queue-e ekhon {len(items)}-ta job."
    except Exception as e:
        return f"⚠️ Queue-e add korte parlam na: {e}"


def queue_list() -> str:
    """List queued/running jobs. Never raises."""
    try:
        items = _queue_load()
        if not items:
            return "Upload queue khali — add korte 'upload_queue' action-e tool + args dao."
        lines = [f"📥 Upload queue ({len(items)}-ta):"]
        for it in items:
            lines.append(f"• [{it.get('id')}] {it.get('tool')} — "
                         f"{it.get('status')} ({it.get('created_at', '')})"
                         + (f" — {str(it.get('result', ''))[:100]}"
                            if it.get("result") else ""))
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Queue dekhte parlam na: {e}"


def queue_clear(confirm: bool = False) -> str:
    """Clear the whole queue. Guarded by data protection. Never raises."""
    try:
        from memory.config_manager import bulk_clear_guard
        if not bulk_clear_guard("upload queue", confirm):
            return "⚠️ Queue clear korte confirm=yes dao — data protection ON ache."
        n = len(_queue_load())
        _queue_save([])
        return f"✅ Queue khali holo ({n}-ta job muche gelo)."
    except Exception as e:
        return f"⚠️ Queue clear korte parlam na: {e}"


def queue_next_job() -> dict | None:
    """The oldest queued job (dict) or None. Never raises."""
    try:
        for it in _queue_load():
            if it.get("status") == "queued":
                return dict(it)
    except Exception:
        pass
    return None


def queue_mark(item_id: str, status: str, result: str = "") -> None:
    """Update one job's status/result. Never raises."""
    try:
        items = _queue_load()
        for it in items:
            if it.get("id") == item_id:
                it["status"] = status
                if result:
                    it["result"] = str(result)[:300]
                break
        _queue_save(items)
    except Exception:
        pass


# ── 89 · Facebook auto-reply engine ──────────────────────────────────────────

def facebook_enabled() -> bool:
    return bool(get_cat05_config().get("facebook_enabled", False))


def facebook_match_reply(text: str) -> str | None:
    """Reply for an incoming Facebook message, or None.

    Reuses the SHARED keyword rules + default reply from plugin_config
    ["autoreply"] (the same rules WhatsApp/Instagram use), so the user
    manages one rule list. Returns None when Facebook auto-reply is off,
    or when nothing matches and no default is set. Never raises."""
    try:
        if not facebook_enabled():
            return None
        incoming = (text or "").strip()
        if not incoming:
            return None
        try:
            from core import autoreply as _ar
            cfg = _ar.get_config()
        except Exception:
            cfg = {}
        lowered = incoming.lower()
        for rule in cfg.get("rules") or []:
            keyword = str(rule.get("keyword", "")).strip().lower()
            if keyword and keyword in lowered:
                return str(rule.get("reply", "")).strip() or None
        default = str(cfg.get("default_reply", "") or "").strip()
        return default or None
    except Exception:
        return None


def _fb_send_message(sender_id: str, reply: str) -> str:
    """Send a Facebook Page message via the Graph API (Messenger send).
    Short status, never raises. Token is never logged."""
    try:
        tok, pid = _fb_token_and_page()
        if not tok:
            return ("Facebook Page token set kora nei — Connectors settings-e "
                    "Page token dao.")
        if _requests is None:
            return "Facebook-e pathate parlam na: requests install kora nei."
        # /me/messages works with a Page token; fall back to /{page-id}/messages.
        url = f"{_FB}/me/messages" if not pid else f"{_FB}/{pid}/messages"
        try:
            r = _requests.post(url, params={"access_token": tok},
                               json={"recipient": {"id": sender_id},
                                     "message": {"text": reply}},
                               timeout=_TIMEOUT)
            data = r.json() if r.text else {}
        except Exception as e:
            return f"Facebook-e pathate parlam na: network error: {e}"
        if r.status_code not in (200, 201) or not isinstance(data, dict):
            err = ""
            if isinstance(data, dict):
                err = str(((data.get("error") or {}).get("message", "")))[:120]
            return (f"Facebook-e pathano jay ni (HTTP {r.status_code})"
                    + (f": {err}" if err else "."))
        return "✅ Facebook-e reply pathano holo."
    except Exception as e:
        return f"Facebook-e pathate parlam na: {e}"


def handle_facebook_incoming(sender_id: str, text: str, player=None) -> str:
    """Handle one incoming Facebook message. Returns a short status string:
    "disabled" / "no reply" / the send result. Never raises."""
    try:
        sender_id = (sender_id or "").strip()
        text = (text or "").strip()
        if not sender_id or not text:
            return "Khali message — reply korar moto kichu nei."
        if not facebook_enabled():
            return "disabled"
        reply = facebook_match_reply(text)
        if not reply:
            return "no reply"
        result = _fb_send_message(sender_id, reply)
        try:
            if player is not None:
                player.write_log(f"[Auto-reply] facebook: {result[:120]}")
        except Exception:
            pass
        return str(result)[:200]
    except Exception as e:
        return f"Facebook auto-reply korte parlam na: {e}"


def extract_facebook_messages(payload) -> list[tuple[str, str]]:
    """[(sender_id, text)] from a Facebook Page messaging webhook body.

    Same shape as Instagram: entry[].messaging[] — sender.id + message.text.
    Echoes (message.is_echo) and non-text messages are skipped. Bad payloads
    give an empty list, never an exception."""
    out: list[tuple[str, str]] = []
    try:
        if not isinstance(payload, dict):
            return out
        for entry in payload.get("entry") or []:
            if not isinstance(entry, dict):
                continue
            for item in entry.get("messaging") or []:
                if not isinstance(item, dict):
                    continue
                sender = item.get("sender") or {}
                message = item.get("message") or {}
                if not isinstance(sender, dict) or not isinstance(message, dict):
                    continue
                if message.get("is_echo"):
                    continue
                sender_id = str(sender.get("id", "") or "").strip()
                text = str(message.get("text", "") or "").strip()
                if sender_id and text:
                    out.append((sender_id, text))
    except Exception:
        return []
    return out


# ── 96 · Scheduled posting (creates a real automation TASK) ──────────────────

def schedule_post(platforms: list[str], when: str, kind: str = "daily",
                  date: str = "", weekday=None, file_path: str = "",
                  title: str = "", message: str = "", caption: str = "",
                  description: str = "", image_url: str = "",
                  privacy: str = "private") -> str:
    """Create a scheduled automation TASK (core.automation.ENGINE.create_task)
    that posts/uploads at the given time. This is a TASK, not a template —
    templates live in automation.py. Never raises."""
    try:
        from core.automation import ENGINE
    except Exception as e:
        return f"Scheduled post korte parlam na (automation load hoy ni): {e}"
    try:
        when = (when or "").strip()
        if not re.match(r"^\d{1,2}:\d{2}$", when):
            return "Scheduled post-er jonno time dao HH:MM format-e (e.g. 18:00)."
        hh, mm = when.split(":")
        when = f"{int(hh):02d}:{int(mm):02d}"
        kind = (kind or "daily").strip().lower()
        if kind not in ("once", "daily", "weekly"):
            return "kind once, daily, ba weekly hote hobe."
        plats = [str(p or "").strip().lower()
                 for p in (platforms or []) if str(p or "").strip()]
        if not plats:
            return "Kon platform-e post hobe — youtube, instagram, ba facebook dao."
        for p in plats:
            if p not in ("youtube", "instagram", "facebook"):
                return f"Platform '{p}' bujhlam na — youtube, instagram, ba facebook dao."
        file_path = (file_path or "").strip()
        image_url = (image_url or "").strip()
        title = (title or "").strip()
        message = (message or "").strip()
        caption = (caption or "").strip()
        description = (description or "").strip()
        steps: list[dict] = []
        for p in plats:
            if p == "youtube":
                if not file_path:
                    return "YouTube scheduled upload-er jonno file_path dao."
                if not title:
                    return "YouTube scheduled upload-er jonno title dao."
                steps.append({"tool": "youtube_upload",
                              "args": {"file_path": file_path, "title": title,
                                       "description": description,
                                       "privacy": (privacy or "private").strip().lower() or "private"}})
            elif p == "instagram":
                if image_url:
                    steps.append({"tool": "instagram_post",
                                  "args": {"image_url": image_url,
                                           "caption": caption or message}})
                elif file_path:
                    # Honest limit: IG Graph API takes a public URL, not a
                    # local file — the step will say so at run time if the
                    # file is still local. Warn now, in the answer.
                    steps.append({"tool": "instagram_upload_video",
                                  "args": {"file_path_or_url": file_path,
                                           "caption": caption or message}})
                else:
                    return "Instagram scheduled post-er jonno file_path ba image_url dao."
            else:  # facebook
                if file_path:
                    steps.append({"tool": "facebook_upload_video",
                                  "args": {"file_path": file_path,
                                           "title": title or "Video",
                                           "description": description or message}})
                elif message:
                    steps.append({"tool": "facebook_post",
                                  "args": {"message": message}})
                else:
                    return "Facebook scheduled post-er jonno file_path (video) ba message dao."
        trigger: dict = {"type": "time", "kind": kind, "time": when}
        if kind == "once":
            if not (date or "").strip():
                return "once-er jonno date dao (YYYY-MM-DD)."
            trigger["date"] = (date or "").strip()
        elif kind == "weekly":
            trigger["weekday"] = weekday if weekday is not None else 0
        name = f"Scheduled post ({', '.join(plats)}) {when}"
        task_id = ENGINE.create_task({"name": name, "trigger": trigger,
                                      "steps": steps,
                                      "description": ("Social post scheduled via "
                                                      "cat05_social — edit in Automation.")})
        if not task_id:
            return "Scheduled post task banate parlam na — trigger/steps check koro."
        note = (f"✅ Scheduled post task banalam: {name} (id {task_id}). "
                f"{kind} {when}" + (f" {date}" if kind == "once" else "") + ".")
        if "instagram" in plats and file_path and not image_url:
            note += (" Note: Instagram-e local file cholbe na — post-er age "
                     "video-ta public URL-e rakhte hobe, na hole oi step fail korbe.")
        return note
    except Exception as e:
        return f"⚠️ Scheduled post: {e}"
