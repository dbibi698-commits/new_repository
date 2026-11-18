"""plugins/browser_setup.py — 🧪 BROWSER SETUP WIZARD + Playwright sample.

Voice path for core/browser_setup.py. The FULL Playwright process the
user asked for, shown and runnable inside Mark:

  1. System Python check (python --version) — Mark-er bundled Python na.
  2. One click: pip install playwright.
  3. One click: playwright install (browser download ~150 MB).
  4. Verify: Playwright diye browser launch hoy kina.
  5. Sample code (samples/browser_sample.py): browser kholo -> URL-e jao
     -> selector diye click koro -> screenshot -> bondho. "Run sample"
     chalale asol code-ta asol system Python diye chole; URL/selector
     bodlano jay; "Copy code" diye code-ta copy kora jay.

Slow work runs on a background thread: run() returns in seconds,
progress is reported live in the activity log. Never raises. Internet
lagbe pip + browser download-er jonno; system Python lagbe (Mark-er
bundled Python diye tomar script cholbe na).
"""
from __future__ import annotations

import threading

PLUGIN = {
    "name": "browser_setup",
    "description": (
        "Set up Playwright on this PC step by step AND run a real sample: "
        "1) check the system Python (python --version), 2) pip install "
        "playwright, 3) playwright install (browser download ~150 MB), "
        "4) verify Playwright can launch a browser, 5) run the shipped "
        "sample code (samples/browser_sample.py) — it opens the browser, "
        "goes to a URL, clicks an element by selector, screenshots and "
        "closes. Actions: 'check', 'pip_install', 'playwright_install', "
        "'verify', 'full_setup' (all steps in order), 'run_sample' "
        "(url + selector optional), 'show_code' (prints the sample code). "
        "Needs internet + a system Python (Mark's bundled Python does not "
        "count). Call when the user asks: Playwright install koro / "
        "browser setup koro / sample code chalao / full process bolo."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "'check', 'pip_install', "
                                      "'playwright_install', 'verify', "
                                      "'full_setup' (default), 'run_sample', "
                                      "'show_code'."},
            "url": {"type": "STRING",
                    "description": "URL for 'run_sample' "
                                   "(default https://example.com)."},
            "selector": {"type": "STRING",
                         "description": "CSS selector to click in "
                                        "'run_sample' (default 'a')."},
            "browsers": {"type": "STRING",
                         "description": "Browsers for 'playwright_install', "
                                        "comma-separated: chromium, firefox, "
                                        "webkit (default chromium)."},
        },
    },
}

PLUGIN_SETTINGS = {
    "namespace": "browser_setup",
    "title": "🧪 BROWSER SETUP — Playwright full process + sample code",
    "widget": "browser_setup",
    "fields": [],
}


def _log(player, text: str) -> None:
    if player is None:
        return
    try:
        player.write_log(text)
    except Exception:
        pass


def run(parameters: dict, player=None, session_memory=None) -> str:
    try:
        from core import browser_setup as bs
    except Exception as e:
        return f"Browser Setup korte parlam na (core load hoy ni): {e}"
    params = parameters or {}
    action = str(params.get("action") or "full_setup").strip().lower()
    url = str(params.get("url") or "https://example.com").strip()
    selector = str(params.get("selector") or "a").strip()

    if action == "show_code":
        try:
            code = bs.sample_code(url, selector)
        except Exception as e:
            return f"Sample code dekhte parlam na: {e}"
        if player is not None:
            try:
                player.show_content("🧪 Browser sample code", code)
            except Exception:
                pass
        return ("Sample code-ta screen-e dekhacchi — browser kholo, URL-e "
                "jao, selector-e click koro, screenshot nao.")

    if action == "check":
        try:
            res = bs.check_python()
        except Exception as e:
            return f"Python check korte parlam na: {e}"
        return res["message"]

    def _work():
        try:
            if action == "pip_install":
                chk = bs.check_python()
                if not chk["ok"]:
                    _log(player, chk["message"])
                    return
                ok, msg, _o = bs.pip_install_playwright(
                    chk["path"], log_fn=lambda m: _log(player, m))
                _log(player, msg)
            elif action == "playwright_install":
                chk = bs.check_python()
                if not chk["ok"]:
                    _log(player, chk["message"])
                    return
                wanted = [b.strip() for b in
                          str(params.get("browsers") or "chromium").split(",")
                          if b.strip()]
                ok, msg, _o = bs.playwright_install(
                    chk["path"], browsers=tuple(wanted),
                    log_fn=lambda m: _log(player, m))
                _log(player, msg)
            elif action == "verify":
                chk = bs.check_python()
                if not chk["ok"]:
                    _log(player, chk["message"])
                    return
                ok, msg = bs.verify_playwright(chk["path"])
                _log(player, msg)
            elif action == "run_sample":
                chk = bs.check_python()
                if not chk["ok"]:
                    _log(player, chk["message"])
                    return
                ok, msg, _o = bs.run_sample(
                    chk["path"], url, selector,
                    log_fn=lambda m: _log(player, m))
                _log(player, msg)
            else:  # full_setup
                state = bs.run_all_steps(log_fn=lambda m: _log(player, m))
                done = [s for s, v in state.items()
                        if v["status"] == "done"]
                failed = [s for s, v in state.items()
                          if v["status"] == "failed"]
                if failed:
                    _log(player, "❌ Setup thamlo — " +
                         state[failed[0]]["message"])
                else:
                    _log(player, "✅ Browser Setup sesh — 4/4 step done. "
                         "Ebar 'Run sample' chaple sample code cholbe.")
        except Exception as e:
            _log(player, f"Browser Setup-e error: {e}")

    threading.Thread(target=_work, daemon=True,
                     name="browser-setup").start()
    if action == "run_sample":
        return (f"▶ Sample chalacchi ({url} → click {selector!r}) — "
                "output log-e dekhabe.")
    if action == "full_setup":
        return ("🧪 Browser Setup shuru korlam — Python check → pip install "
                "→ browser download → verify. Prottek step log-e dekhabe.")
    return "🧪 Browser Setup-er kaj shuru korlam — log-e dekho."
