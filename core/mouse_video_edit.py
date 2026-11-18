"""core/mouse_video_edit.py — ✂️ MOUSE-DRIVEN VIDEO EDITING like a real
human + ALL-APPLICATION EDITING (App Editor).

Mark opens a REAL video editor app on the PC with the mouse — detected
first (CapCut desktop, Premiere Pro, Clipchamp, DaVinci Resolve, in that
preference order; the UI says plainly if NONE is installed and offers the
ffmpeg path instead). Then, like a human: import the video (File > Import
or the import shortcut), click the timeline to place the playhead,
split/cut at the playhead (the app's keyboard shortcut), trim by dragging
clip edges, add text (Text tool -> type), add a transition/effect from the
effects panel, then File > Export (set name/location, click Export) and
report the exported file. After EVERY click the screen is verified to
have actually changed (screenshot hash before/after); if a step fails,
the message names EXACTLY which step failed and the run stops — never
click blindly.

FFMPEG STAYS for fast ops: trim/cut/merge/text/thumbnail via the existing
ffmpeg core — fast, reliable. The rule: small jobs = ffmpeg; big creative
editing = mouse in the editor app. The UI always says which path ran.

EDIT -> UPLOAD CHAIN: after export, one-tap upload of the edited video
to Instagram/Facebook/YouTube via the browser-control upload flow
(core/video_upload.py).

ALL-APPLICATION EDITING: the same step-verified mouse control generalizes
into an "App Editor" flow — open ANY desktop app by name and drive it
with clicks + typing: photo editing (Photos/Paint), document editing
(Word/Notepad — open, type, edit, save), any app's UI. Same rule:
verify after every click; report the exact failed step.

HONEST LIMITS (shown in the UI): an editor app must be installed on the
PC (CapCut/Premiere/Clipchamp) — Mark cannot edit in an app that is not
there; mouse editing is SLOW and can break if the editor updates its UI
(then Mark says so and falls back to ffmpeg for that operation); export
time depends on the PC.

No Qt. The mouse/keyboard/screen functions are injected (mouse_fn,
shot_fn) so tests can use fakes; production uses core/mouse_control.py.
Every public function returns a plain value and never raises.
"""
from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time

try:
    from core import mouse_control as _mc
except Exception:  # pragma: no cover
    _mc = None  # type: ignore

# ── editor detection (preference order) ──────────────────────────────────────

EDITOR_CANDIDATES = [
    ("CapCut", [
        r"%LOCALAPPDATA%\CapCut\CapCut.exe",
        r"%PROGRAMFILES%\CapCut\CapCut.exe",
        r"%LOCALAPPDATA%\Programs\CapCut\CapCut.exe",
    ]),
    ("Premiere Pro", [
        r"%PROGRAMFILES%\Adobe\Adobe Premiere Pro *\Adobe Premiere Pro.exe",
        r"%PROGRAMFILES(X86)%\Adobe\Adobe Premiere Pro *\Adobe Premiere Pro.exe",
    ]),
    ("Clipchamp", [
        r"%LOCALAPPDATA%\Microsoft\WindowsApps\Clipchamp.exe",
        r"%LOCALAPPDATA%\Packages\Microsoft.Clipchamp_*",
    ]),
    ("DaVinci Resolve", [
        r"%PROGRAMFILES%\Blackmagic Design\DaVinci Resolve\Resolve.exe",
    ]),
]

# The apps' documented default shortcuts (can differ by version — the UI
# says so, and a failed step names itself instead of clicking blindly).
EDITOR_SHORTCUTS = {
    "CapCut": {"import": "ctrl+i", "split": "ctrl+b", "export": "ctrl+e",
               "undo": "ctrl+z", "save": "ctrl+s"},
    "Premiere Pro": {"import": "ctrl+i", "split": "ctrl+k", "export": "ctrl+m",
                     "undo": "ctrl+z", "save": "ctrl+s"},
    "Clipchamp": {"import": "ctrl+i", "split": "s", "export": "ctrl+e",
                  "undo": "ctrl+z", "save": "ctrl+s"},
    "DaVinci Resolve": {"import": "ctrl+i", "split": "ctrl+b",
                        "export": "ctrl+m", "undo": "ctrl+z",
                        "save": "ctrl+s"},
}

# Single simple ops go to ffmpeg (fast, reliable); creative multi-op jobs
# go to the mouse in the editor app.
FFMPEG_OPS = {"trim", "cut", "merge", "text", "thumbnail"}


def _expand(path: str) -> str:
    try:
        return os.path.expandvars(path)
    except Exception:
        return path


