"""
core/mouse_control.py — move/click/type with the mouse like a human.

pyautogui (already in requirements.txt, automation section) does the work.
Every function returns (ok, message) and never raises, so a tool call on a
worker thread can hand the result straight to the user. No Qt anywhere —
tools run on worker threads (see AGENTS.md).

Safety:
  * pyautogui.FAILSAFE is on — slamming the mouse into the top-left corner
    (0, 0) aborts any move, the standard pyautogui escape hatch.
  * Coordinates outside the screen are refused, never clamped silently:
    clicking the wrong pixel is worse than doing nothing.
  * pyautogui is imported lazily, so importing this module never fails on a
    machine where it is not installed yet — the caller gets a plain-words
    "install koro" message instead of an ImportError.

Honest limits:
  * The PC must be unlocked and the app you want to click must be in focus —
    no program can click through a lock screen.
  * type_text types into whatever window has focus; check focus first.
"""
from __future__ import annotations

import os
import tempfile
import time

_pyautogui = None          # cached module once imported
_pyautogui_failed = False  # True once an import has failed (don't retry forever)


def _get_pyautogui():
    """The pyautogui module, or None when it is not installed. Never raises."""
    global _pyautogui, _pyautogui_failed
    if _pyautogui is not None:
        return _pyautogui
    if _pyautogui_failed:
        return None
    try:
        import pyautogui as _pg
    except Exception:
        _pyautogui_failed = True
        return None
    try:
        _pg.FAILSAFE = True
    except Exception:
        pass
    _pyautogui = _pg
    return _pyautogui


def _no_pyautogui() -> tuple[bool, str]:
    return (False,
            "pyautogui install kora nei — `pip install pyautogui` dao, "
            "tarpor abar try koro.")


def screen_size() -> tuple[int, int]:
    """(width, height) of the primary screen, (0, 0) when unknown. Never raises."""
    pg = _get_pyautogui()
    if pg is None:
        return (0, 0)
    try:
        w, h = pg.size()
        return (int(w), int(h))
    except Exception:
        return (0, 0)


def _check_xy(x, y) -> str:
    """'' when (x, y) is a usable on-screen point, else why not."""
    try:
        x, y = int(x), int(y)
    except (TypeError, ValueError):
        return "x ar y — duitoi number hote hobe (e.g. x=500, y=300)."
    w, h = screen_size()
    if w <= 0 or h <= 0:
        return "screen-er size pelam na — display on ache kina dekho."
    if x < 0 or y < 0 or x >= w or y >= h:
        return (f"({x}, {y}) screen-er baire — screen {w}x{h}, tai "
                f"x 0-{w - 1} ar y 0-{h - 1}-er moddhe dao.")
    return ""


def _check_button(button: str) -> str:
    b = (button or "").strip().lower()
    if b in ("left", "right", "middle"):
        return ""
    return "button left / right / middle-er ekta hobe."


def move(x, y) -> tuple[bool, str]:
    """Move the mouse to (x, y). Returns (ok, message)."""
    try:
        pg = _get_pyautogui()
        if pg is None:
            return _no_pyautogui()
        bad = _check_xy(x, y)
        if bad:
            return (False, bad)
        pg.moveTo(int(x), int(y), duration=0.25)
        return (True, f"✅ Mouse ({int(x)}, {int(y)})-te nilam.")
    except Exception as e:
        return (False, f"Mouse move korte parlam na: {e}")


def click(x, y, button: str = "left") -> tuple[bool, str]:
    """Click at (x, y) with `button` (left/right/middle). Returns (ok, message)."""
    try:
        pg = _get_pyautogui()
        if pg is None:
            return _no_pyautogui()
        bad = _check_xy(x, y)
        if bad:
            return (False, bad)
        bad = _check_button(button)
        if bad:
            return (False, bad)
        pg.click(int(x), int(y), button=(button or "left").strip().lower())
        return (True, f"✅ ({int(x)}, {int(y)})-te {button} click korlam.")
    except Exception as e:
        return (False, f"Click korte parlam na: {e}")


