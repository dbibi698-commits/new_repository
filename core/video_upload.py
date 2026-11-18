"""core/video_upload.py — 📤 VIDEO UPLOAD via manual browser control
(Instagram / Facebook / YouTube).

The browser flow — NOT the Graph API. Mark drives the user's own logged-in
Chrome (no-extension driver: Playwright channel="chrome" first, CDP
fallback, pyautogui last resort — zero extension calls) and clicks like a
human, step by step: open the site -> Create -> Select from computer
(real file-input handling via Playwright set_input_files, no OS file
picker) -> caption/title -> Share/Post/Publish. After every step the flow
verifies the page actually advanced; a failed step names itself and the
page is left open for the user to finish by hand.

MANUAL MODE: Mark opens the user's own Chrome to the upload page and the
USER clicks in the real browser while Mark watches (the driver reads the
page state and narrates it). "tumi koro" hands control to Mark from the
current page; "ami korbo" hands it back to the user. Both directions work.

LOGIN + LIMITS (shown in the UI): login is required on each site (the
user's own account, already logged in on Chrome — Mark never sees or
stores the site password); each site has file size / video length limits
(shown in the upload box — the site's stated limits, which can change);
browser upload is slower than API upload but human-like; selectors can
break if a site redesigns (then Mark says so plainly and leaves the page
open). The Graph API flows (instagram_upload_video for business accounts,
facebook_upload_video) stay as alternatives — this browser flow is the
deliverable.

No Qt, no network except through the driver. Every public function
returns a plain value and never raises. The driver is injected
(driver_fn) so tests can use a fake.
"""
from __future__ import annotations

import os

try:
    from memory import config_manager as _cm
except Exception:  # pragma: no cover
    _cm = None  # type: ignore

from core.browser_automation import run_steps
from core.browser_driver import ensure_driver

_NS = "video_upload"

SITES = {
    "instagram": {
        "label": "Instagram",
        "upload_url": "https://www.instagram.com/",
        "limit": ("Reel: 90 min porjonto, 4 GB porjonto "
                  "(site-er niyom bodlate pare)"),
    },
    "facebook": {
        "label": "Facebook",
        "upload_url": "https://www.facebook.com/",
        "limit": ("Video: 240 min porjonto, 10 GB porjonto "
                  "(site-er niyom bodlate pare)"),
    },
    "youtube": {
        "label": "YouTube",
        "upload_url": "https://studio.youtube.com/",
        "limit": ("Video: 12 ghonta / 256 GB (verified account); "
                  "unverified: 15 min (site-er niyom bodlate pare)"),
    },
}

# What "logged in" looks like on each site (pure text markers).
_LOGIN_OK = {
    "instagram": ("create", "home", "reels"),
    "facebook": ("what's on your mind", "home", "watch"),
    "youtube": ("create", "dashboard", "channel content"),
}
_LOGIN_WALL = {
    "instagram": ("log in", "sign up"),
    "facebook": ("log in", "create new account"),
    "youtube": ("sign in",),
}


def _read_ns() -> dict:
    try:
        if _cm is None:
            return {}
        return dict(_cm.get_plugin_config(_NS) or {})
    except Exception:
        return {}


def _save_ns(values: dict) -> None:
    try:
        if _cm is not None:
            _cm.save_plugin_config(_NS, values)
    except Exception:
        pass


def get_mode() -> str:
    """'auto' or 'manual' (default 'auto')."""
    return str(_read_ns().get("mode") or "auto").lower() or "auto"


def set_mode(mode: str) -> None:
    _save_ns({"mode": "manual" if str(mode).lower() == "manual" else "auto"})


def site_limit(site: str) -> str:
    """The site's stated file size / length limit for the upload box."""
    info = SITES.get((site or "").lower())
    return info["limit"] if info else ""


def login_needed(site: str, page_text: str) -> bool:
    """True when the page is a login wall for this site. Pure."""
    try:
        site = (site or "").lower()
        text = (page_text or "").lower()
        ok_markers = _LOGIN_OK.get(site, ())
        if any(m in text for m in ok_markers):
            return False
        wall = _LOGIN_WALL.get(site, ())
        return any(m in text for m in wall)
    except Exception:
        return False


def file_ok(file_path: str) -> str:
    """'' when the video file exists and looks like a video, else the
    plain-words problem."""
    try:
        path = (file_path or "").strip()
        if not path:
            return "Video-r file path dao."
        if not os.path.isfile(path):
            return f"Video file-ta pelam na: {path}"
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"):
            return (f"Ei file-ta video mone hocche na ({ext or 'no extension'}) "
                    "— mp4/mov/avi/mkv/webm dao.")
        return ""
    except Exception as e:
        return f"File check korte parlam na: {e}"


# ── step lists (data — tests assert on these) ────────────────────────────────

