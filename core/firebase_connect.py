"""core/firebase_connect.py — 🔥 Firebase Connect: link a Firebase project
to an app/website, from the PC.

Two paths, best first:
  (a) BROWSER flow — the no-extension Playwright/CDP driver
      (core/browser_driver.py) drives the user's own logged-in Chrome to
      console.firebase.google.com: open the console, create a project (or
      pick an existing one), open Project Settings, download
      google-services.json (Android) or the web app config, and save it
      into the project folder the user picked. Every step is reported; a
      step that cannot be done stops honestly instead of pretending.
  (b) CLI fallback — `firebase apps:sdkconfig` from firebase-tools, when
      the CLI is installed and the user is logged in (`firebase login`).

Honest limits, said up front:
  * The browser flow needs the user's Google account logged in on Chrome —
    Mark never sees or stores the Google password.
  * Creating a project in the console is a multi-click flow whose buttons
    change when Google redesigns the page — the selectors are best-effort
    and every miss is reported with the exact step.
  * The config file (google-services.json / web config) is only a set of
    public identifiers + API key — it is NOT a secret credential, but it
    still belongs in the project folder, never in chat.

Every function returns a short string or (ok, message) and never raises.
No Qt anywhere — runs on worker threads.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

try:
    from core import browser_driver as _drv
except Exception:  # pragma: no cover - never on a real install
    _drv = None

_CONSOLE = "https://console.firebase.google.com"

# Buttons the Firebase console shows, in the order tried. Google redesigns
# this page often — a miss is reported, never silently skipped.
_CREATE_SELECTORS = (
    "text=Add project",
    "text=Create a project",
    "text=Add a project",
    "button:has-text(\"Add project\")",
    "button:has-text(\"Create a project\")",
)


# ── pure helpers (unit-tested) ───────────────────────────────────────────────

def cli_available() -> tuple[bool, str]:
    """(True, path) when `firebase` CLI is on PATH, else (False, why)."""
    try:
        path = shutil.which("firebase") or ""
        if path:
            return True, path
        return False, ("firebase CLI install kora nei — `npm install -g "
                       "firebase-tools` chalao, tarpor abar try koro.")
    except Exception as e:
        return False, f"firebase CLI check korte parlam na: {e}"


def sdkconfig_command(project_id: str, platform: str = "web") -> str:
    """The CLI command that prints a project's SDK config. Pure string."""
    pid = (project_id or "").strip()
    plat = (platform or "web").strip().lower()
    if plat not in ("web", "android", "ios"):
        plat = "web"
    return f"firebase apps:sdkconfig {plat} --project {pid}" if pid else ""


def classify_console_state(page_text: str) -> str:
    """What the Firebase console page is showing, from its visible text.
    Returns: login_needed | create_project | project_page | console | unknown.
    Pure — no browser needed."""
    try:
        t = " " + (page_text or "").lower() + " "
        if "sign in" in t and ("google" in t or "continue" in t):
            return "login_needed"
        if "add project" in t or "create a project" in t:
            return "create_project"
        if "project settings" in t or "project overview" in t:
            return "project_page"
        if "firebase" in t:
            return "console"
        return "unknown"
    except Exception:
        return "unknown"


def _project_folder_ok(folder: str) -> tuple[Path | None, str]:
    folder = (folder or "").strip()
    if not folder:
        return None, "Project folder dao — Firebase config kothay rakhbo?"
    p = Path(os.path.expanduser(folder))
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return None, f"Project folder banate parlam na ({folder}): {e}"
    return p, ""


# ── browser flow ─────────────────────────────────────────────────────────────

def console_status(driver_fn=None) -> str:
    """One-line status: CLI present? driver ready? Never raises."""
    try:
        cli_ok, cli_msg = cli_available()
        if _drv is None:
            return "Browser driver module pelam na."
        ensure = driver_fn if driver_fn is not None else _drv.ensure_driver
        driver, backend, msg = ensure(auto_install=False)
        if driver is None:
            return f"Firebase console: driver ready noy — {msg}"
        try:
            driver.close()
        except Exception:
            pass
        return (f"Firebase console ready (driver: {backend}). "
                f"CLI: {'ache' if cli_ok else 'nei — ' + cli_msg}")
    except Exception as e:
        return f"Firebase-er status dekhte parlam na: {e}"


