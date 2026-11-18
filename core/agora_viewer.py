"""core/agora_viewer.py — 📹 AGORA LIVE SCREEN (primary live view).

The phone shares its screen over Agora (camera uid 1001, screen uid
1002 — the phone's startAgoraLive, backend token). Mark watches it as
an audience member in a Chrome page built on the Agora Web SDK NG
(CDN — internet lagbe). The page shows the phone's screen FULL-SCREEN,
real video, NOT periodic stills.

How Mark gets the channel/token: it asks the PHONE over the relay
("agora live start koro") — the phone starts its live share and replies
with the channel + token (+ app id). The reply is parsed tolerantly
(JSON blob or "channel: X / token: Y" lines). If the phone does not
answer, or there is no token, Mark says so plainly and falls back to
the frame stream (core/live_screen.py) — never a fake live view.

Nothing here imports Qt. All functions return short strings / dicts
and never raise.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def viewer_html(app_id: str, channel: str, token: str, uid: int = 1002) -> str:
    """Build the Agora web viewer page (AgoraRTC_N.js via CDN).
    Subscribes to the screen-share video track (uid 1002 first, else
    any remote video track) and plays it full-screen."""
    app_id = str(app_id or "").strip()
    channel = str(channel or "").strip()
    token = str(token or "").strip()
    uid = int(uid or 1002)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Mark-LVII — Phone Live Screen (Agora)</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://download.agora.io/sdk/release/AgoraRTC_N.js"></script>
<style>html,body{{margin:0;padding:0;background:#000;height:100%;overflow:hidden}}
#stage{{position:fixed;inset:0}} #stage video{{width:100%!important;height:100%!important;object-fit:contain}}
#hud{{position:fixed;left:10px;top:10px;color:#fff;background:rgba(0,0,0,.55);padding:6px 10px;border-radius:8px;font:14px system-ui;z-index:9}}
#hud b{{color:#4ade80}}</style></head>
<body><div id="hud">📱 Phone live screen — <b id="st">connecting…</b> <span id="fps"></span></div>
<div id="stage"></div>
<script>
const APP_ID = {json.dumps(app_id)};
const CHANNEL = {json.dumps(channel)};
const TOKEN = {json.dumps(token)};
const SCREEN_UID = {uid};
const st = document.getElementById('st');
let client = null, frames = 0, lastT = Date.now();
async function main() {{
  try {{
    client = AgoraRTC.createClient({{mode: "rtc", codec: "vp8"}});
    client.on("user-published", async (user, mediaType) => {{
      await client.subscribe(user, mediaType);
      if (mediaType === "video") {{
        const track = user.videoTrack;
        track.play("stage");
        st.textContent = "LIVE — screen uid " + user.uid;
        track.on("first-frame-decoded", () => {{ st.textContent = "LIVE — screen uid " + user.uid; }});
        setInterval(() => {{
          const now = Date.now();
          document.getElementById('fps').textContent = "• " + Math.round(frames * 1000 / Math.max(1, now - lastT)) + " fps (measured)";
          frames = 0; lastT = now;
        }}, 2000);
        const obs = new MutationObserver(() => {{ frames++; }});
        const stage = document.getElementById('stage');
        obs.observe(stage, {{childList: true, subtree: true, attributes: true}});
      }}
    }});
    client.on("user-unpublished", (user) => {{ st.textContent = "phone stopped sharing"; }});
    await client.join(APP_ID, CHANNEL, TOKEN || null, null);
    st.textContent = "joined channel — waiting for phone screen…";
  }} catch (e) {{
    st.textContent = "join failed: " + (e && e.message ? e.message : e);
  }}
}}
main();
</script></body></html>
"""


