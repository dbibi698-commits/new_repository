"""plugins/cat01_voice.py — 🎙️ VOICE & AI BRAIN (Category 1, features 1-20).

One plugin, seven sub-actions (the loader registers ONE tool per file, so a
suite like this dispatches on `action` — the same pattern as the `automation`
plugin). The model calls voice_tools(action="<one of these>", ...):

  think_plan       — think before speaking: Gemini plans a big question first.
  screen_vision    — describe what's on the PC screen / where to click.
  photo_understand — describe a photo + read the text in it (OCR).
  emotion_check    — emotion of the last utterance + suggested reply tone.
  translate        — translate text to another language (voice reply is TTS).
  dictate          — dictation note: append / read / clear (persisted).
  suggest_next     — 1-3 next actions from recent automation history.

Features 1-4, 6-11, 14, 16 of the category already exist in the app (Live
session, moods, memory, providers, interrupt) — this file only builds the
ones that were missing. Feature 15 (custom wake word) is NOT built: the wake
model is the hardcoded pretrained "hey_jarvis" ONNX model in
core/wake_word.py, and a custom phrase needs a trained model — there is no
config value that could change it. Feature 2 (live voice call) is partial by
design: two-way voice via TTS exists, a true live call does not.

run() never raises and never touches Qt. Every model call goes through
core.gemini with a local fallback, and a missing key / dead model degrades
to an honest sentence instead of silence. No secrets are read or stored here.
"""
from __future__ import annotations

PLUGIN = {
    "name": "voice_tools",
    "description": (
        "Voice & AI brain helpers. Call with action=think_plan when a big "
        "question needs a short plan BEFORE answering (give `question`). "
        "action=screen_vision to describe what's on the PC screen right now "
        "or find where to click (give `question`, e.g. 'where is the Send "
        "button?'). action=photo_understand to describe a photo and read "
        "the text in it (give `path` to the image file, optional "
        "`question`). action=emotion_check to work out the emotion in what "
        "the user just said and how to reply (give `text`). "
        "action=translate to translate text into another language (give "
        "`text` and `target_language`, e.g. Bengali, Hindi, English). "
        "action=dictate for dictation: append spoken text to a saved note "
        "(give `text`), read the note back (`mode`=read), or clear it "
        "(`mode`=clear + `confirm`=yes). action=suggest_next for 1-3 "
        "suggested next actions based on what Mark has done recently. "
        "Do NOT use this for changing the mood (use set_mood), for "
        "switching AI provider (use provider_status / AI PROVIDERS "
        "settings), or for a live phone call."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "think_plan | screen_vision | photo_understand | "
                    "emotion_check | translate | dictate | suggest_next"
                ),
            },
            "question": {
                "type": "STRING",
                "description": (
                    "think_plan: the question to plan. screen_vision / "
                    "photo_understand: what to look for in the image."
                ),
            },
            "text": {
                "type": "STRING",
                "description": (
                    "emotion_check: the utterance to read the emotion of. "
                    "translate: the text to translate. dictate: the text "
                    "to append to the dictation note."
                ),
            },
            "path": {
                "type": "STRING",
                "description": "photo_understand: path to the image file.",
            },
            "target_language": {
                "type": "STRING",
                "description": "translate: language to translate into.",
            },
            "mode": {
                "type": "STRING",
                "description": "dictate: append (default) | read | clear.",
            },
            "confirm": {
                "type": "STRING",
                "description": "dictate clear needs confirm=yes.",
            },
        },
        "required": ["action"],
    },
}

_ACTIONS = (
    "think_plan", "screen_vision", "photo_understand", "emotion_check",
    "translate", "dictate", "suggest_next",
)

_DICTATION_NS = "cat01_dictation"
_DICTATION_KEY = "note"
_NOTE_CAP = 20_000          # chars kept in the dictation note
_SPEECH_CAP = 600            # chars of model output spoken back

