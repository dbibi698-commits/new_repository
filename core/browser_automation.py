"""core/browser_automation.py — GitHub repo create + Render deploy flows.

Runs ON TOP of core/browser_driver.py (no-extension Playwright/CDP driver).
Nothing in this module touches the Chrome extension, the dashboard
browser-command queue, or any API token: the flows drive the user's own
logged-in Chrome exactly the way a person would — navigate, fill, click,
read the page back.

Step runner
-----------
``run_steps(steps, driver)`` executes one step at a time. A step is a dict::

    {"label": "Repo name bhorlam",              # human name, used in errors
     "action": "navigate" | "click" | "fill" | "read" | "wait" | "wait_for",
     "selectors": ["#repository_name", ...],    # tried in order, first win
     "selector": "#repository_name",            # same as a 1-item list
     "url": "https://github.com/new",           # navigate
     "text": "my-repo",                         # fill / click text=
     "wait_s": 2,                               # wait action
     "verify": {"url_contains": "...", "url_regex": "...",
                "text_contains": "...", "text_regex": "..."},
     "optional": True}                          # failure is skipped, not fatal

Verification reads the page back (``read_text`` / ``current_url``) and
checks the conditions. The first failing step stops the run and the returned
message names that step and what was actually seen — never a bare traceback.

Flows return ``(ok, message)`` and never raise. ``message`` is a short
plain-words sentence: success carries the new URL, failure names the step.
"""
from __future__ import annotations

import re

from core.browser_driver import Driver, ensure_driver

_GITHUB_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_RENDER_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_GITHUB_URL_RE = re.compile(r"^https://github\.com/([^/]+)/([^/\s?#]+)/?$")
_ONRENDER_URL_RE = re.compile(r"https://[a-z0-9-]+\.onrender\.com")

# ── selector tables (data, not code) ─────────────────────────────────────────
# Playwright selectors: CSS, ``text=...``, ``button:has-text('...')``.
# First entry is the preferred one; the rest are fallbacks, tried in order.

GITHUB_NEW_REPO_STEPS = "github_new_repo"  # flow name, kept for logs/tests

GITHUB_SELECTORS = {
    # github.com/new — the repo-name input. id is stable; name= is the fallback.
    "repo_name": ["#repository_name", "input[name='repository_name']"],
    # Description input on the same form.
    "repo_desc": ["#repository_description",
                  "input[name='repository_description']"],
    # Visibility radios (GitHub's own ids) + their <label>s as fallback.
    "visibility_public": ["#repository_visibility_public",
                          "label[for='repository_visibility_public']",
                          "text=Public"],
    "visibility_private": ["#repository_visibility_private",
                           "label[for='repository_visibility_private']",
                           "text=Private"],
    # "Create repository" submit button.
    "create_button": ["button:has-text('Create repository')",
                      "text=Create repository",
                      "form button[type='submit']"],
}

RENDER_SELECTORS = {
    # Top-right "New +" button on dashboard.render.com.
    "new_button": ["text=New +", "button:has-text('New')",
                   "[aria-label*='New']"],
    # The "Web Service" entry in the New menu.
    "web_service": ["text=Web Service", "a:has-text('Web Service')",
                    "button:has-text('Web Service')"],
    # The repo row in "Build and deploy from a Git repository". Filled in
    # per-run with the actual repo name (see render_steps()).
    #   "repo_row": ["text=<repo>", "text=<owner>/<repo>"]
    # "Connect" next to a repo that is not connected yet (optional step).
    "connect_button": ["button:has-text('Connect')", "text=Connect"],
    # New-web-service form: service name + branch.
    "service_name": ["input[name='serviceName']", "input[name='name']",
                     "#service-name"],
    "branch": ["input[name='branch']", "input[value='main']"],
    # Final submit.
    "create_service": ["button:has-text('Create Web Service')",
                       "text=Create Web Service",
                       "form button[type='submit']"],
}


