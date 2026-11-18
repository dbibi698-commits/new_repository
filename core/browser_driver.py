"""core/browser_driver.py — NO-EXTENSION browser driver for Mark-LVII.

Drives the user's REAL installed Chrome — the one they are already logged
into on github.com and dashboard.render.com — with no browser extension
involved at all. The extension is a separate, already-delivered feature;
nothing in this module imports it, talks to the dashboard browser-command
queue, or depends on it in any way.

Backend order (best first):

1. "playwright" — Playwright for Python, ``channel="chrome"``, launched as a
   PERSISTENT context over the user's own Chrome profile directory. A plain
   ``launch(channel="chrome")`` uses a throwaway profile, so the user would
   NOT be logged in — persistent context is the whole point. Fails honestly
   when Chrome is already running with that profile (Chrome locks it).
2. "cdp" — Playwright's ``connect_over_cdp("http://localhost:9222")`` to a
   Chrome that is already running with ``--remote-debugging-port=9222``. If
   nothing answers on 9222 and Chrome is NOT already running, the driver
   launches Chrome itself with that flag + the user's profile, then attaches.
   If Chrome IS already running without the flag, this backend cannot attach
   (a second chrome.exe just opens a window in the running instance) and
   says so plainly.
3. "pyautogui" — last resort: screen mouse + keyboard only. It can navigate
   (Ctrl+L, type URL, Enter) and move/click the mouse, but it CANNOT see the
   DOM, so click/fill/read_text by selector are refused with a plain message
   instead of pretending. The flows need DOM access, so they treat this
   backend as "driver not ready".

``ensure_driver()`` picks the best available backend and reports which one
is active. Every method returns ``(ok, message)`` and never raises. No Qt
anywhere in this module — it runs on worker threads.

Playwright is installed on first use when missing (``pip install
playwright``); with ``channel="chrome"`` no ``playwright install`` browser
download is needed — the user's own Chrome is the browser.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import time

# Backends in preference order.
BACKEND_PLAYWRIGHT = "playwright"
BACKEND_CDP = "cdp"
BACKEND_PYAUTOGUI = "pyautogui"

CDP_PORT = 9222
CDP_URL = f"http://localhost:{CDP_PORT}"
_STEP_TIMEOUT_MS = 15000

# Set once per process so a missing Playwright is only pip-installed once.
_INSTALL_TRIED = False


def default_user_data_dir() -> str:
    """The user's real Chrome profile directory, per OS."""
    system = platform.system()
    home = os.path.expanduser("~")
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return os.path.join(base, "Google", "Chrome", "User Data")
    if system == "Darwin":
        return os.path.join(home, "Library", "Application Support",
                            "Google", "Chrome")
    return os.path.join(home, ".config", "google-chrome")


def find_chrome_exe() -> str:
    """Path to the user's installed Chrome, or "" when none is found."""
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    if platform.system() == "Windows":
        for cand in (
            os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                         "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                         "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "Google", "Chrome", "Application", "chrome.exe"),
        ):
            if cand and os.path.isfile(cand):
                return cand
    if platform.system() == "Darwin":
        cand = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if os.path.isfile(cand):
            return cand
    return ""


def _load_playwright():
    """The ``sync_playwright`` callable, or None when Playwright is missing."""
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except Exception:
        return None


def _try_install_playwright() -> bool:
    """Best-effort ``pip install playwright`` (once per process). Returns
    True when Playwright imports afterwards. Never raises."""
    global _INSTALL_TRIED
    if _INSTALL_TRIED:
        return _load_playwright() is not None
    _INSTALL_TRIED = True
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "playwright>=1.40,<2"],
            capture_output=True, timeout=300)
    except Exception:
        return False
    return _load_playwright() is not None


def _load_pyautogui():
    """The pyautogui module, or None (headless machines import-fail)."""
    try:
        import pyautogui
        return pyautogui
    except Exception:
        return None