# Tiny local fallback for emotion_check when no model answers: word lists,
# Bengali + English + Hindi. Only a hint — the model answer wins whenever
# there is one.
_EMOTION_WORDS = {
    "happy": ("khushi", "happy", "great", "bhalo", "moja", "khush", "awesome",
              "bhalo lagche", "darun", "fantastic"),
    "sad": ("dukho", "sad", "mon kharap", "kharap lagche", "upset", "dukkho",
            "crying", "kanna"),
    "angry": ("rag", "angry", "rege", "birokto", "annoyed", "frustrated",
              "rag hoyeche", "gussa"),
    "tired": ("klanto", "tired", "ghum", "sleepy", "exhausted", "thaka"),
    "worried": ("chinta", "worried", "tension", "bhoy", "afraid", "anxious",
                "chintito"),
    "excited": ("excited", "darun", "josh", "can't wait", "uthshaho"),
}
_EMOTION_TONE = {
    "happy": "playful and warm",
    "sad": "gentle and caring",
    "angry": "calm, patient and short",
    "tired": "soft and brief",
    "worried": "reassuring and clear",
    "excited": "upbeat and warm",
}


def _short(text: str, cap: int = _SPEECH_CAP) -> str:
    """One short spoken reply: single-spaced, capped, never empty."""
    out = " ".join(str(text or "").split())
    if len(out) > cap:
        out = out[:cap].rsplit(" ", 1)[0].rstrip() + "…"
    return out or "Kichu bolte parlam na."


def _gemini_text(prompt: str, tier: str, timeout_ms: int = 30_000) -> str:
    """core.gemini.text, or '' when nothing answered. Never raises."""
    try:
        from core import gemini
        return (gemini.text(prompt, tier=tier, timeout_ms=timeout_ms) or "").strip()
    except Exception:
        return ""


def _vision_call(image_bytes: bytes, mime: str, prompt: str,
                 timeout_ms: int = 60_000):
    """One image + prompt through core.gemini.call (the vision path).

    Returns the reply text, or '' when the model / SDK could not answer.
    Never raises. Image input is supported by gemini.call via
    google.genai.types.Part.from_bytes — the same call actions/
    computer_control.py uses for click-target screenshots.
    """
    try:
        from google.genai import types as gtypes
        from core import gemini
        resp = gemini.call(
            [gtypes.Part.from_bytes(data=image_bytes, mime_type=mime), prompt],
            tier=gemini.SMART, timeout_ms=timeout_ms)
        if resp is None:
            return ""
        return (getattr(resp, "text", None) or "").strip()
    except Exception:
        return ""


def _mime_for(path: str) -> str:
    ext = str(path or "").rsplit(".", 1)[-1].strip().lower() if "." in str(path or "") else ""
    return {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "webp": "image/webp", "gif": "image/gif"}.get(ext, "")


# ── think_plan ──────────────────────────────────────────────────────────────
def _think_plan(question: str) -> str:
    q = (question or "").strip()
    if not q:
        return "Kon proshner plan chai? Proshno-ta dao."
    answer = _gemini_text(
        "Make a SHORT plan for answering this question — at most 5 numbered "
        "steps, each one line, no preamble, no conclusion. Question: " + q,
        tier="smart", timeout_ms=30_000)
    if answer:
        return _short("Plan:\n" + answer)
    # Fallback without a model: a generic plan is still better than silence,
    # and it says so.
    return _short(
        "Model ekhon answer dite parlo na, tai ekta shadharon plan: 1) "
        f"Proshno-ta bhenge dekho — {q[:80]}. 2) Dorkari tothyo jachai koro. "
        "3) Dhaper por dhap uttor dao. 4) Sheshe ek line-e sharsongkhep dao.")


# ── screen_vision ───────────────────────────────────────────────────────────
def _capture_pc_screen() -> str:
    """PC screenshot via core/jarvis_link.py's capture helper (mss, then PIL
    ImageGrab fallback). Returns the saved JPEG path, or '' on failure.
    Reuses the link singleton when the app attached it, so no second link
    object is made in the running app."""
    try:
        from core import jarvis_link as _jl
        link = getattr(_jl, "LINK", None)
        if link is None:
            link = _jl.JarvisLink()
        return link.capture_pc_screen() or ""
    except Exception:
        return ""


def _screen_vision(question: str, player=None) -> str:
    q = (question or "").strip() or "Describe what's on the screen."
    path = _capture_pc_screen()
    if not path:
        return ("Screen-er screenshot nite parlam na — ei PC-te screen "
                "capture cholche na (headless ba onno display). Abar try "
                "koro, ba bolo ki khujcho.")
    try:
        with open(path, "rb") as fh:
            image_bytes = fh.read()
    except Exception:
        return "Screenshot nilam, kintu file-ta porte parlam na."
    prompt = (
        "This is a screenshot of a Windows PC screen. " + q +
        " Answer briefly, in the language of the question. If the question "
        "asks where to click, give the element's position as x,y in percent "
        "of screen width/height, or say NOT_FOUND when it is not visible.")
    answer = _vision_call(image_bytes, "image/jpeg", prompt)
    if answer:
        if player is not None:
            try:
                player.show_content("Screen vision", answer)
            except Exception:
                pass
        return _short(answer)
    return ("Screenshot nilam (" + path + "), kintu model ekhon chobi-ta "
            "porte parlo na — key ba quota dekho. Chobi-ta save ache, "
            "abar try korle hobe.")