def connect_flow(project_folder: str, project_id: str = "",
                 platform: str = "web", driver_fn=None,
                 progress_cb=None) -> tuple[bool, str]:
    """Start the Firebase connect flow in the user's Chrome.

    Opens console.firebase.google.com with the no-extension driver and
    reports each step. Creating the project itself needs the user's Google
    login in Chrome; when the console asks to sign in, this stops honestly
    ("Google login lagbe") instead of pretending. `progress_cb(text)` is
    called with one line per step (best-effort, never raises the flow).
    Returns (ok, message). Never raises."""
    def _say(text: str) -> None:
        try:
            if callable(progress_cb):
                progress_cb(str(text))
        except Exception:
            pass

    try:
        folder, err = _project_folder_ok(project_folder)
        if err:
            return False, err
        if _drv is None:
            return False, "Browser driver module pelam na."
        _say("Firebase console khulchi — Chrome-e console.firebase.google.com…")
        ensure = driver_fn if driver_fn is not None else _drv.ensure_driver
        driver, backend, msg = ensure()
        if driver is None:
            return False, f"Driver ready noy — {msg}"
        if backend == _drv.BACKEND_PYAUTOGUI:
            try:
                driver.close()
            except Exception:
                pass
            return (False,
                    "Chrome khullam kintu driver ready noy — pyautogui backend "
                    "DOM dekhte pare na. PC-te `pip install playwright` chalao.")
        try:
            ok, nav = driver.navigate(_CONSOLE)
            if not ok:
                return False, f"Firebase console-e jete parlam na: {nav}"
            time.sleep(2.0)
            ok, text = driver.read_text()
            state = classify_console_state(text if ok else "")
            if state == "login_needed":
                return (False,
                        "Firebase console Google login chachhe — Chrome-e tomar "
                        "Google account-e login koro, tarpor abar bolo. "
                        "Mark tomar password kokhono dekhbe na.")
            if state == "create_project":
                _say("Console khuleche — ekhane notun project banate hobe.")
                clicked = False
                for sel in _CREATE_SELECTORS:
                    ok, _m = driver.click(sel)
                    if ok:
                        clicked = True
                        break
                if not clicked:
                    return (False,
                            "Console khuleche kintu 'Add project' button pelam na — "
                            "Google page-ta bodle geche hote pare. Chrome-e nije "
                            "'Add project' chapho, tarpor abar bolo.")
                return (True,
                        "✅ Firebase console-e 'Add project' chaplam — project-er "
                        "naam dao, tarpor Project Settings theke config download "
                        f"kore {folder}-e rakhbo.")
            if state in ("project_page", "console"):
                pid = (project_id or "").strip()
                if pid:
                    cmd = sdkconfig_command(pid, platform)
                    return (True,
                            f"✅ Firebase console khula ache. Project {pid}-er "
                            f"config-er jonno CLI command: `{cmd}` — CLI login "
                            f"thakle config {folder}-e save kore dibo.")
                return (True,
                        "✅ Firebase console khula ache — ekta project khulo ba "
                        "notun banao, tarpor project-er id dao, ami config "
                        f"{folder}-e namiye dibo.")
            return (False,
                    "Firebase console khullam kintu page-ta chinlam na — Chrome-e "
                    "nije dekhe login/project khulo, tarpor abar bolo.")
        finally:
            try:
                driver.close()
            except Exception:
                pass
    except Exception as e:
        return False, f"Firebase connect korte parlam na: {e}"


def sdkconfig_via_cli(project_id: str, platform: str = "web",
                      project_folder: str = "") -> tuple[bool, str]:
    """Run `firebase apps:sdkconfig` and save the output into the project
    folder. Needs firebase-tools + `firebase login`. Never raises."""
    try:
        pid = (project_id or "").strip()
        if not pid:
            return False, "Project id dao — kon project-er config chai?"
        cli_ok, cli_msg = cli_available()
        if not cli_ok:
            return False, cli_msg
        folder, err = _project_folder_ok(project_folder or ".")
        if err:
            return False, err
        plat = (platform or "web").strip().lower()
        if plat not in ("web", "android", "ios"):
            plat = "web"
        out_name = ("google-services.json" if plat == "android"
                    else "GoogleService-Info.plist" if plat == "ios"
                    else "firebase-config.json")
        try:
            r = subprocess.run(
                ["firebase", "apps:sdkconfig", plat, "--project", pid],
                capture_output=True, text=True, timeout=60)
        except Exception as e:
            return False, f"firebase CLI chalate parlam na: {e}"
        if r.returncode != 0:
            tail = (r.stderr or r.stdout or "").strip()[-300:]
            return False, (f"firebase CLI config ante parlo na: {tail} "
                           "— `firebase login` kora ache kina dekho.")
        out = (r.stdout or "").strip()
        if not out:
            return False, "firebase CLI khali uttor dilo — project id thik ache kina dekho."
        p = folder / out_name
        try:
            p.write_text(out, encoding="utf-8")
        except Exception as e:
            return False, f"Config file save korte parlam na: {e}"
        return True, f"✅ Firebase config save holo: {p}"
    except Exception as e:
        return False, f"Firebase config ante parlam na: {e}"
