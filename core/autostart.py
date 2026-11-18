"""core/autostart.py — 🖥️ AUTOSTART + PC environment probe for Mark-LVII.

Windows autostart: Mark joins Windows startup through a shortcut in the
user's Startup folder (the standard Windows way — no registry, no
service, nothing hidden). A Settings toggle in Plugin Settings
("🖥️ SYSTEM STATUS") turns it on/off; the status box shows the true
detected state. The user says all permissions are granted — this module
REPORTS the true state instead of trusting that: autostart on/off,
Python version, Chrome found yes/no, Playwright installed yes/no,
Java/Gradle found yes/no.

The shortcut target is the app's own launcher: <app root>/run.bat when
it exists (the installed EXE), else the bundled Python running main.py.
Creating the .lnk uses a tiny VBScript through cscript (plain Windows,
no extra dependency); removal just deletes the file. Everything returns
plain-words strings and never raises. No Qt anywhere.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_SHORTCUT_NAME = "Mark-LVII.lnk"


# ── Windows startup folder ───────────────────────────────────────────────────

def is_windows() -> bool:
    return platform.system() == "Windows"


def startup_folder() -> str:
    """The user's Startup folder, or \"\" off Windows. Never raises."""
    try:
        if not is_windows():
            return ""
        appdata = os.environ.get("APPDATA") or ""
        if not appdata:
            return ""
        return os.path.join(
            appdata, "Microsoft", "Windows", "Start Menu", "Programs",
            "Startup")
    except Exception:
        return ""


def shortcut_path() -> str:
    """Full path of Mark's startup shortcut, or \"\" off Windows."""
    try:
        folder = startup_folder()
        return os.path.join(folder, _SHORTCUT_NAME) if folder else ""
    except Exception:
        return ""


def autostart_enabled() -> bool:
    """True when Mark's startup shortcut exists. Never raises."""
    try:
        path = shortcut_path()
        return bool(path) and os.path.isfile(path)
    except Exception:
        return False


def _app_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _launch_target() -> tuple[str, str]:
    """(target, arguments) for the shortcut: run.bat when the install has
    one, else the bundled Python + main.py. Never raises."""
    try:
        root = _app_root()
        run_bat = root / "run.bat"
        if run_bat.is_file():
            return str(run_bat), ""
        main_py = root / "main.py"
        return sys.executable or "python", (
            f'"{main_py}"' if main_py.is_file() else "")
    except Exception:
        return sys.executable or "python", ""


def set_autostart(on: bool) -> tuple[bool, str]:
    """Enable/disable Windows autostart. Returns (ok, message). Never
    raises. Off Windows: honest 'Windows-ei kaj kore' (no fake)."""
    try:
        if not is_windows():
            return False, ("Autostart sudhu Windows-e kaj kore — ei PC-te "
                           "Windows noy, tai shortcut banano jabe na.")
        folder = startup_folder()
        if not folder:
            return False, "Windows Startup folder-ta khuje pelam na."
        path = shortcut_path()
        if not on:
            try:
                if os.path.isfile(path):
                    os.remove(path)
                return True, "✅ Autostart OFF — Windows start hole Mark ar nije khulbe na."
            except Exception as e:
                return False, f"Autostart OFF korte parlam na: {e}"
        target, args = _launch_target()
        if not target:
            return False, "Mark-er launcher-ta khuje pelam na."
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception as e:
            return False, f"Startup folder-e jete parlam na: {e}"
        vbs = (
            'Set sh = CreateObject("WScript.Shell")\n'
            f'Set lnk = sh.CreateShortcut("{path}")\n'
            f'lnk.TargetPath = "{target}"\n'
            + (f'lnk.Arguments = "{args}"\n' if args else "")
            + f'lnk.WorkingDirectory = "{_app_root()}"\n'
            + 'lnk.Description = "Mark-LVII Jarvis"\n'
            + "lnk.Save\n"
        )
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".vbs",
                                           delete=False,
                                           encoding="utf-8") as f:
                f.write(vbs)
                vbs_path = f.name
            try:
                r = subprocess.run(["cscript", "//nologo", vbs_path],
                                   capture_output=True, text=True, timeout=30)
            finally:
                try:
                    os.remove(vbs_path)
                except Exception:
                    pass
            if r.returncode != 0 or not os.path.isfile(path):
                err = (r.stderr or r.stdout or "").strip()
                return False, ("Autostart shortcut banate parlam na"
                               + (f": {err[:160]}" if err else "."))
            return True, ("✅ Autostart ON — Windows start hole Mark nije "
                          "khule jabe.")
        except Exception as e:
            return False, f"Autostart ON korte parlam na: {e}"
    except Exception as e:
        return False, f"Autostart bodlate parlam na: {e}"