def _chrome_already_running() -> bool:
    """Best-effort check whether a Chrome process is already up."""
    try:
        if platform.system() == "Windows":
            out = subprocess.run(["tasklist"], capture_output=True,
                                 text=True, timeout=10).stdout or ""
            return "chrome.exe" in out.lower()
        out = subprocess.run(["pgrep", "-x", "chrome"], capture_output=True,
                             timeout=10)
        if out.returncode == 0:
            return True
        out = subprocess.run(["pgrep", "-f", "google-chrome"],
                             capture_output=True, timeout=10)
        return out.returncode == 0
    except Exception:
        return False


class Driver:
    """One browser session behind a single backend.

    ``backend`` is "playwright" | "cdp" | "pyautogui" | "" (not launched).
    ``dom_capable`` is False for the pyautogui backend — it has no DOM.
    Use :func:`ensure_driver` instead of building one by hand.
    """

    def __init__(self, backend: str = "", playwright_fn=None,
                 pyautogui_mod=None, user_data_dir: str | None = None):
        self.backend = backend
        self.dom_capable = backend in (BACKEND_PLAYWRIGHT, BACKEND_CDP)
        self._pw_fn = playwright_fn
        self._pag = pyautogui_mod
        self.user_data_dir = user_data_dir or default_user_data_dir()
        self._pw = None          # sync_playwright instance
        self._browser = None     # playwright Browser / CDP browser
        self._context = None     # playwright BrowserContext (persistent)
        self._page = None        # playwright Page
        self._cdp_proc = None    # Chrome we launched ourselves for CDP
        self._launched_by_us = False

    # ── lifecycle ────────────────────────────────────────────────────────

    def launch(self) -> tuple[bool, str]:
        """Start the backend this Driver was built for. Never raises."""
        try:
            if self.backend == BACKEND_PLAYWRIGHT:
                return self._launch_playwright()
            if self.backend == BACKEND_CDP:
                return self._launch_cdp()
            if self.backend == BACKEND_PYAUTOGUI:
                return self._launch_pyautogui()
            return False, "No backend picked — use ensure_driver() first."
        except Exception as e:  # never raise out of the driver
            return False, f"Browser launch failed: {e}"

    def _launch_playwright(self) -> tuple[bool, str]:
        pw_fn = self._pw_fn or _load_playwright()
        if pw_fn is None:
            return False, "Playwright install kora nei."
        try:
            self._pw = pw_fn().start()
        except Exception as e:
            return False, f"Playwright start holo na: {e}"
        try:
            # Persistent context over the USER's profile = their logins and
            # cookies. A plain launch() would use a throwaway profile and
            # the user would be logged out everywhere.
            self._context = self._pw.chromium.launch_persistent_context(
                self.user_data_dir, channel="chrome", headless=False,
                args=["--start-maximized"])
            pages = list(self._context.pages or [])
            self._page = pages[0] if pages else self._context.new_page()
            self._launched_by_us = True
            return True, ("Playwright + tomar Chrome (profile diye) — "
                          "github.com / Render-e login thakle cholbe.")
        except Exception as e:
            self._stop_pw_quietly()
            msg = str(e)
            if "already running" in msg.lower() or "profile" in msg.lower() \
                    or "singleton" in msg.lower() or "lock" in msg.lower():
                return False, ("Chrome already khula ache ei profile diye — "
                               "Playwright profile lock korte parlo na. "
                               "Chrome bondho kore abar try koro, na CDP "
                               "backend use koro.")
            return False, f"Playwright Chrome khulte parlo na: {e}"

    def _launch_cdp(self) -> tuple[bool, str]:
        pw_fn = self._pw_fn or _load_playwright()
        if pw_fn is None:
            return False, "Playwright install kora nei — CDP-o cholbe na."
        try:
            self._pw = pw_fn().start()
        except Exception as e:
            return False, f"Playwright start holo na: {e}"
        # 1) Something already listening on 9222?
        ok, msg = self._cdp_attach()
        if ok:
            return True, msg
        # 2) Launch Chrome ourselves with the debugging flag — only works
        # when Chrome is NOT already running (otherwise the new process just
        # opens a window in the running instance and the flag is ignored).
        if _chrome_already_running():
            self._stop_pw_quietly()
            return False, ("Chrome khula ache kintu --remote-debugging-port "
                           "chara — CDP attach kora jabe na. Chrome bondho "
                           "kore abar try koro, na Chrome-e ei flag diye "
                           "kholo: chrome --remote-debugging-port=9222")
        chrome = find_chrome_exe()
        if not chrome:
            self._stop_pw_quietly()
            return False, "Chrome install khuje pelam na ei PC-te."
        try:
            self._cdp_proc = subprocess.Popen(
                [chrome, f"--remote-debugging-port={CDP_PORT}",
                 f"--user-data-dir={self.user_data_dir}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self._stop_pw_quietly()
            return False, f"Chrome launch korte parlam na: {e}"
        for _ in range(20):  # up to ~10 s for the DevTools port to answer
            time.sleep(0.5)
            ok, msg = self._cdp_attach()
            if ok:
                self._launched_by_us = True
                return True, msg
        self._stop_pw_quietly()
        return False, "Chrome khullam kintu CDP port 9222-e answer dilo na."

    def _cdp_attach(self) -> tuple[bool, str]:
        try:
            self._browser = self._pw.chromium.connect_over_cdp(CDP_URL)
            contexts = list(self._browser.contexts or [])
            if not contexts:
                return False, "CDP connect holo kintu kono context pelam na."
            ctx = contexts[0]
            pages = list(ctx.pages or [])
            self._context = ctx
            self._page = pages[0] if pages else ctx.new_page()
            return True, ("CDP diye cholti Chrome-e attach holo — tomar "
                          "login/cookies kaj korbe.")
        except Exception as e:
            return False, f"CDP attach holo na: {e}"

    def _launch_pyautogui(self) -> tuple[bool, str]:
        pag = self._pag if self._pag is not None else _load_pyautogui()
        if pag is None:
            return False, "pyautogui load holo na (headless PC-te cholbe na)."
        self._pag = pag
        try:
            self._pag.FAILSAFE = False
        except Exception:
            pass
        return True, ("pyautogui mouse/keyboard backend — sudhu navigate "
                      "ar mouse click; form fill / page read kora jabe na.")

    def _stop_pw_quietly(self) -> None:
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    def close(self) -> tuple[bool, str]:
        """Detach. Never closes the user's own running Chrome (CDP backend):
        only a browser this driver launched itself is closed."""
        try:
            if self._page is not None and self.backend == BACKEND_PLAYWRIGHT:
                try:
                    self._context.close()
                except Exception:
                    pass
            if self._cdp_proc is not None:
                try:
                    self._cdp_proc.terminate()
                except Exception:
                    pass
                self._cdp_proc = None
            self._stop_pw_quietly()
            self._page = None
            return True, "Browser driver bondho holo."
        except Exception as e:
            return False, f"Driver bondho korte giye error: {e}"

    # ── helpers ──────────────────────────────────────────────────────────

    def current_url(self) -> str:
        try:
            if self._page is not None:
                return str(getattr(self._page, "url", "") or "")
        except Exception:
            pass
        return ""

    def _need_dom(self) -> tuple[bool, str] | None:
        """(False, reason) when this backend cannot touch the DOM."""
        if self._page is None:
            if self.backend == BACKEND_PYAUTOGUI:
                return (False, "pyautogui backend-e DOM dekha jay na — "
                        "Playwright/CDP backend lagbe.")
            return (False, "Browser driver launch kora nei — age launch koro.")
        return None

    def _need_page(self):
        return self._page

    # ── actions ──────────────────────────────────────────────────────────

    def navigate(self, url: str) -> tuple[bool, str]:
        """Go to a URL. pyautogui backend: Ctrl+L, type, Enter."""
        try:
            url = (url or "").strip()
            if not url:
                return False, "navigate-e URL dao."
            if self.backend == BACKEND_PYAUTOGUI:
                if self._pag is None:
                    return False, "pyautogui backend launch kora nei."
                self._pag.hotkey("ctrl", "l")
                time.sleep(0.4)
                self._pag.typewrite(url, interval=0.01)
                self._pag.press("enter")
                time.sleep(1.0)
                return True, f"Address bar-e gelam: {url}"
            blocked = self._need_dom()
            if blocked:
                return blocked
            self._page.goto(url, timeout=60000, wait_until="domcontentloaded")
            time.sleep(1.0)
            return True, f"Gelam: {self.current_url() or url}"
        except Exception as e:
            return False, f"Navigate korte parlam na ({url}): {e}"

    def click(self, selector: str) -> tuple[bool, str]:
        """Click one element. Playwright selectors: CSS, ``text=...``,
        ``button:has-text('...')`` — see the flows in browser_automation."""
        try:
            selector = (selector or "").strip()
            if not selector:
                return False, "click-e selector dao."
            blocked = self._need_dom()
            if blocked:
                return blocked
            self._page.click(selector, timeout=_STEP_TIMEOUT_MS)
            time.sleep(0.6)
            return True, f"Click korlam: {selector}"
        except Exception as e:
            return False, f"Click korte parlam na ({selector}): {e}"

    def fill(self, selector: str, text: str) -> tuple[bool, str]:
        """Fill a text field (clears it first)."""
        try:
            selector = (selector or "").strip()
            if not selector:
                return False, "fill-e selector dao."
            blocked = self._need_dom()
            if blocked:
                return blocked
            self._page.fill(selector, text or "", timeout=_STEP_TIMEOUT_MS)
            return True, f"Bhorlam: {selector}"
        except Exception as e:
            return False, f"Field bhorte parlam na ({selector}): {e}"

    def wait_for_selector(self, selector: str,
                          timeout_ms: int = 15000) -> tuple[bool, str]:
        """Wait until an element appears. DOM backends only."""
        try:
            selector = (selector or "").strip()
            if not selector:
                return False, "wait_for_selector-e selector dao."
            blocked = self._need_dom()
            if blocked:
                return blocked
            self._page.wait_for_selector(selector, timeout=timeout_ms)
            return True, f"Pelam: {selector}"
        except Exception as e:
            return False, f"Element aslo na ({selector}): {e}"

    def read_text(self, selector: str | None = None) -> tuple[bool, str]:
        """Page (or one element's) visible text. DOM backends only."""
        try:
            blocked = self._need_dom()
            if blocked:
                return blocked
            if selector:
                return True, str(self._page.locator(selector).inner_text(
                    timeout=_STEP_TIMEOUT_MS))
            return True, str(self._page.locator("body").inner_text(
                timeout=_STEP_TIMEOUT_MS))
        except Exception as e:
            return False, f"Page porte parlam na: {e}"

    def screenshot(self, path: str) -> tuple[bool, str]:
        """Save a screenshot to path. Works on every backend."""
        try:
            path = (path or "").strip()
            if not path:
                return False, "screenshot-e path dao."
            if self.backend == BACKEND_PYAUTOGUI:
                if self._pag is None:
                    return False, "pyautogui backend launch kora nei."
                self._pag.screenshot(path)
                return True, f"Screenshot nilam: {path}"
            blocked = self._need_dom()
            if blocked:
                return blocked
            self._page.screenshot(path=path)
            return True, f"Screenshot nilam: {path}"
        except Exception as e:
            return False, f"Screenshot nite parlam na: {e}"

    def type_text(self, selector: str, text: str) -> tuple[bool, str]:
        """Click an element then type into it (for contenteditable fields
        like Facebook's composer or YouTube Studio's title box, where
        fill() cannot work). DOM backends only."""
        try:
            selector = (selector or "").strip()
            if not selector:
                return False, "type_text-e selector dao."
            blocked = self._need_dom()
            if blocked:
                return blocked
            self._page.click(selector, timeout=_STEP_TIMEOUT_MS)
            time.sleep(0.3)
            self._page.keyboard.type(str(text or ""), delay=5)
            return True, f"Type korlam: {selector}"
        except Exception as e:
            return False, f"Type korte parlam na ({selector}): {e}"

    def set_input_files(self, selector: str, path: str) -> tuple[bool, str]:
        """Set a <input type=file> value without opening the OS file
        picker (Playwright set_input_files — the upload flows use this
        for Instagram/Facebook/YouTube). DOM backends only; the
        pyautogui backend has no DOM and refuses honestly."""
        try:
            selector = (selector or "").strip()
            path = (path or "").strip()
            if not selector:
                return False, "set_input_files-e selector dao."
            if not path:
                return False, "set_input_files-e file path dao."
            blocked = self._need_dom()
            if blocked:
                return blocked
            self._page.set_input_files(selector, path,
                                       timeout=_STEP_TIMEOUT_MS)
            return True, f"File select korlam: {path}"
        except Exception as e:
            return False, f"File select korte parlam na ({selector}): {e}"

    def fill_form(self, fields: dict, submit_selector: str | None = None) -> tuple[bool, str]:
        """Fill several fields in order, then optionally click a submit
        button. `fields` is {selector: text}. DOM backends only — the
        first field that fails stops the run and the message names it."""
        try:
            fields = fields or {}
            if not isinstance(fields, dict) or not fields:
                return False, "fill_form-e field dao — {selector: text}."
            blocked = self._need_dom()
            if blocked:
                return blocked
            filled = 0
            for selector, text in fields.items():
                selector = str(selector or "").strip()
                if not selector:
                    return False, "fill_form-e khali selector pelam."
                try:
                    self._page.fill(selector, str(text or ""),
                                  timeout=_STEP_TIMEOUT_MS)
                except Exception as e:
                    return False, (f"Field bhorte parlam na ({selector}): "
                                   f"{e}")
                filled += 1
            if submit_selector:
                ok, msg = self.click(str(submit_selector))
                if not ok:
                    return False, f"Submit chapte parlam na: {msg}"
                return True, (f"Form bhorlam ({filled} ta field) + "
                              "submit chaplam.")
            return True, f"Form bhorlam ({filled} ta field)."
        except Exception as e:
            return False, f"Form bhorte parlam na: {e}"

    def new_tab(self, url: str | None = None) -> tuple[bool, str]:
        """Open a new tab (DOM backends only) and make it the current one."""
        try:
            blocked = self._need_dom()
            if blocked:
                return blocked
            if self._context is None:
                return False, "Browser context pelam na — driver launch koro."
            page = self._context.new_page()
            self._page = page
            count = len(list(self._context.pages or []))
            if (url or "").strip():
                ok, msg = self.navigate(str(url).strip())
                if not ok:
                    return False, msg
                return True, f"Notun tab khullam ({count} ta tab): {self.current_url()}"
            return True, f"Notun tab khullam ({count} ta tab)."
        except Exception as e:
            return False, f"Notun tab khulte parlam na: {e}"

    def list_tabs(self) -> tuple[bool, list[dict]]:
        """All open tabs: [{index, url, title}]. DOM backends only."""
        try:
            blocked = self._need_dom()
            if blocked:
                return False, []
            pages = list(self._context.pages or []) if self._context else []
            out = []
            for i, p in enumerate(pages):
                try:
                    title = str(p.title() or "")
                except Exception:
                    title = ""
                out.append({"index": i,
                            "url": str(getattr(p, "url", "") or ""),
                            "title": title,
                            "current": p is self._page})
            return True, out
        except Exception:
            return False, []

    def switch_tab(self, index: int) -> tuple[bool, str]:
        """Make tab `index` the current one. DOM backends only."""
        try:
            blocked = self._need_dom()
            if blocked:
                return blocked
            pages = list(self._context.pages or []) if self._context else []
            idx = int(index)
            if idx < 0 or idx >= len(pages):
                return False, (f"Tab {idx} nei — {len(pages)} ta tab khula "
                               "ache.")
            self._page = pages[idx]
            try:
                self._page.bring_to_front()
            except Exception:
                pass
            return True, f"Tab {idx}-e gelam: {self.current_url()}"
        except Exception as e:
            return False, f"Tab bodlate parlam na: {e}"

    def close_tab(self, index: int | None = None) -> tuple[bool, str]:
        """Close one tab (the current one by default). Refuses to close
        the LAST tab. DOM backends only."""
        try:
            blocked = self._need_dom()
            if blocked:
                return blocked
            pages = list(self._context.pages or []) if self._context else []
            if len(pages) <= 1:
                return False, "Shesh tab-ta bondho korbo na."
            idx = len(pages) - 1
            if index is not None:
                idx = int(index)
            if idx < 0 or idx >= len(pages):
                return False, (f"Tab {idx} nei — {len(pages)} ta tab khula "
                               "ache.")
            target = pages[idx]
            was_current = target is self._page
            target.close()
            if was_current:
                rest = list(self._context.pages or [])
                self._page = rest[0] if rest else None
            return True, (f"Tab {idx} bondho holo — "
                          f"{len(list(self._context.pages or []))} ta tab baki.")
        except Exception as e:
            return False, f"Tab bondho korte parlam na: {e}"

    def scroll_to_element(self, selector: str) -> tuple[bool, str]:
        """Scroll so an element is visible. DOM backends only."""
        try:
            selector = (selector or "").strip()
            if not selector:
                return False, "scroll_to_element-e selector dao."
            blocked = self._need_dom()
            if blocked:
                return blocked
            self._page.locator(selector).scroll_into_view_if_needed(
                timeout=_STEP_TIMEOUT_MS)
            return True, f"Scroll korlam: {selector}"
        except Exception as e:
            return False, f"Scroll korte parlam na ({selector}): {e}"

    def mouse_move(self, x: int, y: int) -> tuple[bool, str]:
        try:
            if self.backend == BACKEND_PYAUTOGUI:
                if self._pag is None:
                    return False, "pyautogui backend launch kora nei."
                self._pag.moveTo(int(x), int(y))
            else:
                blocked = self._need_dom()
                if blocked:
                    return blocked
                self._page.mouse.move(int(x), int(y))
            return True, f"Mouse gelam ({x}, {y})"
        except Exception as e:
            return False, f"Mouse move holo na: {e}"

    def mouse_click(self, x: int, y: int) -> tuple[bool, str]:
        try:
            if self.backend == BACKEND_PYAUTOGUI:
                if self._pag is None:
                    return False, "pyautogui backend launch kora nei."
                self._pag.click(int(x), int(y))
            else:
                blocked = self._need_dom()
                if blocked:
                    return blocked
                self._page.mouse.click(int(x), int(y))
            return True, f"Mouse click ({x}, {y})"
        except Exception as e:
            return False, f"Mouse click holo na: {e}"

    def eval_js(self, js: str) -> tuple[bool, str]:
        """Evaluate JS on the page and return the result as a string.
        DOM backends only."""
        try:
            js = (js or "").strip()
            if not js:
                return False, "eval_js-e JS dao."
            blocked = self._need_dom()
            if blocked:
                return blocked
            result = self._page.evaluate(js)
            return True, "" if result is None else str(result)
        except Exception as e:
            return False, f"JS evaluate korte parlam na: {e}"

    def press_key(self, key: str) -> tuple[bool, str]:
        """Press one keyboard key ('k' = play/pause on YouTube, 'Enter',
        'Escape', 'Tab'). DOM backends use Playwright's keyboard;
        pyautogui uses its own press."""
        try:
            key = (key or "").strip()
            if not key:
                return False, "press_key-e key dao."
            if self.backend == BACKEND_PYAUTOGUI:
                if self._pag is None:
                    return False, "pyautogui backend launch kora nei."
                self._pag.press(key)
                return True, f"Key press korlam: {key}"
            blocked = self._need_dom()
            if blocked:
                return blocked
            self._page.keyboard.press(key)
            return True, f"Key press korlam: {key}"
        except Exception as e:
            return False, f"Key press korte parlam na ({key}): {e}"

    def play_video(self, selector: str | None = None) -> tuple[bool, str]:
        """Play the video on the page: click it (or press 'k'), then
        verify it is actually playing (video.paused == false)."""
        try:
            blocked = self._need_dom()
            if blocked:
                return blocked
            sel = (selector or "").strip() or "video"
            try:
                self._page.click(sel, timeout=_STEP_TIMEOUT_MS)
            except Exception:
                try:
                    self._page.keyboard.press("k")
                except Exception as e:
                    return False, f"Video play korte parlam na: {e}"
            time.sleep(1.0)
            ok, state = self.eval_js(
                "(() => { const v = document.querySelector('video'); "
                "return v ? (v.paused ? 'paused' : 'playing') : 'no-video'; })()")
            if not ok:
                return False, f"Video state check korte parlam na: {state}"
            if state.strip() == "playing":
                return True, "Video cholche ▶"
            if state.strip() == "no-video":
                return False, "Page-e kono video pelam na."
            return False, "Video-ta play holo na (paused ache)."
        except Exception as e:
            return False, f"Video play korte parlam na: {e}"

    def wait(self, seconds: float) -> tuple[bool, str]:
        """Pause. Always succeeds (even with no browser)."""
        try:
            time.sleep(max(0.0, float(seconds or 0)))
            return True, f"Wait korlam {seconds}s"
        except Exception as e:
            return False, f"Wait korte parlam na: {e}"


def ensure_driver(auto_install: bool = True, playwright_fn=None,
                  pyautogui_mod=None,
                  user_data_dir: str | None = None) -> tuple[Driver | None, str, str]:
    """Pick the best available backend and launch it.

    Returns ``(driver, backend, message)`` — driver is None when nothing
    works, and the message then says plainly what is missing. ``playwright_fn``
    / ``pyautogui_mod`` exist so tests can inject fakes; production code
    never passes them.
    """
    pw_fn = playwright_fn if playwright_fn is not None else _load_playwright()
    if pw_fn is None and auto_install:
        _try_install_playwright()
        pw_fn = _load_playwright()

    if pw_fn is not None:
        drv = Driver(BACKEND_PLAYWRIGHT, playwright_fn=pw_fn,
                     user_data_dir=user_data_dir)
        ok, msg = drv.launch()
        if ok:
            return drv, BACKEND_PLAYWRIGHT, msg
        pw_msg = msg
        # Persistent-context launch failed (usually: Chrome already running
        # with this profile) — try CDP against the running Chrome.
        drv2 = Driver(BACKEND_CDP, playwright_fn=pw_fn,
                      user_data_dir=user_data_dir)
        ok2, msg2 = drv2.launch()
        if ok2:
            return drv2, BACKEND_CDP, msg2
        cdp_msg = msg2
    else:
        pw_msg = "Playwright install kora nei."
        cdp_msg = "Playwright chara CDP-o cholbe na."

    pag = pyautogui_mod if pyautogui_mod is not None else _load_pyautogui()
    if pag is not None:
        drv3 = Driver(BACKEND_PYAUTOGUI, pyautogui_mod=pag,
                      user_data_dir=user_data_dir)
        ok3, msg3 = drv3.launch()
        if ok3:
            # Honest: this backend cannot run the flows — it has no DOM.
            return drv3, BACKEND_PYAUTOGUI, msg3

    return None, "", (
        "Chrome driver ready noy — Playwright install korte hobe. "
        f"(Playwright: {pw_msg} CDP: {cdp_msg} "
        "pyautogui-o pelam na.) PC-te `pip install playwright` chalao, "
        "tarpor abar try koro.")
