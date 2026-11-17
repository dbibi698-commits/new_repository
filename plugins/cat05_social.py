"""plugins/cat05_social.py — 📱 SOCIAL MEDIA & VIDEO UPLOAD (Category 5,
features 81-100 of the 200-feature list).

One discovered tool ("social_media") with an `action` dispatcher — the same
pattern as plugins/jarvis_automation.py ("automation" + action). A plugin file
can only carry ONE PLUGIN dict, so the category's sub-tools are actions here:
youtube_shorts_upload, instagram_story, comment_manager, caption_ai,
thumbnail_maker, cross_post, upload_queue, scheduled_post, analytics_summary,
broadcast_message, content_ideas, facebook_autoreply, link_in_bio, status.
The real work lives in core/cat05_social.py; this file only dispatches,
threads the slow uploads, and orchestrates other tools.

ALREADY WORKING elsewhere (verified in code, not assumed — see report):
  81 youtube_upload, 83 instagram_upload_video (Reels = same container flow),
  84 instagram_post (feed photo), 85 facebook_upload_video,
  86 facebook_post, 87/88 autoreply (WhatsApp/Instagram), 95 live progress
  (every 10% in the three upload plugins).

CONFIRM-FIRST: cross_post and youtube_shorts_upload with privacy=public ask
first (confirm=false, the app_install.py pattern) and only publish when the
user confirms with confirm=true. Facebook/Instagram uploads go public the
moment they run, so they always need that confirmation inside cross_post.

FACEBOOK AUTO-REPLY — DASHBOARD PATCH (server.py, NOT edited here):
The webhook handler lives in core/cat05_social.py (handle_facebook_incoming /
extract_facebook_messages, reusing the shared rules in plugin_config
["autoreply"]). To wire it, dashboard/server.py needs this exact patch,
placed right after the Instagram webhook routes (~line 1272):

    # ── after the instagram webhook routes ──
    @app.get("/webhooks/facebook")
    async def facebook_webhook_get(req: Request):
        return _webhook_verify(req, "facebook")

    @app.post("/webhooks/facebook")
    async def facebook_webhook_post(req: Request):
        return await _webhook_receive(req, "facebook")

...plus, inside _webhook_verify, after the `expected = ...` line, add the
Facebook fallback (the autoreply get_config() only knows whatsapp/instagram
keys, so the Facebook verify token lives in plugin_config["cat05_social"]):

        if platform == "facebook" and not expected:
            try:
                from memory.config_manager import get_plugin_config as _gpc
                expected = str((_gpc("cat05_social") or {}).get(
                    "facebook_verify_token", "") or "").strip()
            except Exception:
                expected = ""

...plus, inside _webhook_receive, after the whatsapp/instagram extraction:

        if platform == "facebook":
            try:
                from core import cat05_social as _c05
                messages = _c05.extract_facebook_messages(body)
            except Exception:
                messages = []

...and inside its per-message loop, replace the handle_incoming call with:

        if platform == "facebook":
            from core import cat05_social as _c05
            result = await asyncio.to_thread(
                _c05.handle_facebook_incoming, sender_id, text)
        else:
            result = await asyncio.to_thread(
                _ar.handle_incoming, platform, sender_id, text)

The user must still paste https://mark-lvii-dashboard.onrender.com/webhooks/facebook
into their own Meta app (Facebook product → Webhooks → subscribe to "messages")
with the SAME verify token from Settings — Mark cannot register it for them,
exactly like WhatsApp/Instagram. NEEDS-KEY (Meta app setup + Page token).

run() returns a short string and never raises. No Qt anywhere.
"""
from __future__ import annotations

import json
import threading