def double_click(x, y) -> tuple[bool, str]:
    """Double-click at (x, y). Returns (ok, message)."""
    try:
        pg = _get_pyautogui()
        if pg is None:
            return _no_pyautogui()
        bad = _check_xy(x, y)
        if bad:
            return (False, bad)
        pg.doubleClick(int(x), int(y))
        return (True, f"✅ ({int(x)}, {int(y)})-te double-click korlam.")
    except Exception as e:
        return (False, f"Double-click korte parlam na: {e}")


def right_click(x, y) -> tuple[bool, str]:
    """Right-click at (x, y). Returns (ok, message)."""
    try:
        pg = _get_pyautogui()
        if pg is None:
            return _no_pyautogui()
        bad = _check_xy(x, y)
        if bad:
            return (False, bad)
        pg.rightClick(int(x), int(y))
        return (True, f"✅ ({int(x)}, {int(y)})-te right-click korlam.")
    except Exception as e:
        return (False, f"Right-click korte parlam na: {e}")


def type_text(text) -> tuple[bool, str]:
    """Type `text` into the focused window, like a human typing.
    Returns (ok, message)."""
    try:
        pg = _get_pyautogui()
        if pg is None:
            return _no_pyautogui()
        text = "" if text is None else str(text)
        if not text:
            return (False, "Ki type korbo — text dao.")
        if len(text) > 10000:
            return (False, "Text-ta onek boro (10,000 character-er beshi) — "
                           "choto kore dao.")
        pg.typewrite(text, interval=0.02)
        shown = text if len(text) <= 80 else text[:77] + "..."
        return (True, f"✅ Type korlam: \"{shown}\"")
    except Exception as e:
        return (False, f"Type korte parlam na: {e}")


def scroll(amount) -> tuple[bool, str]:
    """Scroll the wheel: positive = up, negative = down (pyautogui convention).
    Returns (ok, message)."""
    try:
        pg = _get_pyautogui()
        if pg is None:
            return _no_pyautogui()
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            return (False, "scroll amount number hote hobe (e.g. 3 up, -3 down).")
        if amount == 0:
            return (False, "scroll amount 0 mane kichui hobe na — 3 ba -3 dao.")
        pg.scroll(amount)
        direction = "upore" if amount > 0 else "niche"
        return (True, f"✅ {direction} scroll korlam ({amount}).")
    except Exception as e:
        return (False, f"Scroll korte parlam na: {e}")


def press_key(key) -> tuple[bool, str]:
    """Press one key (e.g. "enter", "esc", "win", "tab", "f5").
    Returns (ok, message). Never raises."""
    try:
        pg = _get_pyautogui()
        if pg is None:
            return _no_pyautogui()
        key = ("" if key is None else str(key)).strip().lower()
        if not key:
            return (False, "Kon key chapbo — key-er naam dao (e.g. enter).")
        pg.press(key)
        return (True, f"✅ \"{key}\" key chaplam.")
    except Exception as e:
        return (False, f"Key chapte parlam na: {e}")


def screenshot(path: str | None = None) -> tuple[bool, str]:
    """Take a screenshot and save it as a PNG.

    `path` given → save there; otherwise a timestamped file in the temp
    folder. Returns (True, path + size) so the caller can show it with
    player.show_content / the phone screen view. Never raises.
    """
    try:
        pg = _get_pyautogui()
        if pg is None:
            return _no_pyautogui()
        if path:
            path = os.path.expanduser(str(path).strip())
            if not path.lower().endswith(".png"):
                path += ".png"
        else:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            path = os.path.join(tempfile.gettempdir(),
                                f"mark_screenshot_{stamp}.png")
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        img = pg.screenshot()
        img.save(path)
        try:
            w, h = img.size
            size_txt = f"{w}x{h}"
        except Exception:
            size_txt = "size janina"
        return (True, f"✅ Screenshot nilam: {path} ({size_txt})")
    except Exception as e:
        return (False, f"Screenshot nite parlam na: {e}")


def position() -> tuple[bool, str]:
    """Where is the mouse right now? Returns (ok, message)."""
    try:
        pg = _get_pyautogui()
        if pg is None:
            return _no_pyautogui()
        x, y = pg.position()
        return (True, f"Mouse ekhon ({int(x)}, {int(y)})-te ache.")
    except Exception as e:
        return (False, f"Mouse-er position pelam na: {e}")