# ── environment probe ────────────────────────────────────────────────────────

def _which_version(cmd: str, args: list[str],
                   timeout: int = 5) -> tuple[bool, str]:
    """(found, first-line-of-version-output). Never raises."""
    try:
        exe = shutil.which(cmd)
        if not exe:
            return False, ""
        r = subprocess.run([exe] + args, capture_output=True, text=True,
                           timeout=timeout)
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        first = out.splitlines()[0].strip() if out.splitlines() else ""
        return True, first[:120]
    except Exception:
        return False, ""


def _playwright_installed() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def _chrome_path() -> str:
    """The user's Chrome, or \"\". Never raises."""
    try:
        from core import browser_driver as _bd
        return _bd.find_chrome_exe()
    except Exception:
        return ""


def environment_status() -> dict:
    """True detected state of this PC. Never raises.

    Keys: os, autostart (bool), autostart_note, python_version,
    python_exe, chrome (path or ""), chrome_found, playwright (bool),
    java (bool), java_version, gradle (bool), gradle_version.
    """
    try:
        java_ok, java_ver = _which_version("java", ["-version"])
        gradle_ok, gradle_ver = _which_version("gradle", ["--version"])
        chrome = _chrome_path()
        auto = autostart_enabled()
        return {
            "os": f"{platform.system()} {platform.release()}",
            "autostart": auto,
            "autostart_note": ("ON — Windows start hole Mark khulbe" if auto
                               else "OFF — Windows start hole Mark khulbe na"),
            "python_version": sys.version.split()[0] if sys.version else "?",
            "python_exe": sys.executable or "",
            "chrome": chrome,
            "chrome_found": bool(chrome),
            "playwright": _playwright_installed(),
            "java": java_ok,
            "java_version": java_ver,
            "gradle": gradle_ok,
            "gradle_version": gradle_ver,
        }
    except Exception:
        return {"os": platform.system(), "autostart": False,
                "autostart_note": "status dekhte parlam na",
                "python_version": "?", "python_exe": "",
                "chrome": "", "chrome_found": False, "playwright": False,
                "java": False, "java_version": "", "gradle": False,
                "gradle_version": ""}


def environment_lines() -> str:
    """environment_status() as short human lines. Never raises."""
    try:
        s = environment_status()
        lines = ["🖥️ System status:"]
        lines.append(f"• OS: {s.get('os', '?')}")
        lines.append("• Autostart: " + ("✅ " if s.get("autostart") else "❌ ")
                     + str(s.get("autostart_note", "")))
        lines.append(f"• Python: {s.get('python_version', '?')}")
        lines.append("• Chrome: " + ("✅ " + str(s.get("chrome", "")) if s.get("chrome_found")
                                     else "❌ install pelam na"))
        lines.append("• Playwright: " + ("✅ install ache" if s.get("playwright")
                                         else "❌ install nei (prothom browser use-e auto-install)"))
        if s.get("java"):
            lines.append(f"• Java: ✅ {s.get('java_version', '')}")
        else:
            lines.append("• Java: ❌ pelam na (local Gradle build-er jonno lagbe)")
        if s.get("gradle"):
            lines.append(f"• Gradle: ✅ {s.get('gradle_version', '')}")
        else:
            lines.append("• Gradle: ❌ pelam na (local build-er jonno lagbe; GitHub Actions path cholbe)")
        return "\n".join(lines)
    except Exception as e:
        return f"System status dekhte parlam na: {e}"