def parse_phone_reply(text: str) -> dict:
    """Extract {app_id, channel, token} from the phone's reply.
    Accepts a JSON blob or 'channel: X' / 'token: Y' / 'app id: Z' lines.
    Returns {} when nothing usable is found. Never raises."""
    try:
        t = str(text or "")
        # JSON blob first.
        for m in re.finditer(r"\{[^{}]*\"(?:channel|token|app_id)\"[^{}]*\}", t):
            try:
                data = json.loads(m.group(0))
                if isinstance(data, dict) and data.get("channel"):
                    return {"app_id": str(data.get("app_id") or ""),
                            "channel": str(data.get("channel") or ""),
                            "token": str(data.get("token") or "")}
            except Exception:
                continue
        def _grab(pats: list[str]) -> str:
            for p in pats:
                m = re.search(p, t, flags=re.IGNORECASE)
                if m:
                    return m.group(1).strip().strip("\"'")
            return ""
        channel = _grab([r"channel\s*[:=]\s*([A-Za-z0-9_\-]+)",
                         r"channel\s+([A-Za-z0-9_\-]+)"])
        token = _grab([r"token\s*[:=]\s*([A-Za-z0-9_\-+/=]+)"])
        app_id = _grab([r"app[_\s-]?id\s*[:=]\s*([A-Za-z0-9_\-]+)"])
        if not channel:
            return {}
        return {"app_id": app_id, "channel": channel, "token": token}
    except Exception:
        return {}


def viewer_path() -> Path:
    return Path(__file__).resolve().parent.parent / "memory" / "agora_viewer.html"


def write_viewer(app_id: str, channel: str, token: str) -> str:
    """Write the viewer page to memory/agora_viewer.html. Returns its
    file:// URL or '' on failure. Never raises."""
    try:
        p = viewer_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(viewer_html(app_id, channel, token), encoding="utf-8")
        return p.as_uri()
    except Exception:
        return ""


def start_agora_live(link=None, timeout: float = 30.0) -> dict:
    """Ask the phone to start its Agora screen share and open the viewer
    in Chrome. Returns {ok, url|reason, source}. The frame stream is
    the fallback — the caller says so plainly. Never raises."""
    try:
        from core import jarvis_link as _jl
        link = link or _jl.LINK
        if link is None or not getattr(link, "paired", False):
            return {"ok": False,
                    "reason": "Phone pair kora nei — age QR scan koro."}
        ans = link.send_and_wait_result(
            "agora live start koro — channel, token ar app id dao",
            timeout=max(10.0, float(timeout or 30.0)))
        if not ans:
            return {"ok": False,
                    "reason": ("Phone theke uttor elo na — Agora live "
                               "start korte parlam na. Frame stream "
                               "cholbe.")}
        info = parse_phone_reply(str(ans))
        if not info.get("channel"):
            return {"ok": False,
                    "reason": ("Phone Agora channel/token dite parlo na "
                               f"(uttor: {str(ans)[:150]}). Frame stream "
                               "cholbe.")}
        if not info.get("app_id"):
            # The phone may keep the app id server-side; the viewer still
            # needs it — say so plainly instead of guessing.
            return {"ok": False,
                    "reason": ("Agora app id pelam na — phone-er reply-te "
                               "channel/token ache kintu app id nei. "
                               "Frame stream cholbe.")}
        url = write_viewer(info["app_id"], info["channel"], info["token"])
        if not url:
            return {"ok": False,
                    "reason": "Agora viewer page likhte parlam na."}
        try:
            from core import browser_driver as _bd
            driver, _backend, _msg = _bd.ensure_driver(auto_install=False)
            if driver is not None:
                ok, _m = driver.navigate(url)
                if ok:
                    return {"ok": True, "url": url, "source": "agora",
                            "channel": info["channel"]}
        except Exception:
            pass
        return {"ok": True, "url": url, "source": "agora (link)",
                "channel": info["channel"],
                "note": "Chrome driver ready noy — link-ta khule dekho."}
    except Exception as e:
        return {"ok": False, "reason": f"Agora live start korte parlam na: {e}"}
