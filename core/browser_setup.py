"""core/browser_setup.py — 🧪 BROWSER SETUP WIZARD + Playwright sample.

The user asked for the FULL Playwright process, shown and runnable inside
Mark: system Python check -> ``pip install playwright`` -> ``playwright
install`` (browser download) -> a real Python file that opens the browser,
goes to a URL and clicks an element by selector.

IMPORTANT distinction (shown in the UI too): Mark ships its own bundled
embeddable Python for Mark itself. The wizard is about the SYSTEM Python
the user installs on their PC — the one their own Playwright scripts run
with. ``sys.executable`` here is Mark's bundled Python and is deliberately
NOT used as the system Python.

Every function returns (ok, message) / a plain dict and never raises.
Long commands run through an injectable ``runner`` so tests can fake
subprocess without touching a real Python or the network. No Qt anywhere
in this module — it runs on worker threads.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

# ── steps ────────────────────────────────────────────────────────────────────
STEPS = ("python", "pip", "install", "verify")
STEP_LABELS = {
    "python": "1️⃣  Python check (system Python ache kina)",
    "pip": "2️⃣  pip install playwright",
    "install": "3️⃣  playwright install (browser download ~150 MB)",
    "verify": "4️⃣  Verify — Playwright diye browser launch hoy kina",
}

PYTHON_GUIDANCE = (
    "PC-te Python install nei. python.org theke Python install koro — "
    "install-er somoy 'Add Python to PATH' tick dite hobe, naile CMD-te "
    "python cholbe na. (Mark-er nijer bundled Python diye tomar script "
    "cholbe na — system Python lagbe.)"
)

PIP_MISSING_GUIDANCE = (
    "pip pelam na ei Python-e. `python -m ensurepip` chalao, naile "
    "python.org theke Python abar install koro (pip tick kore)."
)

NO_INTERNET_HINT = "Internet lagbe — net connection check koro, tarpor abar chesta koro."

_STATE: dict[str, dict[str, str]] = {}


def reset_wizard() -> None:
    """Reset all step statuses to pending (tests + 'Run again')."""
    _STATE.clear()
    for step in STEPS:
        _STATE[step] = {"status": "pending", "message": ""}


def wizard_state() -> dict[str, dict[str, str]]:
    if not _STATE:
        reset_wizard()
    return {s: dict(_STATE[s]) for s in STEPS}


def _set_step(step: str, status: str, message: str = "") -> None:
    if not _STATE:
        reset_wizard()
    _STATE[step] = {"status": status, "message": message}


def _default_run(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr). Never raises."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout)
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except FileNotFoundError:
        return 127, "", f"Command pelam na: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"Timeout ({timeout}s) — command sesh holo na."
    except Exception as e:  # noqa: BLE001 - never raise from a runner
        return 1, "", str(e)


def _log(log_fn, text: str) -> None:
    if log_fn is None:
        return
    try:
        log_fn(text)
    except Exception:
        pass


def _version_of(output: str) -> str:
    """'Python 3.12.4' from 'Python 3.12.4\\n' — '' when it is not Python."""
    m = re.search(r"Python\s+(\d+\.\d+(?:\.\d+)?)", output or "")
    return m.group(1) if m else ""


def find_system_python(runner=None, which_fn=None) -> tuple[str, str]:
    """Find the SYSTEM Python (PATH theke), NOT Mark's bundled one.

    Tries ``python``, ``python3`` and the Windows ``py`` launcher, in that
    order. Returns (exe_path, version) or ("", "") when none is found.
    """
    run = runner or _default_run
    which = which_fn or shutil.which
    for candidate in ("python", "python3", "py"):
        exe = which(candidate)
        if not exe:
            continue
        # Never accept Mark's own bundled python as the "system" one.
        try:
            if os.path.abspath(exe) == os.path.abspath(sys.executable):
                continue
        except Exception:
            pass
        rc, out, _err = run([exe, "--version"], timeout=15)
        version = _version_of(out) if rc == 0 else ""
        if version:
            return exe, version
    return "", ""


def check_python(runner=None, which_fn=None) -> dict:
    """Step 1 — is a system Python installed? Plain-words result."""
    exe, version = find_system_python(runner=runner, which_fn=which_fn)
    if exe:
        return {"ok": True, "path": exe, "version": version,
                "message": f"✅ Python {version} pelam: {exe}"}
    return {"ok": False, "path": "", "version": "",
            "message": "❌ " + PYTHON_GUIDANCE}


def _is_network_error(text: str) -> bool:
    low = (text or "").lower()
    return any(k in low for k in (
        "could not fetch url", "failed to establish a new connection",
        "temporary failure in name resolution", "network is unreachable",
        "connection reset", "connection timed out", "name or service not known",
        "no internet", "err_internet_disconnected"))


def pip_install_playwright(python_exe: str, runner=None,
                           log_fn=None) -> tuple[bool, str, str]:
    """Step 2 — ``<python> -m pip install playwright``. Streams output."""
    run = runner or _default_run
    cmd = [python_exe, "-m", "pip", "install", "playwright"]
    _log(log_fn, "▶ " + " ".join(cmd))
    rc, out, err = run(cmd, timeout=600)
    combined = (out or "") + ("\n" + err if err else "")
    for line in combined.splitlines():
        if line.strip():
            _log(log_fn, line.rstrip())
    if "No module named pip" in combined:
        return False, "❌ " + PIP_MISSING_GUIDANCE, combined
    if rc != 0:
        if _is_network_error(combined):
            return False, "❌ pip install holo na — " + NO_INTERNET_HINT, combined
        return False, (f"❌ pip install fail holo (exit {rc}). "
                       "Output-ta upore dekho."), combined
    return True, "✅ pip install playwright hoye geche.", combined


def playwright_install(python_exe: str, browsers=("chromium",),
                       runner=None, log_fn=None) -> tuple[bool, str, str]:
    """Step 3 — ``<python> -m playwright install <browsers>``.

    Downloads the browsers (~150 MB for Chromium). Progress lines are
    streamed to log_fn; a trailing 'NN%' is reported when the tool prints
    one. ``browsers`` may be ("chromium",), ("firefox",), ("webkit",) or
    any combination.
    """
    run = runner or _default_run
    wanted = [b for b in (browsers or ("chromium",)) if b]
    cmd = [python_exe, "-m", "playwright", "install", *wanted]
    _log(log_fn, "▶ " + " ".join(cmd) +
         "   (download ~150 MB hote pare — ektu somoy lagbe)")
    rc, out, err = run(cmd, timeout=1800)
    combined = (out or "") + ("\n" + err if err else "")
    for line in combined.splitlines():
        line = line.rstrip()
        if line.strip():
            _log(log_fn, line)
    if rc != 0:
        if _is_network_error(combined):
            return False, "❌ Browser download holo na — " + NO_INTERNET_HINT, combined
        if "is not installed" in combined or "No module named playwright" in combined:
            return False, ("❌ Playwright install kora nei — age step 2 "
                           "(pip install playwright) koro."), combined
        return False, (f"❌ playwright install fail holo (exit {rc}). "
                       "Output-ta upore dekho."), combined
    names = ", ".join(wanted)
    return True, f"✅ Browser download hoye geche: {names}.", combined


def playwright_cache_dir() -> str:
    """Where ``playwright install`` puts browsers, per OS."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "ms-playwright")
    return os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright")