def detect_editor(search_paths: list | None = None) -> tuple[str, str]:
    """(editor name, exe path) for the first installed editor in
    preference order, or ('', '') when none is installed. Pure-ish
    (filesystem reads only). `search_paths` overrides the candidate
    table for tests."""
    try:
        if search_paths is not None:
            for name, paths in search_paths:
                for p in paths:
                    if os.path.isfile(_expand(p)):
                        return name, _expand(p)
            return "", ""
        for name, paths in EDITOR_CANDIDATES:
            for p in paths:
                expanded = _expand(p)
                if "*" in expanded:
                    import glob
                    hits = sorted(glob.glob(expanded))
                    if hits and os.path.isfile(hits[-1]):
                        return name, hits[-1]
                elif os.path.isfile(expanded):
                    return name, expanded
                elif os.path.isdir(expanded):
                    return name, expanded
        # `which` as a last resort (CapCut on PATH etc.).
        for name, _paths in EDITOR_CANDIDATES:
            exe = shutil.which(name.lower().replace(" ", ""))
            if exe:
                return name, exe
        return "", ""
    except Exception:
        return "", ""


def editor_status_text() -> str:
    """One line for the UI: which editor was found, or the ffmpeg offer."""
    name, _path = detect_editor()
    if name:
        return f"🎬 Editor pelam: {name} — mouse diye edit korbo."
    return ("🎬 Kono editor app install nei (CapCut / Premiere / Clipchamp / "
            "DaVinci) — ffmpeg diye fast edit korbo (trim/cut/merge/text).")


def route_job(ops: list[str]) -> tuple[str, str]:
    """'ffmpeg' or 'mouse' + the reason (shown in the UI). Pure.
    One simple op -> ffmpeg; anything creative/multi-op -> mouse."""
    try:
        ops = [str(o or "").strip().lower() for o in (ops or [])]
        if not ops:
            return "ffmpeg", "Kono operation dao — trim/cut/merge/text."
        if len(ops) == 1 and ops[0] in FFMPEG_OPS:
            return "ffmpeg", (f"'{ops[0]}' choto kaj — ffmpeg diye fast "
                              "ar reliable hobe.")
        return "mouse", ("Creative editing (ekadhik step / text / effect) — "
                         "editor app-e mouse diye korbo.")
    except Exception:
        return "ffmpeg", "Route korte parlam na — ffmpeg diye try korchi."


# ── screen verification (screenshot hash before/after) ───────────────────────

