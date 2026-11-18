"""plugins/browser_advanced.py — 🌐 BROWSER ADVANCED: form fill + multi-tab.

Advanced direct browser control on top of core/browser_driver.py:
fill a whole form (several fields + submit), open/switch/close/list tabs,
scroll to an element, wait for a selector, screenshot to a file. DOM
backends only (Playwright/CDP) — the pyautogui backend has no DOM and
says so plainly instead of pretending.

Runs on a worker thread. Returns a short string, never raises.
"""
from __future__ import annotations

import json

PLUGIN = {
    "name": "browser_advanced",
    "description": (
        "Advanced direct browser control: fill a whole form (several "
        "fields + submit), sign up / register, login, click by text or "
        "coordinates, fill by field labels, open/switch/close/list tabs, "
        "scroll to an element, wait for a selector, take a screenshot. "
        "MANUAL mode: Mark opens the page and the user clicks while Mark "
        "watches and narrates; 'tumi koro' hands it to Mark (AUTO). Call "
        "when the user asks: form bhorlam, sign up koro, login koro, "
        "notun tab kholo, tab bodlao, tab bondho koro, element-e scroll "
        "koro, screenshot nao."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "'fill_form', 'tabs', 'scroll_to', "
                                      "'wait_for', 'screenshot', 'signup', "
                                      "'login', 'click_text', 'click_coords', "
                                      "'fill_by_label', 'scroll', 'manual' "
                                      "or 'takeover'."},
            "mode": {"type": "STRING",
                     "description": "'auto' (Mark clicks) or 'manual' "
                                    "(user clicks, Mark watches + narrates). "
                                    "Signup/login/manual action-e."},
            "text": {"type": "STRING",
                     "description": "Visible text to click (click_text) or "
                                    "submit button text (signup/login)."},
            "success": {"type": "STRING",
                        "description": "Success marker text (comma-separated) "
                                       "to verify after submit (signup/login/manual)."},
            "x": {"type": "NUMBER",
                  "description": "X coordinate (click_coords)."},
            "y": {"type": "NUMBER",
                  "description": "Y coordinate (click_coords)."},
            "dy": {"type": "NUMBER",
                   "description": "Scroll pixels, down positive (scroll)."},
            "url": {"type": "STRING",
                    "description": "URL (fill_form: page to open)."},
            "fields": {"type": "STRING",
                       "description": "JSON object {selector: text} "
                                      "(fill_form)."},
            "submit": {"type": "STRING",
                       "description": "Submit button selector (fill_form, "
                                      "optional)."},
            "selector": {"type": "STRING",
                         "description": "Selector (scroll_to / wait_for)."},
            "index": {"type": "NUMBER",
                      "description": "Tab index (tabs switch/close)."},
            "tab_op": {"type": "STRING",
                       "description": "'list', 'new', 'switch' or 'close' "
                                      "(tabs action)."},
            "path": {"type": "STRING",
                     "description": "Screenshot file path."},
        },
        "required": [],
    },
}


def _driver():
    from core.browser_driver import ensure_driver
    driver, _backend, msg = ensure_driver()
    return driver, msg


# ── MANUAL mode state ────────────────────────────────────────────────────────
# The watch runs on a daemon thread (plugins must return in seconds);
# _MANUAL holds the pending AUTO flow so "tumi koro" can take over.
import threading as _threading

_MANUAL = {"stop": _threading.Event(), "thread": None,
           "kind": "", "url": "", "fields": {}, "submit": "",
           "success": []}