def installed_browsers(cache_dir: str | None = None) -> list[str]:
    """Browsers already downloaded in the ms-playwright cache (names only)."""
    directory = cache_dir or playwright_cache_dir()
    try:
        names = sorted(
            d for d in os.listdir(directory)
            if os.path.isdir(os.path.join(directory, d)))
    except Exception:
        names = []
    return names


_VERIFY_SCRIPT = (
    "from playwright.sync_api import sync_playwright\n"
    "with sync_playwright() as p:\n"
    "    b = p.chromium.launch(headless=True)\n"
    "    pg = b.new_page()\n"
    "    pg.goto('about:blank')\n"
    "    print('LAUNCH-OK', pg.url)\n"
    "    b.close()\n"
)


def verify_playwright(python_exe: str, runner=None,
                      timeout: int = 120) -> tuple[bool, str]:
    """Step 4 — can Playwright actually launch a browser? Tiny real check."""
    run = runner or _default_run
    rc, out, err = run([python_exe, "-c", _VERIFY_SCRIPT], timeout=timeout)
    combined = (out or "") + ("\n" + err if err else "")
    if rc == 0 and "LAUNCH-OK" in combined:
        return True, "✅ Verify holo — Playwright diye browser launch hoy."
    if "No module named playwright" in combined:
        return False, ("❌ Playwright install kora nei — age step 2 "
                       "(pip install playwright) koro.")
    if _is_network_error(combined):
        return False, "❌ Verify holo na — " + NO_INTERNET_HINT
    return False, ("❌ Browser launch holo na. Error: " +
                   (combined.strip().splitlines()[-1]
                    if combined.strip() else "unknown"))