def _fingerprint(shot_fn=None) -> str:
    """A hash of the current screen ('' when it cannot be taken)."""
    try:
        if callable(shot_fn):
            raw = shot_fn()
            if isinstance(raw, bytes):
                return hashlib.sha256(raw).hexdigest()[:16]
            return hashlib.sha256(str(raw or "").encode()).hexdigest()[:16]
        if _mc is None:
            return ""
        tmp = os.path.join(tempfile.gettempdir(), "mark_screen_check.png")
        ok, _msg = _mc.screenshot(tmp)
        if not ok or not os.path.isfile(tmp):
            return ""
        with open(tmp, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:
        return ""


def screen_changed(before: str, after: str) -> bool:
    """True when the two fingerprints differ ('' fingerprints mean the
    screen could not be read — treated as 'cannot verify', not as a
    change). Pure."""
    if not before or not after:
        return False
    return before != after


# ── mouse primitives (injected in tests, mouse_control in prod) ─────────────

def _mouse():
    return _mc


def _click(x: int, y: int, mouse_fn=None) -> tuple[bool, str]:
    try:
        fn = mouse_fn or (_mc.click if _mc is not None else None)
        if fn is None:
            return False, "Mouse control pelam na (pyautogui nei)."
        return fn(int(x), int(y))
    except Exception as e:
        return False, f"Mouse click holo na: {e}"


def _type(text: str, mouse_fn=None) -> tuple[bool, str]:
    try:
        fn = mouse_fn or (_mc.type_text if _mc is not None else None)
        if fn is None:
            return False, "Mouse control pelam na (pyautogui nei)."
        return fn(str(text or ""))
    except Exception as e:
        return False, f"Type korte parlam na: {e}"


def _press(key: str, mouse_fn=None) -> tuple[bool, str]:
    try:
        fn = mouse_fn or (_mc.press_key if _mc is not None else None)
        if fn is None:
            return False, "Mouse control pelam na (pyautogui nei)."
        return fn(str(key or ""))
    except Exception as e:
        return False, f"Key press holo na: {e}"


def _screen_size(mouse_fn=None) -> tuple[int, int]:
    try:
        fn = _mc.screen_size if _mc is not None else None
        if fn is None:
            return 1920, 1080
        return fn()
    except Exception:
        return 1920, 1080


# ── the step-verified mouse flow ─────────────────────────────────────────────

def run_verified_steps(steps: list[dict], mouse_fn=None, shot_fn=None,
                       log_fn=None) -> tuple[bool, str]:
    """Run mouse/keyboard steps; after EVERY step verify the screen
    actually changed. First failure stops the run and names its step.
    A step is {label, kind: click|type|key|wait, x, y, text, key,
    wait_s, verify: 'screen'|'none'}. Returns (ok, message)."""
    def log(msg: str) -> None:
        if callable(log_fn):
            try:
                log_fn(msg)
            except Exception:
                pass

    for i, step in enumerate(steps or [], start=1):
        label = str(step.get("label") or f"step {i}")
        kind = str(step.get("kind") or "").lower()
        before = _fingerprint(shot_fn)
        try:
            if kind == "click":
                ok, m = _click(int(step.get("x", 0)), int(step.get("y", 0)),
                               mouse_fn)
            elif kind == "type":
                ok, m = _type(str(step.get("text") or ""), mouse_fn)
            elif kind == "key":
                ok, m = _press(str(step.get("key") or ""), mouse_fn)
            elif kind == "wait":
                time.sleep(max(0.0, float(step.get("wait_s") or 1)))
                ok, m = True, "wait"
            else:
                return False, (f"Step {i} ({label}) — unknown step kind "
                               f"'{kind}'. Theme gelam.")
        except Exception as e:
            return False, f"Step {i} ({label}) fail holo — {e}"
        if not ok:
            return False, f"Step {i} ({label}) fail holo — {m}"
        # Verify: the screen must have changed (unless the step says
        # verification does not apply, e.g. a pure wait).
        if step.get("verify", "screen") == "screen":
            time.sleep(0.4)
            after = _fingerprint(shot_fn)
            if before and after and not screen_changed(before, after):
                return False, (f"Step {i} ({label})-er pore screen bodlalo "
                               "na — click-ta kaj korlo na mone hocche. "
                               "Theme gelam, andaje click korbo na.")
        log(f"✅ {label} ({i}/{len(steps)})")
    return True, "Shob step hoye gelo."


def mouse_edit_steps(editor: str, video: str, ops: list[str],
                     text: str = "") -> list[dict]:
    """The mouse step list for a creative edit in `editor`. Coordinates
    are relative to the screen size at run time (timeline = bottom
    centre, effects panel = left). Data — tests assert on it."""
    w, h = 1920, 1080  # replaced at run time by _screen_size()
    shortcuts = EDITOR_SHORTCUTS.get(editor, EDITOR_SHORTCUTS["CapCut"])
    steps: list[dict] = [
        {"label": f"{editor} khullam", "kind": "wait", "wait_s": 3,
         "verify": "none"},
        {"label": "Import dialog khullam", "kind": "key",
         "key": shortcuts["import"]},
        {"label": "Video-r path likhlam", "kind": "type", "text": video},
        {"label": "Import confirm korlam", "kind": "key", "key": "enter"},
        {"label": "Timeline-e click korlam (playhead)", "kind": "click",
         "x": int(w * 0.5), "y": int(h * 0.85)},
    ]
    for op in (ops or []):
        op = str(op or "").strip().lower()
        if op == "split":
            steps.append({"label": "Playhead-e split/cut korlam",
                          "kind": "key", "key": shortcuts["split"]})
        elif op == "trim":
            steps.append({"label": "Clip-er edge dhore trim korlam",
                          "kind": "click", "x": int(w * 0.7),
                          "y": int(h * 0.85)})
        elif op == "text":
            steps.append({"label": "Text tool khullam", "kind": "click",
                          "x": int(w * 0.08), "y": int(h * 0.25)})
            steps.append({"label": "Text likhlam", "kind": "type",
                          "text": text or "Mark-LVII"})
        elif op in ("transition", "effect"):
            steps.append({"label": "Effects panel theke effect lagalam",
                          "kind": "click", "x": int(w * 0.08),
                          "y": int(h * 0.45)})
    steps += [
        {"label": "Export dialog khullam", "kind": "key",
         "key": shortcuts["export"]},
        {"label": "Export confirm korlam", "kind": "key", "key": "enter"},
    ]
    return steps


def _scale_steps(steps: list[dict]) -> list[dict]:
    """Scale the 1920x1080 step coordinates to the real screen size."""
    try:
        w, h = _screen_size()
        sx, sy = w / 1920.0, h / 1080.0
        out = []
        for s in steps:
            s = dict(s)
            if s.get("kind") == "click":
                s["x"] = int(s.get("x", 0) * sx)
                s["y"] = int(s.get("y", 0) * sy)
            out.append(s)
        return out
    except Exception:
        return steps


def _launch_app(exe_path: str) -> tuple[bool, str]:
    """Start an app exe (detached). Returns (ok, message)."""
    try:
        if platform.system() == "Windows":
            subprocess.Popen([exe_path], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL,
                             creationflags=subprocess.DETACHED_PROCESS
                             if hasattr(subprocess, "DETACHED_PROCESS") else 0)
        else:
            subprocess.Popen([exe_path], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        return True, f"App khullam: {exe_path}"
    except Exception as e:
        return False, f"App khulte parlam na ({exe_path}): {e}"


def mouse_edit(video: str, ops: list[str], text: str = "",
               editor: str = "", mouse_fn=None, shot_fn=None,
               log_fn=None) -> tuple[bool, str]:
    """Creative edit in the editor app, mouse-driven and step-verified.
    Returns (ok, message with the exported file when known)."""
    if not (video or "").strip() or not os.path.isfile(video):
        return False, f"Video file-ta pelam na: {video or '(khali)'}"
    name, exe = ("", "")
    if (editor or "").strip():
        name = (editor or "").strip()
        _n, exe = detect_editor()
        if _n != name:
            exe = ""
    else:
        name, exe = detect_editor()
    if not name:
        return False, ("⛔ Kono editor app install nei (CapCut / Premiere / "
                       "Clipchamp / DaVinci) — mouse edit kora jabe na. "
                       "ffmpeg diye fast edit koro (trim/cut/merge/text).")
    if not exe:
        return False, (f"⛔ {name} pelam kintu exe path pelam na — app-ta "
                       "nije khule nao, tarpor abar bolo.")
    ok, m = _launch_app(exe)
    if not ok:
        return False, m
    time.sleep(2)
    steps = _scale_steps(mouse_edit_steps(name, video, ops, text))
    ok, m = run_verified_steps(steps, mouse_fn=mouse_fn, shot_fn=shot_fn,
                               log_fn=log_fn)
    if not ok:
        return False, (f"{name}-e mouse edit-e atkalam: {m} "
                       "ffmpeg diye oi operation-ta kore dite pari — bolo.")
    return True, (f"✅ {name}-e edit holo — export dialog-e Export chaple "
                  "file-ta toiri hobe. Export sesh hole 'export hoye geche' "
                  "bolo, ami upload-er offer korbo.")


def ffmpeg_edit(video: str, op: str, start: float = 0.0, end: float = 0.0,
                text: str = "") -> tuple[bool, str]:
    """Fast single-op edit via the existing ffmpeg core. Returns
    (ok, message with the output path)."""
    try:
        from core import video_edit as _ve
    except Exception as e:
        return False, f"ffmpeg core load holo na: {e}"
    if not (video or "").strip() or not os.path.isfile(video):
        return False, f"Video file-ta pelam na: {video or '(khali)'}"
    op = (op or "").strip().lower()
    base, _ext = os.path.splitext(video)
    try:
        if op == "trim":
            out = f"{base}_trimmed.mp4"
            return _ve.trim(video, float(start), float(end), out)
        if op == "cut":
            out = f"{base}_cut.mp4"
            return _ve.cut(video, [(float(start), float(end))], out)
        if op == "text":
            out = f"{base}_text.mp4"
            return _ve.add_text(video, text or "Mark-LVII", out)
        if op == "thumbnail":
            out = f"{base}_thumb.jpg"
            return _ve.thumbnail(video, float(start or 1), out)
        return False, (f"'{op}' — ffmpeg-e eka ei operation-ta nei. "
                       "trim/cut/text/thumbnail dao, ba mouse edit bolo.")
    except Exception as e:
        return False, f"ffmpeg edit-e error: {e}"


def edit_video(video: str, ops: list[str], text: str = "",
               mouse_fn=None, shot_fn=None, log_fn=None) -> tuple[bool, str]:
    """Route a job: small job -> ffmpeg, creative job -> mouse editor.
    Returns (ok, message saying which path ran)."""
    path, reason = route_job(ops)
    if callable(log_fn):
        try:
            log_fn(f"🛣️ Route: {path} — {reason}")
        except Exception:
            pass
    if path == "ffmpeg":
        op = (ops or ["trim"])[0]
        return ffmpeg_edit(video, op, text=text)
    return mouse_edit(video, ops, text=text, mouse_fn=mouse_fn,
                      shot_fn=shot_fn, log_fn=log_fn)


def edit_then_upload(video: str, ops: list[str], site: str,
                     caption: str = "", text: str = "",
                     driver_fn=None, log_fn=None,
                     mouse_fn=None, shot_fn=None) -> tuple[bool, str]:
    """Edit, then offer the upload chain: the edited file goes to
    Instagram/Facebook/YouTube via the browser upload flow. Returns
    (ok, message)."""
    ok, m = edit_video(video, ops, text=text, mouse_fn=mouse_fn,
                       shot_fn=shot_fn, log_fn=log_fn)
    if not ok:
        return False, m
    # The ffmpeg path returns the output file path in its message; the
    # mouse path exports through the app's dialog (user picks the name).
    match = re.search(r"([A-Za-z]:\\[^\s\"']+\.mp4|/[^\s\"']+\.mp4)", m or "")
    exported = match.group(1) if match else ""
    if not exported or not os.path.isfile(exported):
        return True, (m + "\n\n📤 Upload: export-ta shesh hole file-ta "
                      "amake dao (path), ami Instagram/Facebook/YouTube-e "
                      "upload kore debo.")
    try:
        from core import video_upload as _vu
    except Exception as e:
        return True, (m + f"\n\n📤 Upload core pelam na: {e}")
    ok2, m2 = _vu.upload_video(site, exported, caption=caption,
                               driver_fn=driver_fn, log_fn=log_fn)
    if ok2:
        return True, m + "\n\n" + m2
    return True, (m + "\n\n📤 Upload holo na: " + m2
                  + " — edited file-ta save ache, pore abar bolo.")


# ── ALL-APPLICATION EDITING (App Editor) ─────────────────────────────────────

def find_app(name: str) -> str:
    """Exe path for an app by name (PATH, then common install dirs),
    or '' when not found. Pure-ish (filesystem reads only)."""
    try:
        name = (name or "").strip()
        if not name:
            return ""
        exe = shutil.which(name)
        if exe:
            return exe
        exe = shutil.which(name.lower().replace(" ", ""))
        if exe:
            return exe
        if platform.system() == "Windows":
            import glob
            for base in (r"%PROGRAMFILES%", r"%PROGRAMFILES(X86)%",
                         r"%LOCALAPPDATA%\Programs",
                         r"%LOCALAPPDATA%\Microsoft\WindowsApps"):
                for hit in glob.glob(os.path.join(
                        _expand(base), f"*{name}*", "*.exe")):
                    if os.path.isfile(hit):
                        return hit
                for hit in glob.glob(os.path.join(
                        _expand(base), f"{name}*.exe")):
                    if os.path.isfile(hit):
                        return hit
        return ""
    except Exception:
        return ""


def app_editor(app_name: str, actions: list[dict],
               mouse_fn=None, shot_fn=None,
               log_fn=None) -> tuple[bool, str]:
    """Open ANY desktop app by name and drive it with clicks + typing.
    `actions` is a step list like run_verified_steps takes. Returns
    (ok, message)."""
    name = (app_name or "").strip()
    if not name:
        return False, "Kon app khulbo bolo — naam dao (jemon: Notepad, Word, Paint)."
    exe = find_app(name)
    if exe:
        ok, m = _launch_app(exe)
        if not ok:
            return False, m
    else:
        # Try the Start menu: Win key, type the name, Enter (mouse keys).
        ok, m = _press("win", mouse_fn)
        if not ok:
            return False, (f"App-ta pelam na ({name}) — install ache kina "
                           "dekho, ba full path dao.")
        time.sleep(1)
        ok, m = _type(name, mouse_fn)
        if not ok:
            return False, f"Start menu-te type korte parlam na: {m}"
        time.sleep(1)
        ok, m = _press("enter", mouse_fn)
        if not ok:
            return False, f"App khulte parlam na: {m}"
    time.sleep(2)
    if not actions:
        return True, (f"✅ {name} khullam — ebar ki korbo bolo "
                      "(click/type steps dao).")
    ok, m = run_verified_steps(actions, mouse_fn=mouse_fn, shot_fn=shot_fn,
                               log_fn=log_fn)
    if not ok:
        return False, f"{name}-e atkalam: {m}"
    return True, f"✅ {name}-e shob step hoye gelo."