# ── step runner ──────────────────────────────────────────────────────────────

def _step_selectors(step: dict) -> list[str]:
    sels = step.get("selectors")
    if sels:
        return [str(s) for s in sels if str(s).strip()]
    one = str(step.get("selector") or "").strip()
    return [one] if one else []


def _check_verify(driver: Driver, verify: dict) -> tuple[bool, str]:
    """Check verify conditions against the live page. Returns (ok, seen)."""
    url = driver.current_url()
    ok, text = driver.read_text()
    text = text if ok else ""
    seen = f"URL: {url or '(khali)'} | page: {(text or '')[:200].strip()}"
    if verify.get("url_contains") and verify["url_contains"] not in url:
        return False, seen
    if verify.get("url_regex"):
        try:
            if not re.search(verify["url_regex"], url or ""):
                return False, seen
        except re.error:
            return False, seen
    if verify.get("text_contains"):
        needle = str(verify["text_contains"]).lower()
        if needle not in (text or "").lower():
            return False, seen
    if verify.get("text_regex"):
        try:
            if not re.search(verify["text_regex"], text or "",
                             re.IGNORECASE):
                return False, seen
        except re.error:
            return False, seen
    if verify.get("text_not_contains"):
        needle = str(verify["text_not_contains"]).lower()
        if needle in (text or "").lower():
            return False, seen
    return True, seen


def run_steps(steps: list[dict], driver: Driver,
              trace: list[dict] | None = None) -> tuple[bool, str]:
    """Run steps in order on an already-launched driver.

    Returns ``(ok, message)`` and never raises. ``trace`` (when given) is
    filled with one record per step: label, action, selector actually used,
    ok, and the error/seen text.
    """
    if driver is None:
        return False, "Browser driver ready noy — Playwright install korte hobe."
    if not getattr(driver, "dom_capable", False):
        return False, ("Browser driver ready noy — pyautogui backend diye "
                       "form fill kora jay na. Playwright install kore "
                       "Chrome bondho kore abar try koro.")
    for i, step in enumerate(steps or [], start=1):
        label = str(step.get("label") or step.get("action") or f"step {i}")
        action = str(step.get("action") or "").strip().lower()
        optional = bool(step.get("optional"))
        record = {"step": i, "label": label, "action": action,
                  "selector_used": "", "ok": False, "error": ""}
        if trace is not None:
            trace.append(record)
        ok, msg = True, ""
        used = ""
        try:
            if action == "navigate":
                ok, msg = driver.navigate(str(step.get("url") or ""))
            elif action == "wait":
                ok, msg = driver.wait(float(step.get("wait_s") or 2))
            elif action == "wait_for":
                ok, msg = False, "wait_for-e selector dao."
                for sel in _step_selectors(step):
                    ok, msg = driver.wait_for_selector(
                        sel, int(step.get("timeout_ms") or 15000))
                    if ok:
                        used = sel
                        break
            elif action in ("click", "fill"):
                sels = _step_selectors(step)
                if not sels:
                    ok, msg = False, f"{action}-e selector dao."
                else:
                    last_err = ""
                    for sel in sels:
                        if action == "click":
                            ok, msg = driver.click(sel)
                        else:
                            ok, msg = driver.fill(sel, str(step.get("text") or ""))
                        if ok:
                            used = sel
                            break
                        last_err = msg
                    if not ok:
                        msg = last_err or msg
            elif action == "read":
                ok, msg = driver.read_text(step.get("selector") or None)
                msg = (msg[:400] if ok else msg)
            elif action == "fill_form":
                # fields: {selector: text}; submit: selector (optional).
                fields = step.get("fields") or {}
                if not isinstance(fields, dict) or not fields:
                    ok, msg = False, "fill_form-e fields dao."
                else:
                    ok, msg = driver.fill_form(
                        fields, step.get("submit") or None)
            elif action == "type":
                sels = _step_selectors(step)
                if not sels:
                    ok, msg = False, "type-e selector dao."
                else:
                    last_err = ""
                    for sel in sels:
                        ok, msg = driver.type_text(sel, str(step.get("text") or ""))
                        if ok:
                            used = sel
                            break
                        last_err = msg
                    if not ok:
                        msg = last_err or msg
            elif action == "play":
                sel = str(step.get("selector") or "").strip() or None
                ok, msg = driver.play_video(sel)
            elif action == "key":
                ok, msg = driver.press_key(str(step.get("key") or ""))
            elif action == "set_file":
                sel = str(step.get("selector") or "").strip()
                path = str(step.get("path") or "").strip()
                if not sel or not path:
                    ok, msg = False, "set_file-e selector + path dao."
                else:
                    ok, msg = driver.set_input_files(sel, path)
            elif action == "new_tab":
                ok, msg = driver.new_tab(str(step.get("url") or "") or None)
            elif action == "switch_tab":
                try:
                    ok, msg = driver.switch_tab(int(step.get("index") or 0))
                except Exception:
                    ok, msg = False, "switch_tab-e index dao (number)."
            elif action == "close_tab":
                idx = step.get("index")
                try:
                    ok, msg = driver.close_tab(
                        None if idx is None else int(idx))
                except Exception:
                    ok, msg = False, "close_tab-e index dao (number)."
            elif action == "scroll_to":
                ok, msg = driver.scroll_to_element(
                    str(step.get("selector") or ""))
            elif action == "screenshot":
                ok, msg = driver.screenshot(
                    str(step.get("path") or "browser-shot.png"))
            else:
                ok, msg = False, f"Unknown step action: {action}"
        except Exception as e:  # a driver bug must not escape as a crash
            ok, msg = False, f"Driver error: {e}"
        record["selector_used"] = used
        record["ok"] = bool(ok)
        if not ok:
            record["error"] = msg
            if optional:
                continue
            return False, (f"Step {i} ({label}) fail holo — {msg}")
        verify = step.get("verify") or {}
        if verify:
            vok, seen = _check_verify(driver, verify)
            record["ok"] = bool(vok)
            if not vok:
                record["error"] = seen
                if optional:
                    continue
                return False, (f"Step {i} ({label})-er pore page-ta asha "
                               f"moto pelam na — {seen}")
            record["error"] = ""
        else:
            record["error"] = ""
    return True, "Shob step hoye gelo."