PLUGIN = {
    "name": "social_media",
    "description": (
        "Social media + video upload hub (Category 5). Actions: "
        "'youtube_shorts_upload' (Shorts via the YouTube upload API + #Shorts, "
        "needs OAuth token); 'instagram_story' (publish a Story from a public "
        "image/video URL, media_type=STORIES); 'comment_manager' (list/reply/"
        "hide/delete Facebook + Instagram comments); 'caption_ai' (Gemini "
        "caption + hashtags); 'thumbnail_maker' (PIL 1280x720 thumbnail PNG); "
        "'cross_post' (one video to YouTube + Instagram + Facebook — needs "
        "confirm=true, it goes public); 'upload_queue' (persistent upload "
        "queue: add/list/run-next/clear); 'scheduled_post' (schedule a post/"
        "upload as an automation task); 'analytics_summary' (YouTube views/"
        "likes/comments); 'broadcast_message' (WhatsApp Business template to "
        "APPROVED recipients only — never a scraped list); 'content_ideas' "
        "(trending topics + Gemini ideas + script outline); "
        "'facebook_autoreply' (Facebook Page auto-reply status/enable/disable "
        "— needs the Meta webhook pasted by the user, see plugin docs); "
        "'link_in_bio' (READ the current IG bio/website — the Graph API "
        "cannot update it, that edit is manual in the Instagram app); "
        "'status' (Category 5 overview). "
        "Do NOT use for plain uploads/posts — those are youtube_upload, "
        "instagram_upload_video, facebook_upload_video, facebook_post, "
        "instagram_post, autoreply."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "youtube_shorts_upload | instagram_story | "
                                      "comment_manager | caption_ai | thumbnail_maker | "
                                      "cross_post | upload_queue | scheduled_post | "
                                      "analytics_summary | broadcast_message | "
                                      "content_ideas | facebook_autoreply | link_in_bio | "
                                      "status."},
            "op": {"type": "STRING",
                   "description": "Sub-op: comment_manager = list|reply|hide|unhide|delete; "
                                  "upload_queue = add|list|run-next|clear; "
                                  "facebook_autoreply = status|enable|disable; "
                                  "link_in_bio = check|save."},
            "file_path": {"type": "STRING",
                          "description": "Local video/image file path (uploads, thumbnail source)."},
            "url": {"type": "STRING",
                    "description": "Public http(s) URL of the media (Instagram story / reel)."},
            "image_url": {"type": "STRING",
                          "description": "Public image URL (scheduled Instagram post)."},
            "title": {"type": "STRING", "description": "Video title."},
            "description": {"type": "STRING", "description": "Video description."},
            "caption": {"type": "STRING", "description": "Caption for Instagram/Facebook."},
            "message": {"type": "STRING",
                        "description": "Post text (scheduled Facebook post) or comment reply text."},
            "privacy": {"type": "STRING",
                        "description": "private (default), public, or unlisted (YouTube)."},
            "platform": {"type": "STRING",
                         "description": "facebook | instagram (comments, caption, story media kind)."},
            "platforms": {"type": "STRING",
                          "description": "Comma list for cross_post / scheduled_post: youtube,instagram,facebook."},
            "object_id": {"type": "STRING",
                          "description": "Post/media id whose comments to manage."},
            "comment_id": {"type": "STRING",
                           "description": "Comment id to reply to / hide / delete."},
            "topic": {"type": "STRING",
                      "description": "Topic/title for caption_ai and content_ideas."},
            "tone": {"type": "STRING",
                     "description": "Caption tone, e.g. friendly, funny, professional."},
            "count": {"type": "NUMBER",
                      "description": "How many content ideas (default 5, max 10)."},
            "video_id": {"type": "STRING",
                         "description": "YouTube video id for analytics_summary."},
            "channel_id": {"type": "STRING",
                           "description": "YouTube channel id for analytics_summary."},
            "template_name": {"type": "STRING",
                              "description": "Approved WhatsApp template name for broadcast_message."},
            "body_text": {"type": "STRING",
                          "description": "Template body text for broadcast_message."},
            "recipients": {"type": "STRING",
                           "description": "Comma-separated phone numbers for broadcast_message — only approved-list numbers receive anything; others are skipped and named."},
            "when": {"type": "STRING",
                     "description": "Scheduled post time HH:MM, e.g. 18:00."},
            "kind": {"type": "STRING",
                     "description": "once | daily (default) | weekly for scheduled_post."},
            "date": {"type": "STRING",
                     "description": "Date YYYY-MM-DD for a once-off scheduled_post."},
            "weekday": {"type": "NUMBER",
                        "description": "Weekday 0=Monday..6=Sunday for a weekly scheduled_post."},
            "tool": {"type": "STRING",
                     "description": "Upload tool name for upload_queue add."},
            "args": {"type": "STRING",
                     "description": "JSON object of tool args for upload_queue add."},
            "link": {"type": "STRING",
                     "description": "Desired bio link to save as a reminder (link_in_bio save)."},
            "output_path": {"type": "STRING",
                          "description": "Where to save the thumbnail PNG (optional — defaults to <image>_thumb.png next to the source)."},
            "is_video": {"type": "BOOLEAN",
                         "description": "True when the Instagram story URL is a video."},
            "confirm": {"type": "BOOLEAN",
                        "description": "False (default) = only ask for confirmation, publish nothing. True = publish now (only after the user confirmed)."},
        },
        "required": ["action"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "cat05_social",
    "title": "📱 SOCIAL MEDIA — Facebook auto-reply + broadcast",
    "fields": [
        {"key": "facebook_enabled", "type": "toggle",
         "label": "Facebook auto-reply on", "default": False},
        {"key": "facebook_verify_token", "type": "text",
         "label": "Facebook webhook verify token (you make this up, paste same in Meta app — paste https://mark-lvii-dashboard.onrender.com/webhooks/facebook into your Meta app yourself)",
         "placeholder": "e.g. mark-verify-123"},
        {"key": "broadcast_recipients", "type": "text",
         "label": "Broadcast recipients (approved only, comma-separated numbers with country code — nobody else ever receives a broadcast)",
         "placeholder": "8801XXXXXXXXX, 8801YYYYYYYYY"},
        {"key": "broadcast_template", "type": "text",
         "label": "Default approved WhatsApp template name for broadcasts",
         "placeholder": "hello_world",
         "default": "hello_world"},
    ],
}