def sample_path() -> str:
    """Path of the shipped runnable sample (samples/browser_sample.py)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "samples",
                        "browser_sample.py")


def sample_code(url: str = "https://example.com",
                selector: str = "a") -> str:
    """The sample source with the user's URL/selector filled in.

    The shipped file is the source of truth — its DEFAULT_URL /
    DEFAULT_SELECTOR are replaced, so what you copy is what runs.
    """
    path = sample_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
    except Exception as e:
        return f"# Sample file pelam na ({path}): {e}"
    # NOTE (2026-11-18 fix): the shipped file uses DOUBLE quotes for
    # DEFAULT_SELECTOR, so the old single-quote regex never matched and
    # the user's selector was silently ignored. Match either quote and
    # write the value back with repr() so quotes inside it stay valid.
    src = re.sub(r'^DEFAULT_URL = .*$',
                 lambda m: f"DEFAULT_URL = {url!r}", src, flags=re.M)
    src = re.sub(r"^DEFAULT_SELECTOR = .*$",
                 lambda m: f"DEFAULT_SELECTOR = {selector!r}", src,
                 flags=re.M)
    return src


def run_sample(python_exe: str, url: str = "https://example.com",
               selector: str = "a", runner=None,
               log_fn=None) -> tuple[bool, str, str]:
    """Run the shipped sample with the system Python. Streams output."""
    run = runner or _default_run
    path = sample_path()
    if not os.path.exists(path):
        return False, f"❌ Sample file pelam na: {path}", ""
    cmd = [python_exe, path, "--url", url, "--selector", selector]
    _log(log_fn, "▶ " + " ".join(cmd))
    rc, out, err = run(cmd, timeout=180)
    combined = (out or "") + ("\n" + err if err else "")
    for line in combined.splitlines():
        if line.strip():
            _log(log_fn, line.rstrip())
    if rc != 0:
        if "No module named playwright" in combined:
            return False, ("❌ Playwright install kora nei — age Browser "
                           "Setup wizard-er step 2-3 koro."), combined
        return False, (f"❌ Sample cholte giye thamlo (exit {rc}). "
                       "Output-ta upore dekho."), combined
    return True, "✅ Sample cholllo — browser khullo, URL-e gelo, click holo.", combined


def run_all_steps(python_exe: str | None = None, runner=None,
                  log_fn=None) -> dict:
    """Run the whole wizard in order; stop at the first failed step.

    Returns the step-state dict. ``python_exe`` may be "" — then step 1
    finds the system Python itself.
    """
    reset_wizard()
    check = check_python(runner=runner)
    exe = python_exe or check.get("path") or ""
    _set_step("python", "done" if check["ok"] else "failed",
              check["message"])
    _log(log_fn, check["message"])
    if not check["ok"]:
        return wizard_state()
    _set_step("pip", "running", "pip install playwright cholche…")
    ok, msg, _out = pip_install_playwright(exe, runner=runner, log_fn=log_fn)
    _set_step("pip", "done" if ok else "failed", msg)
    _log(log_fn, msg)
    if not ok:
        return wizard_state()
    _set_step("install", "running", "playwright install cholche…")
    ok, msg, _out = playwright_install(exe, runner=runner, log_fn=log_fn)
    _set_step("install", "done" if ok else "failed", msg)
    _log(log_fn, msg)
    if not ok:
        return wizard_state()
    _set_step("verify", "running", "Verify cholche…")
    ok, msg = verify_playwright(exe, runner=runner)
    _set_step("verify", "done" if ok else "failed", msg)
    _log(log_fn, msg)
    return wizard_state()


def status_text() -> str:
    """One short readiness summary for the agent card."""
    check = check_python()
    lines = ["🧪 Browser Setup — Playwright full process:"]
    if check["ok"]:
        lines.append(f"  • System Python: {check['version']} ({check['path']})")
    else:
        lines.append("  • System Python: ❌ install nei — python.org theke nao")
    browsers = installed_browsers()
    if browsers:
        lines.append("  • Downloaded browser: " + ", ".join(browsers))
    else:
        lines.append("  • Downloaded browser: (ekhono kichu download hoy ni)")
    lines.append("  • Sample: samples/browser_sample.py "
                 "(kholo → URL → click → screenshot)")
    lines.append("  • Internet lagbe (pip + browser download ~150 MB)")
    return "\n".join(lines)