# ── GitHub: create a repository ──────────────────────────────────────────────

def github_steps(name: str, description: str = "",
                 private: bool = False) -> list[dict]:
    """The step list for github_new_repo (data — tests assert on this)."""
    steps: list[dict] = [
        {"label": "GitHub new-repo page khola", "action": "navigate",
         "url": "https://github.com/new",
         "verify": {"url_contains": "github.com/new"}},
        {"label": "Repo-name field asha", "action": "wait_for",
         "selectors": GITHUB_SELECTORS["repo_name"], "timeout_ms": 20000},
        {"label": "Repo name bhorlam", "action": "fill",
         "selectors": GITHUB_SELECTORS["repo_name"], "text": name},
    ]
    if (description or "").strip():
        steps.append(
            {"label": "Description bhorlam", "action": "fill",
             "selectors": GITHUB_SELECTORS["repo_desc"],
             "text": (description or "").strip()})
    steps.append(
        {"label": "Private korlam" if private else "Public korlam",
         "action": "click",
         "selectors": GITHUB_SELECTORS["visibility_private" if private
                                       else "visibility_public"]})
    steps.append(
        {"label": "Create repository chaplam", "action": "click",
         "selectors": GITHUB_SELECTORS["create_button"]})
    steps.append(
        {"label": "Notun repo page asha", "action": "wait", "wait_s": 3,
         "verify": {"url_regex": r"^https://github\.com/[^/]+/" +
                    re.escape(name.lower()) + r"/?$"}})
    return steps