# ── photo_understand ────────────────────────────────────────────────────────
def _photo_understand(path: str, question: str, player=None) -> str:
    p = (path or "").strip()
    if not p:
        return "Kon chobi? File-er path dao."
    mime = _mime_for(p)
    if not mime:
        return ("Ei file-ta chobi hishebe porte parlam na — PNG, JPG, "
                "WEBP ba GIF dao.")
    try:
        with open(p, "rb") as fh:
            image_bytes = fh.read()
    except Exception:
        return f"File-ta khulte parlam na: {p}"
    if not image_bytes:
        return "File-ta khali — kono chobi nei ete."
    q = (question or "").strip() or "Describe this photo in detail."
    prompt = (q + " Also read out any text visible in the image (OCR), "
              "word for word. Answer briefly, in the language of the "
              "question.")
    answer = _vision_call(image_bytes, mime, prompt)
    if answer:
        if player is not None:
            try:
                player.show_content("Photo", answer)
            except Exception:
                pass
        return _short(answer)
    # Model silent: still report what the file itself says, honestly.
    try:
        from PIL import Image
        import io as _io
        with Image.open(_io.BytesIO(image_bytes)) as img:
            size = f"{img.width}x{img.height} {img.format or ''}".strip()
    except Exception:
        size = f"{len(image_bytes)} bytes"
    return (f"Chobi-ta pelam ({size}), kintu model ekhon porte parlo na — "
            "key ba quota dekho, abar try korle hobe.")