_ACTIONS = (
    "youtube_shorts_upload", "instagram_story", "comment_manager",
    "caption_ai", "thumbnail_maker", "cross_post", "upload_queue",
    "scheduled_post", "analytics_summary", "broadcast_message",
    "content_ideas", "facebook_autoreply", "link_in_bio", "status",
)


def _log(player, text: str) -> None:
    if player is None:
        return
    try:
        player.write_log(text)
    except Exception:
        pass


def _as_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value) if value is not None else default


def _is_problem(result: str) -> bool:
    try:
        from core import outcome
        return outcome.is_problem(result)
    except Exception:
        pass
    text = str(result or "")
    return (not text.strip() or text.lstrip().startswith(("⚠️", "❌"))
            or "failed" in text.lower())


def _runner(player):
    """(callable, where-from) — player.run_tool first (actions+plugins),
    else the automation engine's full runner (incl. inline tools), else
    (None, reason). Never raises."""
    try:
        fn = getattr(player, "run_tool", None)
        if callable(fn):
            return fn, "player"
    except Exception:
        pass
    try:
        from core.automation import ENGINE
        fn = ENGINE.get_tool_runner()
        if callable(fn):
            return fn, "automation-engine"
    except Exception:
        pass
    return None, "no runner wired"


def _run_via(runner, name: str, args: dict) -> str:
    try:
        return str(runner(name, dict(args or {})) or "")
    except Exception as e:
        return f"⚠️ {name}: {e}"