def github_new_repo(name: str, description: str = "", private: bool = False,
                    driver: Driver | None = None) -> tuple[bool, str]:
    """Create a GitHub repo in the user's logged-in Chrome. No token, no API.

    Returns ``(ok, message)`` — success carries the repo URL.
    Never raises. ``driver`` is injectable for tests; when None, the best
    available driver is picked (Playwright → CDP → pyautogui).
    """
    try:
        name = (name or "").strip()
        description = (description or "").strip()
        if not name:
            return False, "Repo-r naam dao."
        if len(name) > 100:
            return False, "Repo-r naam 100 character-er beshi hote pare na."
        if not _GITHUB_NAME_RE.match(name):
            return False, ("Repo-r naam-e sudhu letter, number, hyphen (-), "
                           "underscore (_) ar dot (.) cholbe — space na.")
        if len(description) > 350:
            return False, "Description 350 character-er beshi hote pare na."
        own_driver = False
        if driver is None:
            driver, _backend, msg = ensure_driver()
            if driver is None:
                return False, msg
            own_driver = True
        try:
            trace: list[dict] = []
            ok, msg = run_steps(github_steps(name, description, private),
                                driver, trace=trace)
            if not ok:
                # Still on /new means GitHub rejected the form (name taken,
                # validation error) — say so in plain words.
                if "github.com/new" in driver.current_url():
                    ok2, page = driver.read_text()
                    hint = ""
                    if ok2:
                        low = page.lower()
                        if "already exists" in low or "name is already taken" in low:
                            hint = " — ei naam-e repo already ache."
                        elif "sign in" in low:
                            hint = " — GitHub-e login kora nei Chrome-e."
                    return False, (msg + hint +
                                   " GitHub form-ta reject korlo; naam-ta "
                                   "bodle abar try koro.")
                return False, msg
            url = driver.current_url()
            m = _GITHUB_URL_RE.match(url or "")
            if not m:
                return False, (f"Repo banalam kintu URL-ta milche na "
                               f"({url or 'khali'}) — github.com-e giye dekho.")
            repo_url = f"https://github.com/{m.group(1)}/{m.group(2)}"
            return True, f"✅ Repo banalam: {repo_url}"
        finally:
            if own_driver:
                try:
                    driver.close()
                except Exception:
                    pass
    except Exception as e:
        return False, f"Repo banate parlam na: {e}"


# ── Advanced: form fill + tabs (advanced round) ─────────────────────────────

def form_fill(url: str, fields: dict, submit: str | None = None,
              driver: Driver | None = None) -> tuple[bool, str]:
    """Open a URL and fill a form, optionally submitting it. `fields` is
    {selector: text}. Returns ``(ok, message)`` — success carries the URL
    after the submit. Never raises. ``driver`` is injectable for tests."""
    try:
        url = (url or "").strip()
        if not url:
            return False, "Form bhorar jonno URL dao."
        if not isinstance(fields, dict) or not fields:
            return False, "Form bhorar jonno field dao — {selector: text}."
        own_driver = False
        if driver is None:
            driver, _backend, msg = ensure_driver()
            if driver is None:
                return False, msg
            own_driver = True
        try:
            ok, msg = driver.navigate(url)
            if not ok:
                return False, msg
            ok, msg = driver.fill_form(fields, submit)
            if not ok:
                return False, msg
            after = driver.current_url()
            return True, (f"✅ Form bhorlam: {msg} "
                          f"(ekhon: {after or url})")
        finally:
            if own_driver:
                try:
                    driver.close()
                except Exception:
                    pass
    except Exception as e:
        return False, f"Form bhorte parlam na: {e}"