# ── emotion_check ───────────────────────────────────────────────────────────
def _emotion_check(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return "Kar emotion dekhbo? Kotha-ta dao."
    answer = _gemini_text(
        "What emotion is in this message? Reply with ONLY one word from: "
        "happy, sad, angry, tired, worried, excited, neutral — then a "
        "comma, then the best reply tone in 3-5 words. Message: " + t,
        tier="fast", timeout_ms=20_000)
    emotion, tone = "", ""
    if answer:
        head = answer.split("\n")[0].strip().lower()
        parts = [p.strip() for p in head.split(",", 1)]
        if parts and parts[0] in _EMOTION_TONE or parts[0] == "neutral":
            emotion = parts[0]
            tone = parts[1] if len(parts) > 1 else ""
    if not emotion:
        low = t.lower()
        for name, words in _EMOTION_WORDS.items():
            if any(w in low for w in words):
                emotion, tone = name, _EMOTION_TONE[name]
                break
        else:
            emotion, tone = "neutral", "calm and friendly"
    if not tone:
        tone = _EMOTION_TONE.get(emotion, "calm and friendly")
    return f"Emotion: {emotion}. Reply in a {tone} tone."


# ── translate ───────────────────────────────────────────────────────────────
def _translate(text: str, target: str) -> str:
    t = (text or "").strip()
    if not t:
        return "Ki translate korbo? Text dao."
    lang = (target or "").strip() or "English"
    answer = _gemini_text(
        f"Translate the following text into {lang}. Reply with ONLY the "
        f"translation, no explanation, no quotes: {t}",
        tier="fast", timeout_ms=30_000)
    if answer:
        return _short(answer, cap=900)
    return ("Translate korte parlam na ekhon — model answer dilo na. "
            f"Original: {t[:200]}")


# ── dictate ─────────────────────────────────────────────────────────────────
def _dictate(text: str, mode: str, confirm: str) -> str:
    try:
        from memory.config_manager import get_plugin_config, save_plugin_config
    except Exception:
        return "Dictation note save korte parlam na — settings porte parini."
    mode = (mode or "append").strip().lower()
    if mode == "read":
        try:
            note = str((get_plugin_config(_DICTATION_NS) or {}).get(_DICTATION_KEY) or "")
        except Exception:
            note = ""
        if not note.strip():
            return "Dictation note khali — ekhono kichu lekha hoy ni."
        return _short("Dictation note:\n" + note, cap=900)
    if mode == "clear":
        if (confirm or "").strip().lower() != "yes":
            return "Note clear korte confirm=yes dao — na bolle clear korbo na."
        from memory.config_manager import bulk_clear_guard
        if not bulk_clear_guard("dictation note", True):
            return "Note clear korte parlam na — data protection guard atkalo."
        try:
            save_plugin_config(_DICTATION_NS, {_DICTATION_KEY: ""})
        except Exception:
            return "Note clear korte parlam na."
        return "Dictation note clear korlam."
    # append (default)
    t = (text or "").strip()
    if not t:
        return "Ki likhbo note-e? Text dao."
    try:
        cur = str((get_plugin_config(_DICTATION_NS) or {}).get(_DICTATION_KEY) or "")
        note = (cur + "\n" + t).strip() if cur else t
        if len(note) > _NOTE_CAP:
            note = note[-_NOTE_CAP:]
        save_plugin_config(_DICTATION_NS, {_DICTATION_KEY: note})
    except Exception:
        return "Note-e likhte parlam na."
    return "Note-e likhlam."


# ── suggest_next ────────────────────────────────────────────────────────────
def _recent_context() -> str:
    """Recent automation history + tasks, as one short text block.

    There is no todos store in this app (checked), so history is the source.
    """
    lines: list[str] = []
    try:
        from core.automation import ENGINE
        for h in (ENGINE.history() or [])[-5:]:
            lines.append(
                f"- {h.get('task_name') or h.get('task_id') or '?'}: "
                f"{h.get('status') or '?'}"
                + (f" ({h.get('duration_s')}s)" if h.get("duration_s") is not None else ""))
        for task in (ENGINE.list_tasks() or [])[:8]:
            if task.get("enabled"):
                trig = task.get("trigger") or {}
                lines.append(f"- scheduled: {task.get('name')} "
                             f"({trig.get('type') or '?'})")
    except Exception:
        pass
    return "\n".join(lines)


def _suggest_next() -> str:
    ctx = _recent_context()
    if not ctx.strip():
        return ("Ekhono kono automation history nei — prothome ekta task "
                "chalao ba schedule koro, tarpor ami next step suggest "
                "korbo. Ekta shuru: 'morning briefing' template diye ekta "
                "task banao.")
    answer = _gemini_text(
        "Based on this recent automation history, suggest 1-3 next actions "
        "for the user — short, concrete, one per line, no preamble. If the "
        "last task failed, suggesting a retry or a fix comes first.\n" + ctx,
        tier="fast", timeout_ms=30_000)
    if answer:
        return _short(answer)
    # Fallback without a model: read the history literally.
    failed = [ln for ln in ctx.splitlines() if "fail" in ln.lower()]
    if failed:
        return ("Last task-ta fail koreche — retry koro ba steps check "
                "koro: " + failed[-1].lstrip("- ").strip()[:200])
    return ("Recent history dekhe notun kichu suggest korte parlam na "
            "(model off). Last kaj: " + ctx.splitlines()[-1].lstrip("- ")[:200])


# ── dispatch ────────────────────────────────────────────────────────────────
def run(parameters: dict, player=None, session_memory=None) -> str:
    """Dispatch one voice_tools action. Never raises."""
    try:
        params = parameters or {}
        action = str(params.get("action") or "").strip().lower()
        if action not in _ACTIONS:
            return ("Action bujhlam na. Use koro: " +
                    ", ".join(_ACTIONS) + ".")
        if action == "think_plan":
            return _think_plan(str(params.get("question") or ""))
        if action == "screen_vision":
            return _screen_vision(str(params.get("question") or ""), player)
        if action == "photo_understand":
            return _photo_understand(str(params.get("path") or ""),
                                     str(params.get("question") or ""), player)
        if action == "emotion_check":
            return _emotion_check(str(params.get("text") or ""))
        if action == "translate":
            return _translate(str(params.get("text") or ""),
                              str(params.get("target_language") or ""))
        if action == "dictate":
            return _dictate(str(params.get("text") or ""),
                            str(params.get("mode") or "append"),
                            str(params.get("confirm") or ""))
        if action == "suggest_next":
            return _suggest_next()
        return "Action bujhlam na."
    except Exception as exc:  # noqa: BLE001 — run() must never raise
        return f"Voice tools action-ta korte parlam na: {exc}"