def _parse_fields(raw):
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _parse_success(raw):
    if isinstance(raw, str):
        return [x.strip() for x in raw.split(",") if x.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def _narrate(player, text):
    try:
        if player is not None:
            player.write_log(f"🌐 {text}")
    except Exception:
        pass
    try:
        if player is not None and hasattr(player, "request_say"):
            player.request_say(text)
    except Exception:
        pass


def _start_manual(kind, url, fields, submit, success, player):
    """Start the MANUAL watch on a daemon thread; return at once."""
    from core import browser_flows as _bf
    _MANUAL["stop"].clear()
    _MANUAL.update({"kind": kind, "url": url, "fields": dict(fields),
                    "submit": submit, "success": list(success)})

    def _watch():
        ok, msg = _bf.run_manual(
            url, tuple(success), narrate_fn=lambda t: _narrate(player, t),
            stop_fn=lambda: _MANUAL["stop"].is_set())
        _narrate(player, msg)
        if player is not None:
            try:
                player.write_log(f"🌐 Manual mode: {msg}")
            except Exception:
                pass

    t = _threading.Thread(target=_watch, daemon=True, name="browser-manual")
    _MANUAL["thread"] = t
    t.start()
    return (f"👀 Manual mode chalu — {url} khullam, tumi click koro, ami "
            f"dekhchi ar bolbo. 'Tumi koro' bolle ami baki-ta korbo.")


def _takeover(player):
    """'Tumi koro' — stop the manual watch, run the pending AUTO flow."""
    from core import browser_flows as _bf
    kind = _MANUAL.get("kind") or ""
    url = _MANUAL.get("url") or ""
    fields = dict(_MANUAL.get("fields") or {})
    submit = _MANUAL.get("submit") or ""
    success = list(_MANUAL.get("success") or [])
    if not kind:
        return "Manual mode chalu nei — age manual-e kono flow shuru koro."
    _MANUAL["stop"].set()
    t = _MANUAL.get("thread")
    if t is not None:
        t.join(timeout=5.0)
    _MANUAL.update({"kind": "", "url": "", "fields": {}, "submit": "",
                    "success": []})
    _narrate(player, "AUTO mode-e nilam — baki step ami korchi.")
    if kind == "signup":
        ok, msg = _bf.signup(url, fields, submit or "Sign up",
                             tuple(success))
    elif kind == "login":
        ok, msg = _bf.login(url, fields, submit or "Log in",
                            tuple(success))
    else:
        ok, msg = _bf.run_manual(url, tuple(success))
    return msg


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Dispatch one advanced browser action. Short string, never raises."""
    try:
        params = parameters or {}
        action = str(params.get("action") or "").strip().lower()
        if action == "fill_form":
            url = str(params.get("url") or "").strip()
            raw_fields = params.get("fields")
            fields = raw_fields if isinstance(raw_fields, dict) else {}
            if isinstance(raw_fields, str) and raw_fields.strip():
                try:
                    parsed = json.loads(raw_fields)
                    fields = parsed if isinstance(parsed, dict) else {}
                except Exception:
                    return "Fields-ta JSON object akare dao — {selector: text}."
            submit = str(params.get("submit") or "").strip() or None
            from core import browser_automation as _ba
            ok, msg = _ba.form_fill(url, fields, submit)
            return msg
        if action == "tabs":
            op = str(params.get("tab_op") or "list").strip().lower()
            if op == "list":
                from core import browser_automation as _ba
                ok, msg = _ba.list_open_tabs()
                return msg
            driver, msg = _driver()
            if driver is None:
                return msg
            try:
                if op == "new":
                    ok, out = driver.new_tab(
                        str(params.get("url") or "").strip() or None)
                    return out
                idx = params.get("index")
                try:
                    idx = int(idx) if idx is not None else 0
                except Exception:
                    return "Tab index-ta number akare dao."
                if op == "switch":
                    ok, out = driver.switch_tab(idx)
                elif op == "close":
                    ok, out = driver.close_tab(idx)
                else:
                    return "tab_op 'list', 'new', 'switch' ba 'close' hote hobe."
                return out
            finally:
                try:
                    driver.close()
                except Exception:
                    pass
        if action == "scroll_to":
            selector = str(params.get("selector") or "").strip()
            if not selector:
                return "Scroll korte selector dao."
            driver, msg = _driver()
            if driver is None:
                return msg
            try:
                ok, out = driver.scroll_to_element(selector)
                return out
            finally:
                try:
                    driver.close()
                except Exception:
                    pass
        if action == "wait_for":
            selector = str(params.get("selector") or "").strip()
            if not selector:
                return "Wait korte selector dao."
            driver, msg = _driver()
            if driver is None:
                return msg
            try:
                ok, out = driver.wait_for_selector(selector)
                return out
            finally:
                try:
                    driver.close()
                except Exception:
                    pass
        if action == "screenshot":
            path = str(params.get("path") or "").strip()
            if not path:
                return "Screenshot-er path dao."
            driver, msg = _driver()
            if driver is None:
                return msg
            try:
                ok, out = driver.screenshot(path)
                return out
            finally:
                try:
                    driver.close()
                except Exception:
                    pass
        if action in ("signup", "login"):
            from core import browser_flows as _bf
            url = str(params.get("url") or "").strip()
            fields = _parse_fields(params.get("fields"))
            submit = str(params.get("text") or "").strip() or (
                "Sign up" if action == "signup" else "Log in")
            success = _parse_success(params.get("success"))
            mode = str(params.get("mode") or "auto").strip().lower()
            if not url:
                return "Sign-up/login-er jonno URL dao."
            if not fields:
                return "Form bhorar jonno field dao — {label: value} JSON."
            if mode == "manual":
                return _start_manual(action, url, fields, submit, success,
                                     player)
            if action == "signup":
                ok, msg = _bf.signup(url, fields, submit, tuple(success))
            else:
                ok, msg = _bf.login(url, fields, submit, tuple(success))
            return msg
        if action == "click_text":
            text = str(params.get("text") or "").strip()
            if not text:
                return "Click korte text dao."
            driver, msg = _driver()
            if driver is None:
                return msg
            try:
                from core.browser_automation import run_steps as _rs
                ok, out = _rs([{"label": f"'{text}' click",
                                "action": "click_text", "text": text}], driver)
                return out
            finally:
                try:
                    driver.close()
                except Exception:
                    pass
        if action == "click_coords":
            try:
                x = int(params.get("x") or 0)
                y = int(params.get("y") or 0)
            except Exception:
                return "Click korte x + y number akare dao."
            driver, msg = _driver()
            if driver is None:
                return msg
            try:
                from core.browser_automation import run_steps as _rs
                ok, out = _rs([{"label": f"Click ({x}, {y})",
                                "action": "click_coords", "x": x, "y": y}],
                              driver)
                return out
            finally:
                try:
                    driver.close()
                except Exception:
                    pass
        if action == "fill_by_label":
            url = str(params.get("url") or "").strip()
            fields = _parse_fields(params.get("fields"))
            if not fields:
                return "Form bhorar jonno field dao — {label: value} JSON."
            driver, msg = _driver()
            if driver is None:
                return msg
            try:
                from core.browser_automation import run_steps as _rs
                steps = []
                if url:
                    steps.append({"label": "Page khola", "action": "navigate",
                                  "url": url})
                steps.append({"label": "Form bhorlam (label diye)",
                              "action": "fill_by_label", "fields": fields})
                ok, out = _rs(steps, driver)
                return out
            finally:
                try:
                    driver.close()
                except Exception:
                    pass
        if action == "scroll":
            try:
                dy = int(params.get("dy") or 500)
            except Exception:
                return "Scroll korte dy number akare dao."
            driver, msg = _driver()
            if driver is None:
                return msg
            try:
                from core.browser_automation import run_steps as _rs
                ok, out = _rs([{"label": f"Scroll {dy}px",
                                "action": "scroll", "dy": dy}], driver)
                return out
            finally:
                try:
                    driver.close()
                except Exception:
                    pass
        if action == "manual":
            url = str(params.get("url") or "").strip()
            success = _parse_success(params.get("success"))
            if not url:
                return "Manual mode-er jonno URL dao."
            return _start_manual("watch", url, {}, "", success, player)
        if action == "takeover":
            return _takeover(player)
        return ("Browser advanced — action dao: 'fill_form', 'tabs', "
                "'scroll_to', 'wait_for', 'screenshot', 'signup', 'login', "
                "'click_text', 'click_coords', 'fill_by_label', 'scroll', "
                "'manual' ba 'takeover'.")
    except Exception as e:
        return f"Browser advanced korte parlam na: {e}"
