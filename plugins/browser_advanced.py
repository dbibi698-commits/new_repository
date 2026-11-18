"""plugins/browser_advanced.py — 🌐 BROWSER ADVANCED: form fill + multi-tab.

Advanced no-extension browser control on top of core/browser_driver.py:
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
        "Advanced browser control (no extension): fill a whole form "
        "(several fields + submit), open/switch/close/list tabs, scroll "
        "to an element, wait for a selector, take a screenshot. Call when "
        "the user asks: form bhorlam, login form bhorlam, notun tab kholo, "
        "tab bodlao, tab bondho koro, element-e scroll koro, screenshot nao."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "'fill_form', 'tabs', 'scroll_to', "
                                      "'wait_for' or 'screenshot'."},
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
        return ("Browser advanced — action dao: 'fill_form', 'tabs', "
                "'scroll_to', 'wait_for' ba 'screenshot'.")
    except Exception as e:
        return f"Browser advanced korte parlam na: {e}"
