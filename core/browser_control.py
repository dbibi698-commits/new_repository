"""core/browser_control.py — 🖱️ Mouse-driven Chrome control (no extension).

Opens the user's REAL Google Chrome with the MOUSE — the way a human
would: click the Windows Start button, type "chrome", press Enter — and
then drives the page precisely with the no-extension Playwright/CDP driver
(core/browser_driver.py). The mouse opens the browser where the user can
SEE it happen; the driver does the precise clicks/types by selector
underneath, because a mouse alone cannot see the DOM.

Backend order (same as browser_driver): Playwright persistent context over
the user's own Chrome profile (so github.com / dashboard.render.com logins
work) first, CDP attach to the running Chrome second, pyautogui last resort
— and the pyautogui backend CANNOT run the flows (no DOM), so it is
reported plainly as "driver not ready" instead of pretending.

Every function returns (ok, message) or a short string and never raises.
No Qt anywhere — runs on worker threads.
"""
from __future__ import annotations

import platform
import socket
import time

try:
    from core import mouse_control as _mc
except Exception:  # pragma: no cover - never on a real install
    _mc = None

try:
    from core import browser_driver as _drv
except Exception:  # pragma: no cover - never on a real install
    _drv = None

_CDP_PORT = 9222


# ── helpers ──────────────────────────────────────────────────────────────────

def _chrome_running() -> bool:
    """True when a Chrome window/process answers. Never raises."""
    # CDP port answering means a debuggable Chrome is up.
    try:
        s = socket.create_connection(("127.0.0.1", _CDP_PORT), timeout=1.0)
        s.close()
        return True
    except Exception:
        pass
    try:
        import psutil
        for proc in psutil.process_iter(["name"]):
            name = str((proc.info or {}).get("name") or "").lower()
            if name in ("chrome.exe", "chrome", "chromium.exe", "chromium"):
                return True
    except Exception:
        pass
    return False


def _wait_chrome(timeout: float = 15.0) -> bool:
    deadline = time.time() + max(1.0, float(timeout))
    while time.time() < deadline:
        if _chrome_running():
            return True
        time.sleep(0.5)
    return False


# ── mouse-driven open ────────────────────────────────────────────────────────

def open_chrome_mouse(url: str = "https://www.google.com",
                      driver_fn=None) -> tuple[bool, str]:
    """Open Google Chrome with the MOUSE, then attach the driver and go to
    `url`. Returns (ok, message). Never raises.

    Steps (Windows): mouse-click the Start button (bottom-left) -> type
    "chrome" -> Enter -> wait for the Chrome window -> attach the
    Playwright/CDP driver -> navigate to `url`. On a non-Windows PC the
    Start click is skipped and the driver launches Chrome itself, said
    plainly. `driver_fn` exists so tests can inject a fake driver factory;
    production code never passes it.
    """
    try:
        if _mc is None:
            return (False, "Mouse control module pelam na — install thik ache kina dekho.")
        system = platform.system()
        w, h = _mc.screen_size()
        if w <= 0 or h <= 0:
            return (False, "Screen-er size pelam na — display on ache kina dekho.")
        if system == "Windows":
            # 1. Mouse diye Start button click (bottom-left corner).
            ok, msg = _mc.click(15, h - 15)
            if not ok:
                return (False, f"Start button-e click korte parlam na: {msg}")
            time.sleep(0.8)
            # 2. "chrome" type kore Enter — Start search theke Chrome khulbe.
            ok, msg = _mc.type_text("chrome")
            if not ok:
                return (False, f"Start-e 'chrome' type korte parlam na: {msg}")
            time.sleep(0.8)
            ok, msg = _mc.press_key("enter")
            if not ok:
                return (False, f"Enter chapte parlam na: {msg}")
        else:
            return (False,
                    "Mouse diye Chrome khola ekhono sudhu Windows-e support kori — "
                    "onno OS-e Chrome nije khulo, tarpor driver attach korbo.")
        if not _wait_chrome(timeout=15.0):
            return (False,
                    "Start theke Chrome khulte bollam, kintu 15 sec-e Chrome-er "
                    "window pelam na — Chrome install ache kina dekho.")
        # 3. Precise control-er jonno driver attach.
        return drive_url(url, driver_fn=driver_fn)
    except Exception as e:
        return (False, f"Chrome khulte parlam na: {e}")


def drive_url(url: str, driver_fn=None) -> tuple[bool, str]:
    """Attach the no-extension driver and navigate to `url`.
    Returns (ok, message). Never raises."""
    try:
        url = (url or "").strip() or "https://www.google.com"
        if _drv is None:
            return (False, "Browser driver module pelam na.")
        ensure = driver_fn if driver_fn is not None else _drv.ensure_driver
        driver, backend, msg = ensure()
        if driver is None:
            return (False, f"Driver ready noy — {msg}")
        if backend == _drv.BACKEND_PYAUTOGUI:
            try:
                driver.close()
            except Exception:
                pass
            return (False,
                    "Chrome khuleche, kintu driver ready noy — pyautogui backend "
                    "DOM dekhte pare na, tai page-e click/type kora jabe na. "
                    "PC-te `pip install playwright` chalao, tarpor abar try koro.")
        try:
            ok, nav_msg = driver.navigate(url)
        except Exception as e:
            return (False, f"Driver attach holo kintu {url}-e jete parlam na: {e}")
        try:
            driver.close()
        except Exception:
            pass
        if ok:
            return (True,
                    f"✅ Chrome khule {url}-e gelam (driver: {backend} — "
                    f"tomar login/cookies kaj korbe).")
        return (False, f"Chrome khullam kintu {url}-e jete parlam na: {nav_msg}")
    except Exception as e:
        return (False, f"Browser chalate parlam na: {e}")


def chrome_status() -> str:
    """One-line status: is Chrome running, is the driver ready? Never raises."""
    try:
        running = _chrome_running()
        if _drv is None:
            return "Browser driver module pelam na."
        driver, backend, msg = _drv.ensure_driver(auto_install=False)
        if driver is None:
            return (f"Chrome {'cholche' if running else 'bondho'} — driver ready "
                    f"noy: {msg}")
        try:
            driver.close()
        except Exception:
            pass
        return (f"Chrome {'cholche' if running else 'bondho'} — driver ready "
                f"({backend}).")
    except Exception as e:
        return f"Chrome-er status dekhte parlam na: {e}"