def upload_steps(site: str, file_path: str, caption: str = "",
                 title: str = "", description: str = "") -> list[dict]:
    """The full auto flow for a site. Each step verifies the page
    advanced before the next one runs."""
    site = (site or "").lower()
    if site == "instagram":
        steps: list[dict] = [
            {"label": "Instagram khullam", "action": "navigate",
             "url": SITES["instagram"]["upload_url"],
             "verify": {"url_contains": "instagram.com"}},
            {"label": "Create chaplam", "action": "click",
             "selectors": ["text=Create", "a[aria-label='New post']",
                           "button:has-text('Create')"]},
            {"label": "Select from computer chaplam", "action": "click",
             "selectors": ["button:has-text('Select from computer')",
                           "text=Select from computer"]},
            {"label": "Video select korlam", "action": "set_file",
             "selector": "input[type='file']", "path": file_path},
            {"label": "Next chaplam (crop)", "action": "click",
             "selectors": ["button:has-text('Next')", "text=Next"]},
            {"label": "Next chaplam (edit)", "action": "click",
             "selectors": ["button:has-text('Next')", "text=Next"]},
        ]
        if (caption or "").strip():
            steps.append(
                {"label": "Caption likhlam", "action": "fill",
                 "selectors": ["textarea[aria-label='Write a caption...']",
                               "textarea"],
                 "text": caption})
        steps.append(
            {"label": "Share chaplam", "action": "click",
             "selectors": ["button:has-text('Share')", "text=Share"],
             "verify": {"text_contains": "shared"}})
        return steps
    if site == "facebook":
        steps = [
            {"label": "Facebook khullam", "action": "navigate",
             "url": SITES["facebook"]["upload_url"],
             "verify": {"url_contains": "facebook.com"}},
            {"label": "Post composer khullam", "action": "click",
             "selectors": ["text=What's on your mind?",
                           "span:has-text(\"What's on your mind?\")"]},
            {"label": "Add photos/videos chaplam", "action": "click",
             "selectors": ["text=Add photos/videos", "text=Photo/video"]},
            {"label": "Video select korlam", "action": "set_file",
             "selector": "input[type='file']", "path": file_path},
        ]
        if (caption or "").strip():
            steps.append(
                {"label": "Caption likhlam", "action": "type",
                 "selectors": ["div[contenteditable='true']"],
                 "text": caption})
        steps.append(
            {"label": "Post chaplam", "action": "click",
             "selectors": ["button:has-text('Post')",
                           "div[aria-label='Post']"],
             "verify": {"text_contains": "posted"}})
        return steps
    # youtube
    steps = [
        {"label": "YouTube Studio khullam", "action": "navigate",
         "url": SITES["youtube"]["upload_url"],
         "verify": {"url_contains": "studio.youtube.com"}},
        {"label": "CREATE chaplam", "action": "click",
         "selectors": ["text=CREATE", "button:has-text('CREATE')"]},
        {"label": "Upload videos chaplam", "action": "click",
         "selectors": ["text=Upload videos"]},
        {"label": "Video select korlam", "action": "set_file",
         "selector": "input[type='file']", "path": file_path},
        {"label": "Details page asha", "action": "wait_for",
         "selectors": ["#textbox", "text=Details"],
         "timeout_ms": 30000},
    ]
    if (title or "").strip():
        steps.append(
            {"label": "Title likhlam", "action": "type",
             "selectors": ["#textbox"], "text": title})
    if (description or "").strip():
        steps.append(
            {"label": "Description likhlam", "action": "type",
             "selectors": ["#description"], "text": description})
    steps += [
        {"label": "Next chaplam (checks)", "action": "click",
         "selectors": ["button:has-text('Next')", "#next-button"]},
        {"label": "Next chaplam (visibility)", "action": "click",
         "selectors": ["button:has-text('Next')", "#next-button"]},
        {"label": "Publish chaplam", "action": "click",
         "selectors": ["button:has-text('Publish')", "#done-button",
                       "text=Publish"],
         "verify": {"text_contains": "published"}},
    ]
    return steps


# ── the flows ────────────────────────────────────────────────────────────────

def _get_driver(driver_fn=None):
    try:
        fn = driver_fn or ensure_driver
        return fn()
    except Exception as e:
        return None, "", f"Browser driver pelam na: {e}"


def _read_page(driver) -> str:
    try:
        ok, text = driver.read_text()
        return text if ok else ""
    except Exception:
        return ""