def list_open_tabs(driver: Driver | None = None) -> tuple[bool, str]:
    """One-line summary of the open tabs (for chat / cards)."""
    try:
        own_driver = False
        if driver is None:
            driver, _backend, msg = ensure_driver()
            if driver is None:
                return False, msg
            own_driver = True
        try:
            ok, tabs = driver.list_tabs()
            if not ok:
                return False, "Tab-er list pelam na — driver ready noy."
            if not tabs:
                return True, "Kono tab khula nei."
            lines = [f"🌐 {len(tabs)} ta tab khula:"]
            for t in tabs:
                mark = "▶️ " if t.get("current") else "   "
                lines.append(f"{mark}[{t['index']}] "
                             f"{t.get('title') or '(no title)'} — "
                             f"{t.get('url') or ''}")
            return True, "\n".join(lines)
        finally:
            if own_driver:
                try:
                    driver.close()
                except Exception:
                    pass
    except Exception as e:
        return False, f"Tab-er list dekhte parlam na: {e}"

# ── Render: deploy a web service ─────────────────────────────────────────────

def _repo_short_name(repo_url: str) -> str:
    """owner/repo -> repo (what Render's repo list shows)."""
    parts = (repo_url or "").strip().rstrip("/").split("/")
    return parts[-1] if parts else ""


def render_steps(service_name: str, repo_url: str,
                 branch: str = "main") -> list[dict]:
    """The step list for render_deploy (data — tests assert on this)."""
    repo = _repo_short_name(repo_url)
    owner_repo = (repo_url or "").strip().rstrip("/").replace(
        "https://github.com/", "")
    steps: list[dict] = [
        {"label": "Render dashboard khola", "action": "navigate",
         "url": "https://dashboard.render.com",
         "verify": {"url_contains": "dashboard.render.com"}},
        {"label": "Repo list asha", "action": "wait", "wait_s": 3},
        {"label": "New button chaplam", "action": "click",
         "selectors": RENDER_SELECTORS["new_button"]},
        {"label": "Web Service bechlam", "action": "click",
         "selectors": RENDER_SELECTORS["web_service"]},
        {"label": f"Repo {repo} bechlam", "action": "click",
         "selectors": [f"text={repo}", f"text={owner_repo}",
                       f"text={repo_url}"]},
        {"label": "Connect chaplam (jodi lage)", "action": "click",
         "selectors": RENDER_SELECTORS["connect_button"], "optional": True},
        {"label": "Service name bhorlam", "action": "fill",
         "selectors": RENDER_SELECTORS["service_name"], "text": service_name},
    ]
    if (branch or "main") != "main":
        steps.append(
            {"label": "Branch bhorlam", "action": "fill",
             "selectors": RENDER_SELECTORS["branch"], "text": branch})
    steps.extend([
        {"label": "Create Web Service chaplam", "action": "click",
         "selectors": RENDER_SELECTORS["create_service"]},
        {"label": "Deploy shuru holo kina dekha", "action": "wait",
         "wait_s": 5,
         "verify": {"url_regex": r"dashboard\.render\.com/web/srv-"}},
    ])
    return steps


