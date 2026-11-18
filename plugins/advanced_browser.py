"""plugins/advanced_browser.py — Advanced Browser Control tool + settings widget.

Direct driver (Playwright channel="chrome" first, CDP fallback,
pyautogui last resort — zero browser helper calls). Runs human-like actions step
by step — open / click / type / fill / scroll / play / upload / multi-tab /
wait / screenshot — verifying the page actually changed after EVERY action
and reporting the exact failed step live. Login = the user's own Chrome
profile; Mark never sees or stores a site password. NO order/booking flow
lives here (standing rule).
"""

PLUGIN = {
    "name": "advanced_browser",
    "description": ("Advanced Browser Control: Chrome-e manusher moto kholo, "
                    "click, type, form fill, scroll, video play, upload, "
                    "multi-tab — prottek step verify kore."),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": ("status | open | steps | login_status | "
                                "screenshot"),
            },
            "url": {"type": "STRING",
                    "description": "open korar URL (action=open)."},
            "site": {"type": "STRING",
                     "description": "login_status-er jonno site-er naam."},
            "steps": {
                "type": "ARRAY",
                "description": ("Step dict-er list (action=steps): prottek-ta "
                                "{label, action, url/selector/selectors/text/"
                                "key/wait_s, verify{...}}."),
            },
        },
    },
}

PLUGIN_SETTINGS = {
    "namespace": "advanced_browser",
    "title": "🌐 ADVANCED BROWSER CONTROL — no browser helper, manusher moto",
    "widget": "advanced_browser",
    "fields": [],
}

_ACTIONS = ("navigate", "click", "fill", "type", "scroll", "scroll_to",
            "play", "key", "wait", "wait_for", "set_file", "screenshot",
            "new_tab", "switch_tab", "close_tab", "read")


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        parameters = parameters or {}
        action = str(parameters.get("action") or "status").strip().lower()
        if action == "status":
            from core import browser_driver as _drv
            chrome = _drv.find_chrome_exe()
            lines = ["🌐 Advanced Browser Control:"]
            lines.append(("✅ Chrome pelam." if chrome
                          else "❌ Chrome install pelam na ei PC-te."))
            lines.append("  • Actions: " + ", ".join(_ACTIONS))
            lines.append("  • Prottek step-er pore page verify hoy; fail "
                         "hole step-er naam bolei theme jay.")
            lines.append("  • Login: tomar nijer Chrome profile — ami "
                         "password dekhi na, rakhi na.")
            return "\n".join(lines)
        if action == "open":
            url = str(parameters.get("url") or "").strip()
            if not url:
                return "Kon site khulbo? URL dao."
            from core import browser_automation as _ba
            ok, msg = _ba.run_human_actions(
                [{"label": f"Khullam {url}", "action": "navigate",
                  "url": url}])
            return msg
        if action == "login_status":
            from core import browser_driver as _drv
            from core import browser_automation as _ba
            driver, _backend, msg = _drv.ensure_driver()
            if driver is None:
                return msg
            try:
                return _ba.login_status_text(
                    driver, str(parameters.get("site") or ""))
            finally:
                try:
                    driver.close()
                except Exception:
                    pass
        if action == "steps":
            steps = parameters.get("steps") or []
            if not isinstance(steps, list) or not steps:
                return "Step-er list dao — prottek-ta {label, action, ...}."
            from core import browser_automation as _ba
            report_fn = player.write_log if player is not None else None
            ok, msg = _ba.run_human_actions(steps, report_fn=report_fn)
            return msg
        if action == "screenshot":
            from core import browser_driver as _drv
            driver, _backend, msg = _drv.ensure_driver()
            if driver is None:
                return msg
            try:
                ok, path = driver.screenshot()
                return (f"📸 Screenshot: {path}" if ok
                        else f"Screenshot nite parlam na: {path}")
            finally:
                try:
                    driver.close()
                except Exception:
                    pass
        return (f"Advanced Browser Control: '{action}' jani na — "
                "status / open / steps / login_status / screenshot.")
    except Exception as e:
        return f"Advanced Browser Control korte parlam na: {e}"