def upload_video(site: str, file_path: str, caption: str = "",
                 title: str = "", description: str = "",
                 driver_fn=None, log_fn=None) -> tuple[bool, str]:
    """Auto upload: run the site's steps one by one, narrating each live.
    Returns (ok, message). Never raises."""
    def log(msg: str) -> None:
        if callable(log_fn):
            try:
                log_fn(msg)
            except Exception:
                pass

    site = (site or "").lower()
    if site not in SITES:
        return False, "Site-ta bolo — Instagram, Facebook, na YouTube?"
    problem = file_ok(file_path)
    if problem:
        return False, problem
    driver, _backend, msg = _get_driver(driver_fn)
    if driver is None:
        return False, f"Browser driver ready noy — {msg}"
    label = SITES[site]["label"]
    steps = upload_steps(site, file_path, caption, title, description)
    try:
        for i, step in enumerate(steps, start=1):
            ok, m = run_steps([step], driver)
            if not ok:
                return False, (f"⛔ {label} upload-e atkalam — {m} "
                               "Page-ta khula rekhechi: tumi nije shesh "
                               "korte paro, ba 'ami korbo' bolo.")
            log(f"✅ {label}: {step.get('label')} ({i}/{len(steps)})")
            # Login wall check right after the first navigate.
            if i == 1:
                if login_needed(site, _read_page(driver)):
                    return False, (f"⛔ {label}-e login lagbe — Chrome-e "
                                   "tomar account-e login koro, tarpor abar "
                                   "bolo. Ami tomar password dekhi na, rakhi na.")
        _save_ns({"last_upload": {"site": site,
                                  "file": os.path.basename(file_path),
                                  "caption": (caption or "")[:120]}})
        return True, (f"✅ {label}-e video upload holo! "
                      f"({os.path.basename(file_path)})")
    except Exception as e:
        return False, f"{label} upload-e error: {e}"


def open_upload_page(site: str, driver_fn=None) -> tuple[bool, str]:
    """MANUAL MODE: open the upload page and hand the mouse to the user.
    Mark watches from here (see watch_state). Returns (ok, message)."""
    site = (site or "").lower()
    if site not in SITES:
        return False, "Site-ta bolo — Instagram, Facebook, na YouTube?"
    driver, _backend, msg = _get_driver(driver_fn)
    if driver is None:
        return False, f"Browser driver ready noy — {msg}"
    try:
        ok, m = driver.navigate(SITES[site]["upload_url"])
        if not ok:
            return False, f"Page khulte parlam na: {m}"
        text = _read_page(driver)
        if login_needed(site, text):
            return False, (f"⛔ {SITES[site]['label']}-e login lagbe — "
                           "Chrome-e tomar account-e login koro, tarpor "
                           "abar bolo.")
        set_mode("manual")
        _save_ns({"manual_site": site})
        return True, (f"🌐 {SITES[site]['label']} khullam — tumi nije "
                      "click koro, ami dekhchi ar bolbo ki hocche. "
                      "'Tumi koro' bolle ami ekhan theke chalabo.")
    except Exception as e:
        return False, f"Page khulte giye error: {e}"


def watch_state(driver, last: dict | None = None) -> tuple[str, dict]:
    """Read the current page and narrate it when it changed since `last`.
    Returns (narration_or_'', new_state). Pure-ish (driver read only)."""
    try:
        url = driver.current_url() or ""
        ok, text = driver.read_text()
        text = text if ok else ""
        state = {"url": url, "head": (text or "")[:120].strip()}
        if last is not None and last.get("url") == url \
                and last.get("head") == state["head"]:
            return "", state
        head = state["head"].replace("\n", " ")[:100]
        return (f"👀 Ekhon tumi ei page-e: {url or '(khali)'}"
                + (f" — {head}" if head else "")), state
    except Exception:
        return "", dict(last or {})


def take_over(site: str, file_path: str, caption: str = "",
              title: str = "", description: str = "",
              driver_fn=None, log_fn=None) -> tuple[bool, str]:
    """'Tumi koro' — Mark takes the mouse from the current page and runs
    the upload from wherever the user left off. If the file-chooser
    dialog is already open (or the user is still on the upload page),
    the flow starts at the file step; otherwise it runs the full flow."""
    site = (site or "").lower()
    if site not in SITES:
        return False, "Site-ta bolo — Instagram, Facebook, na YouTube?"
    problem = file_ok(file_path)
    if problem:
        return False, problem
    driver, _backend, msg = _get_driver(driver_fn)
    if driver is None:
        return False, f"Browser driver ready noy — {msg}"
    try:
        text = _read_page(driver)
        steps = upload_steps(site, file_path, caption, title, description)
        # If the user already opened the create dialog, skip straight to
        # the file step (the "Select from computer" text is on screen).
        triggers = {"instagram": "select from computer",
                    "facebook": "add photos/videos",
                    "youtube": "upload videos"}
        start = 0
        if triggers.get(site, "") in text.lower():
            for i, s in enumerate(steps):
                if s.get("action") == "set_file":
                    start = i
                    break
        set_mode("auto")
        for i, step in enumerate(steps[start:], start=start + 1):
            ok, m = run_steps([step], driver)
            if not ok:
                return False, (f"⛔ {SITES[site]['label']} upload-e "
                               f"atkalam — {m} Page-ta khula rekhechi.")
            if callable(log_fn):
                try:
                    log_fn(f"✅ {SITES[site]['label']}: {step.get('label')}")
                except Exception:
                    pass
        return True, (f"✅ {SITES[site]['label']}-e video upload holo! "
                      f"({os.path.basename(file_path)})")
    except Exception as e:
        return False, f"Take-over-e error: {e}"


def hand_back() -> str:
    """'Ami korbo' — hand the mouse back to the user (manual mode)."""
    set_mode("manual")
    return ("🙋 Thik ache — tumi koro, ami dekhchi. Kono step-e atkale "
            "'tumi koro' bolo, ami sekhan theke chalabo.")