def render_deploy(service_name: str, repo_url: str, branch: str = "main",
                  driver: Driver | None = None) -> tuple[bool, str]:
    """Deploy a web service on Render in the user's logged-in Chrome.

    No API key, no token — the dashboard is driven like a person. Returns
    ``(ok, message)`` — success carries the ``*.onrender.com`` service URL.
    Never raises.
    """
    try:
        service_name = (service_name or "").strip().lower()
        repo_url = (repo_url or "").strip()
        branch = (branch or "main").strip() or "main"
        if not service_name:
            return False, "Service-er naam dao."
        if not _RENDER_NAME_RE.match(service_name):
            return False, ("Service naam-e sudhu chhoto-hat-er letter, "
                           "number ar hyphen (-) cholbe, hyphen diye shuru/"
                           "shesh na.")
        if not repo_url.startswith("https://github.com/") or \
                len(repo_url.rstrip("/").split("/")) < 5:
            return False, ("Repo URL-ta github.com-er hote hobe — "
                           "e.g. https://github.com/owner/repo")
        own_driver = False
        if driver is None:
            driver, _backend, msg = ensure_driver()
            if driver is None:
                return False, msg
            own_driver = True
        try:
            trace: list[dict] = []
            ok, msg = run_steps(render_steps(service_name, repo_url, branch),
                                driver, trace=trace)
            if not ok:
                url = driver.current_url()
                if "render.com/login" in url or "render.com/sign" in url:
                    return False, (msg + " — Render-e login kora nei "
                                   "Chrome-e; age login koro.")
                return False, msg
            ok2, page = driver.read_text()
            found = _ONRENDER_URL_RE.search(page or "") if ok2 else None
            if found:
                return True, (f"✅ Deploy shuru holo: {found.group(0)} "
                              f"(dashboard-e progress dekhbe — prothom "
                              f"deploy-e koyek minute lagte pare.)")
            return True, ("✅ Deploy shuru holo — service URL ekhono page-e "
                          "dekhachhe na, dashboard.render.com-e giye "
                          "service-ta kholo.")
        finally:
            if own_driver:
                try:
                    driver.close()
                except Exception:
                    pass
    except Exception as e:
        return False, f"Render deploy korte parlam na: {e}"


# ── Advanced Browser Control: login wall + human steps ───────────────────────
_LOGIN_WALL_MARKERS = ("log in", "sign in", "login", "sign up", "create account",
                       "continue with google", "continue with facebook",
                       "enter your password", "forgot password", "otp",
                       "verify your identity", "two-step verification")


def login_wall_detected(text: str | None) -> bool:
    """True when page text looks like a login wall (not logged in)."""
    if not text:
        return False
    low = text.lower()
    return any(m in low for m in _LOGIN_WALL_MARKERS)


def login_status_text(driver, site_name: str = "") -> str:
    """One-line login status for the current page (honest when unknown)."""
    try:
        ok, page = driver.read_text()
        if not ok:
            return "🔒 Login status jana gelo na (page pora gelo na)."
        if login_wall_detected(page):
            return (f"🔒 {site_name or 'Ei site'}-e login kora nei — Chrome-e "
                    "age login koro.")
        return f"✅ {site_name or 'Site'}-e login ache mone hochhe."
    except Exception:
        return "🔒 Login status jana gelo na."


def run_human_actions(actions, driver=None, report_fn=None):
    """Run a list of step dicts one by one, reporting EVERY step live
    through report_fn (or printing) — so the user sees
    "step 1/5 khullam ✅ ... step 3/5 click korlam ❌".

    Actions use the same step dicts as run_steps (label, action, url,
    selectors/selector, text, wait_s, verify, key, ...). Returns
    (ok, message) where the message is the full step report.
    """
    from core import browser_driver as _drv
    own_driver = False
    if driver is None:
        driver, _backend, msg = _drv.ensure_driver()
        if driver is None:
            return False, msg
        own_driver = True
    report = []
    def _say(text):
        report.append(text)
        if report_fn is not None:
            try:
                report_fn(text)
            except Exception:
                pass
    try:
        total = len(actions)
        for i, step in enumerate(actions, start=1):
            label = step.get("label") or step.get("action") or f"step {i}"
            trace: list[dict] = []
            ok, msg = run_steps([step], driver, trace=trace)
            mark = "✅" if ok else "❌"
            _say(f"Step {i}/{total}: {label} {mark} — {msg}")
            if not ok:
                _say(f"Step {i}-e theme gelam ({label}) — page-ta khola "
                     "achhe, tumi hate kore nite paro.")
                return False, "\n".join(report)
        _say(f"✅ Sob {total}-ta step shesh holo.")
        return True, "\n".join(report)
    finally:
        if own_driver:
            try:
                driver.close()
            except Exception:
                pass