def _status() -> str:
    try:
        from core import cat05_social as c05
        fb = c05.get_cat05_config()
        queue = c05._queue_load()
    except Exception:
        fb, queue = {}, []
    lines = ["📱 Social Media & Video Upload (Category 5):",
             "• YouTube upload: ✅ youtube_upload (OAuth) — Shorts: youtube_shorts_upload action",
             "• Instagram: ✅ instagram_upload_video (Reels) + instagram_post; Story: instagram_story action",
             "• Facebook: ✅ facebook_upload_video + facebook_post",
             "• Auto-reply: ✅ WhatsApp + Instagram (autoreply); Facebook: "
             + ("✅ ON" if fb.get("facebook_enabled") else "❌ OFF")
             + " — webhook needs the server.py patch + Meta paste (see plugin docs)",
             "• Upload queue: " + (f"{len(queue)} job(s)" if queue else "khali"),
             "• Analytics / captions / thumbnails / ideas: actions in this plugin.",
             "Tokens: Plugin Settings > 🔗 CONNECTORS (YouTube OAuth, IG/FB tokens)."]
    return "\n".join(lines)


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        from core import cat05_social as c05
    except Exception as e:
        return f"Social media korte parlam na (cat05 helper load hoy ni): {e}"
    try:
        params = parameters or {}
        action = str(params.get("action") or "status").strip().lower()
        if action not in _ACTIONS:
            return ("Action dao: " + ", ".join(_ACTIONS) + ".")
        op = str(params.get("op") or "").strip().lower()

        if action == "status":
            return _status()

        # ── 82 · YouTube Shorts (threaded — resumable upload is slow) ──
        if action == "youtube_shorts_upload":
            import os
            file_path = str(params.get("file_path", "") or "").strip()
            title = str(params.get("title", "") or "").strip()
            description = str(params.get("description", "") or "")
            privacy = str(params.get("privacy", "private") or "private").strip().lower()
            confirm = _as_bool(params.get("confirm", False))
            if privacy == "public" and not confirm:
                return (f"⚠️ Confirm koro: '{title or file_path}' YouTube Shorts hishebe "
                        "PUBLIC-e jabe. Public korte chaile abar confirm=true diye bolo; "
                        "na hole privacy private/unlisted dao.")
            if not file_path or not os.path.isfile(file_path):
                return f"⚠️ YouTube Shorts upload: file-ta pelam na: {file_path or '(khali)'}"
            if not title:
                return "⚠️ YouTube Shorts upload: video-r title dao."
            state = {"last": -1}

            def _progress(pct: int) -> None:
                bucket = (int(pct) // 10) * 10
                if bucket != state["last"]:
                    state["last"] = bucket
                    _log(player, f"⏫ YouTube Shorts upload {bucket}% — {title}")

            def _work() -> None:
                try:
                    result = c05.youtube_shorts_upload(
                        file_path, title, description, privacy,
                        progress_cb=_progress)
                except Exception as e:  # never let the thread die silently
                    result = f"⚠️ YouTube Shorts upload: {e}"
                _log(player, result)

            _log(player, f"⏫ YouTube Shorts upload shuru holo: {title} ({privacy})")
            threading.Thread(target=_work, daemon=True).start()
            return (f"YouTube Shorts upload shuru holo: {title} — progress log-e "
                    "dekhabe, seshe video link log-e asbe.")

        # ── 84 · Instagram Story (threaded — video polling can take ~2 min) ──
        if action == "instagram_story":
            url = str(params.get("url", "") or "").strip()
            is_video = _as_bool(params.get("is_video", False))
            if not url.startswith("http"):
                return ("⚠️ Instagram Story: PUBLIC image/video URL dao — local file "
                        "Graph API ney na.")
            state = {"last": -1}

            def _progress(pct: int) -> None:
                bucket = (int(pct) // 10) * 10
                if bucket != state["last"]:
                    state["last"] = bucket
                    _log(player, f"⏫ Instagram Story {bucket}%...")

            def _work() -> None:
                try:
                    result = c05.instagram_story(url, is_video=is_video,
                                                   progress_cb=_progress)
                except Exception as e:
                    result = f"⚠️ Instagram Story: {e}"
                _log(player, result)

            _log(player, "⏫ Instagram Story publish shuru holo...")
            threading.Thread(target=_work, daemon=True).start()
            return ("Instagram Story publish shuru holo — seshe result log-e asbe "
                    "(story 24 ghonta thakbe).")

        # ── 90 · Comment manager ──
        if action == "comment_manager":
            return c05.comment_manager(
                str(params.get("platform", "") or ""),
                str(params.get("object_id", "") or ""),
                op or "list",
                message=str(params.get("message", "") or ""),
                comment_id=str(params.get("comment_id", "") or ""))

        # ── 91 · Caption + hashtags ──
        if action == "caption_ai":
            return c05.caption_generate(
                str(params.get("topic", "") or "") or str(params.get("title", "") or ""),
                platform=str(params.get("platform", "instagram") or "instagram"),
                tone=str(params.get("tone", "friendly") or "friendly"))

        # ── 92 · Thumbnail maker ──
        if action == "thumbnail_maker":
            return c05.thumbnail_make(
                str(params.get("file_path", "") or ""),
                str(params.get("title", "") or "") or str(params.get("topic", "") or ""),
                str(params.get("output_path", "") or ""))

        # ── 93 · Cross-post one click ──
        if action == "cross_post":
            import os
            file_path = str(params.get("file_path", "") or "").strip()
            title = str(params.get("title", "") or "").strip()
            caption = str(params.get("caption", "") or "") or str(params.get("description", "") or "")
            description = str(params.get("description", "") or "") or caption
            privacy = str(params.get("privacy", "private") or "private").strip().lower()
            plats = [p.strip().lower() for p in
                     str(params.get("platforms", "") or "").split(",") if p.strip()]
            if not plats:
                plats = ["youtube", "instagram", "facebook"]
            confirm = _as_bool(params.get("confirm", False))
            if not file_path or not os.path.isfile(file_path):
                return f"⚠️ Cross-post: video file-ta pelam na: {file_path or '(khali)'}"
            if not title:
                return "⚠️ Cross-post: video-r title dao."
            bad = [p for p in plats if p not in ("youtube", "instagram", "facebook")]
            if bad:
                return f"Platform bujhlam na: {', '.join(bad)} — youtube, instagram, facebook dao."
            # Facebook + Instagram publish the moment they run; a public
            # YouTube upload does too. Confirm-first for all of those.
            goes_public = ("facebook" in plats or "instagram" in plats
                           or privacy == "public")
            if goes_public and not confirm:
                return (f"⚠️ Confirm koro: '{title}' {', '.join(plats)}-e jabe — "
                        "Facebook/Instagram-e gele sathe sathe public hobe. "
                        "Post korte chaile abar confirm=true diye bolo.")
            runner, _where = _runner(player)
            if runner is None:
                return ("⚠️ Cross-post korte parlam na — kono tool runner wired nei "
                        "(player.run_tool ba automation engine). Mark restart kore abar try koro.")
            results = []
            ok = 0
            for p in plats:
                if p == "youtube":
                    res = _run_via(runner, "youtube_upload",
                                   {"file_path": file_path, "title": title,
                                    "description": description, "privacy": privacy})
                elif p == "instagram":
                    res = _run_via(runner, "instagram_upload_video",
                                   {"file_path_or_url": file_path, "caption": caption})
                else:
                    res = _run_via(runner, "facebook_upload_video",
                                   {"file_path": file_path, "title": title,
                                    "description": description})
                if not _is_problem(res):
                    ok += 1
                results.append(f"{p}: {res[:220]}")
                _log(player, f"📱 Cross-post {p}: {res[:200]}")
            return (f"📱 Cross-post: {ok}/{len(plats)}-ta platform-e pathano holo.\n"
                    + "\n".join(results))

        # ── 94 · Upload queue ──
        if action == "upload_queue":
            qop = op or "list"
            if qop == "list":
                return c05.queue_list()
            if qop == "clear":
                return c05.queue_clear(_as_bool(params.get("confirm"), False))
            if qop == "add":
                args = params.get("args")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        return "upload_queue add-er args JSON object hote hobe."
                return c05.queue_add(str(params.get("tool", "") or ""),
                                     dict(args or {}))
            if qop == "run-next":
                job = c05.queue_next_job()
                if job is None:
                    return "Queue-e kono queued job nei — add koro age."
                runner, _where = _runner(player)
                if runner is None:
                    return ("⚠️ Queue run korte parlam na — kono tool runner wired nei "
                            "(player.run_tool ba automation engine). Mark restart kore abar try koro.")
                c05.queue_mark(job["id"], "running")
                result = _run_via(runner, str(job.get("tool", "")),
                                  dict(job.get("args") or {}))
                if _is_problem(result):
                    c05.queue_mark(job["id"], "failed", result)
                    return f"❌ Queue job {job['id']} ({job.get('tool')}) fail holo: {result[:200]}"
                c05.queue_mark(job["id"], "done", result)
                return f"✅ Queue job {job['id']} ({job.get('tool')}) cholche/sesh: {result[:200]}"
            return "upload_queue op add, list, run-next, ba clear hote hobe."

        # ── 96 · Scheduled posting ──
        if action == "scheduled_post":
            plats = [p.strip().lower() for p in
                     str(params.get("platforms", "") or "").split(",") if p.strip()]
            weekday = params.get("weekday")
            try:
                weekday = int(weekday) if weekday is not None and str(weekday) != "" else None
            except Exception:
                weekday = None
            return c05.schedule_post(
                plats, str(params.get("when", "") or ""),
                kind=str(params.get("kind", "daily") or "daily"),
                date=str(params.get("date", "") or ""),
                weekday=weekday,
                file_path=str(params.get("file_path", "") or ""),
                title=str(params.get("title", "") or ""),
                message=str(params.get("message", "") or ""),
                caption=str(params.get("caption", "") or ""),
                description=str(params.get("description", "") or ""),
                image_url=str(params.get("image_url", "") or ""),
                privacy=str(params.get("privacy", "private") or "private"))

        # ── 97 · Analytics summary ──
        if action == "analytics_summary":
            return c05.youtube_analytics(
                video_id=str(params.get("video_id", "") or ""),
                channel_id=str(params.get("channel_id", "") or ""))

        # ── 98 · Follower broadcast ──
        if action == "broadcast_message":
            return c05.whatsapp_broadcast(
                str(params.get("template_name", "") or ""),
                body_text=str(params.get("body_text", "") or ""),
                recipients=str(params.get("recipients", "") or ""))

        # ── 100 · Content ideas ──
        if action == "content_ideas":
            count = params.get("count", 5)
            try:
                count = int(count)
            except Exception:
                count = 5
            return c05.content_ideas_generate(
                str(params.get("topic", "") or ""), count=count)

        # ── 89 · Facebook auto-reply ──
        if action == "facebook_autoreply":
            fop = op or "status"
            if fop == "status":
                cfg = c05.get_cat05_config()
                lines = ["💬 Facebook auto-reply status:",
                         f"• Facebook: {'✅ ON' if cfg.get('facebook_enabled') else '❌ OFF'}"
                         f" — verify token {'set' if cfg.get('facebook_verify_token') else 'NOT SET'}",
                         "• Webhook: https://mark-lvii-dashboard.onrender.com/webhooks/facebook",
                         "• Rules: WhatsApp/Instagram-er sathe SHARED — autoreply action-e rule banao.",
                         "Meta-te webhook URL + verify token nije paste korte hobe — "
                         "Mark eta tomar hoye korte pare na (dashboard/server.py-te "
                         "route patch-o lagbe, plugin docs-e deoa ache)."]
                return "\n".join(lines)
            if fop == "enable":
                c05.save_cat05_config({"facebook_enabled": True})
                cfg = c05.get_cat05_config()
                if not cfg.get("facebook_verify_token"):
                    return ("✅ Facebook auto-reply ON — kintu verify token set kora nei! "
                            "Settings-e verify token dao ar Meta app-e webhook URL + oi "
                            "token paste koro, na hole Meta message pathabe na.")
                return ("✅ Facebook auto-reply ON. Webhook: "
                        "https://mark-lvii-dashboard.onrender.com/webhooks/facebook — "
                        "Meta app-e eta paste kora ache kina check koro.")
            if fop == "disable":
                c05.save_cat05_config({"facebook_enabled": False})
                return "❌ Facebook auto-reply OFF."
            return "facebook_autoreply op status, enable, ba disable hote hobe."

        # ── 99 · Link in bio (read-only — API-limited) ──
        if action == "link_in_bio":
            return c05.link_in_bio(action=op or "check",
                                   link=str(params.get("link", "") or ""))

        return "Bujhlam na — action-ta check koro."
    except Exception as e:
        return f"Social media korte parlam na: {e}"
