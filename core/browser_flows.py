"""core/browser_flows.py — 🌐 Browser control flows: sign up / login,
manual + auto modes, Render Static Site (2026-11-18 add-on).

Built on core/browser_automation.py's step runner + the direct
driver (Playwright channel="chrome" first, CDP fallback, pyautogui
last resort). Every flow verifies the page actually changed and
reports the exact failed step — never a blind click.

Modes:
  * AUTO   — Mark does the clicks itself, step by step.
  * MANUAL — Mark opens the user's own Chrome to the page and the USER
    clicks/types while Mark watches the page and narrates what changed.
    "tumi koro" hands control back to Mark (auto continues the rest);
    "ami korbo" hands it back to the user. The watch loop is
    ``run_manual`` below.

Honest limits (shown in the UI, not hidden):
  * sign up / register / login / deploy / repo create need the user's
    own account + login, already logged in on their Chrome. Mark never
    asks for or stores a site password.
  * a site redesign can break a click flow — Mark says so plainly and
    leaves the page open for the user.
  * Render deploy needs the user's Render account + a connected repo;
    GitHub repo create needs their GitHub login.
"""
from __future__ import annotations

import json
import time

from core.browser_automation import (
    RENDER_SELECTORS,
    ensure_driver,
    run_steps,
)

# ── honest limits (user-visible) ─────────────────────────────────────────────

BROWSER_LIMITS = (
    "Login lagbe: sign up / login / deploy / repo create — tomar nijer "
    "account + Chrome-e login thakte hobe. Mark tomar site-er password "
    "chay na, save-o kore na. Site-er design bodle gele click flow "
    "bhenge jete pare — tokhon Mark page-ta khula rekhe debe, tumi nije "
    "click korte parbe. Render deploy-er jonno tomar Render account + "
    "connected repo lagbe; repo create-er jonno GitHub login lagbe."
)

MODE_AUTO = "auto"
MODE_MANUAL = "manual"

MODE_TEXT = {
    MODE_AUTO: "AUTO — Mark nije click korbe",
    MODE_MANUAL: "MANUAL — tumi click korbe, Mark dekhbe ar bolbe",
}


def mode_text(mode: str) -> str:
    return MODE_TEXT.get((mode or "").strip().lower(), MODE_TEXT[MODE_AUTO])


# ── JS snippets (run through driver.eval_js) ─────────────────────────────────

def click_text_js(text: str) -> str:
    """JS that clicks the first visible clickable element whose text
    contains ``text`` (button, link, or anything with a click handler).
    Returns 'OK:<label>' or 'FAIL:<text>'."""
    needle = json.dumps((text or "").strip().lower())
    return (
        "(function(){"
        " var n = " + needle + ";"
        " if(!n) return 'FAIL:khali text';"
        " var els = document.querySelectorAll('button, a, [role=button], input[type=submit]');"
        " for(var i=0;i<els.length;i++){"
        "  var e=els[i]; var t=(e.innerText||e.value||'').trim().toLowerCase();"
        "  if(t && t.indexOf(n)!==-1 && e.offsetParent!==null){ e.click(); return 'OK:'+t.slice(0,60); }"
        " }"
        " return 'FAIL:'+n; })()"
    )


def fill_by_label_js(fields: dict) -> str:
    """JS that fills inputs found by their LABEL text (or aria-label /
    placeholder / name). ``fields`` is {label: value}. Returns
    'OK:<n>' or 'FAIL:<label>'."""
    pairs = json.dumps([[str(k), str(v)] for k, v in (fields or {}).items()])
    return (
        "(function(){"
        " var pairs = " + pairs + ";"
        " function findInput(label){"
        "  var want = label.trim().toLowerCase();"
        "  var labels = document.querySelectorAll('label');"
        "  for(var i=0;i<labels.length;i++){"
        "   var lb=labels[i];"
        "   if((lb.innerText||'').trim().toLowerCase().indexOf(want)!==-1){"
        "    if(lb.htmlFor){ var el=document.getElementById(lb.htmlFor); if(el) return el; }"
        "    var inner=lb.querySelector('input,textarea,select'); if(inner) return inner;"
        "   }"
        "  }"
        "  var inputs=document.querySelectorAll('input,textarea,select');"
        "  for(var j=0;j<inputs.length;j++){"
        "   var el=inputs[j];"
        "   var hay=((el.getAttribute('aria-label')||'')+' '+(el.getAttribute('placeholder')||'')+' '+(el.name||'')+' '+(el.id||'')).toLowerCase();"
        "   if(hay && hay.indexOf(want)!==-1) return el;"
        "  }"
        "  return null;"
        " }"
        " var done=0;"
        " for(var k=0;k<pairs.length;k++){"
        "  var el=findInput(pairs[k][0]);"
        "  if(!el) return 'FAIL:'+pairs[k][0];"
        "  var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value');"
        "  if(el.tagName==='TEXTAREA') setter=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value');"
        "  if(setter&&setter.set) setter.set.call(el,pairs[k][1]); else el.value=pairs[k][1];"
        "  el.dispatchEvent(new Event('input',{bubbles:true}));"
        "  el.dispatchEvent(new Event('change',{bubbles:true}));"
        "  done++;"
        " }"
        " return 'OK:'+done; })()"
    )


def _eval_ok(driver, js: str) -> tuple[bool, str]:
    """Run JS, expect an 'OK:...' result string."""
    ok, out = driver.eval_js(js)
    if not ok:
        return False, out
    out = (out or "").strip()
    if out.startswith("OK:"):
        return True, out[3:]
    return False, (out[5:] if out.startswith("FAIL:") else (out or "JS theke OK pelam na"))


# ── sign up / register + login ───────────────────────────────────────────────

def signup_steps(url: str, fields: dict, submit_text: str = "Sign up",
                 success_markers: tuple[str, ...] = ()) -> list[dict]:
    """Step list for a registration form. ``fields`` is {label: value}
    (e.g. {"Email": "a@b.com", "Password": "…"}). Success is verified
    by ``success_markers`` (page text after submit) when given."""
    url = (url or "").strip()
    fields = dict(fields or {})
    steps: list[dict] = [
        {"label": "Sign-up page khola", "action": "navigate", "url": url,
         "verify": {"url_contains": url.split("/")[2] if "://" in url else url}},
        {"label": "Form asha", "action": "wait", "wait_s": 3},
        {"label": "Form bhorlam (label diye)", "action": "fill_by_label",
         "fields": fields},
        {"label": f"'{submit_text}' chaplam", "action": "click_text",
         "text": submit_text},
        {"label": "Submit-er pore page dekha", "action": "wait", "wait_s": 4},
    ]
    if success_markers:
        steps[-1]["verify"] = {"text_contains": success_markers[0]}
    return steps


def login_steps(url: str, fields: dict, submit_text: str = "Log in",
                success_markers: tuple[str, ...] = ()) -> list[dict]:
    """Step list for a login form. Same shape as signup_steps; the
    success state is verified by ``success_markers`` when given."""
    steps = signup_steps(url, fields, submit_text=submit_text,
                         success_markers=success_markers)
    steps[0]["label"] = "Login page khola"
    steps[2]["label"] = "Login form bhorlam (label diye)"
    return steps


def _run_flow(steps, driver=None) -> tuple[bool, str]:
    """Run a flow's steps on a driver (own driver when none given)."""
    try:
        own_driver = False
        if driver is None:
            driver, _backend, msg = ensure_driver()
            if driver is None:
                return False, msg
            own_driver = True
        try:
            trace: list[dict] = []
            ok, msg = run_steps(steps, driver, trace=trace)
            if not ok:
                url = ""
                try:
                    url = driver.current_url() or ""
                except Exception:
                    pass
                if url:
                    msg += f" (page khula ache: {url} — tumi nije try korte paro.)"
                return False, msg
            return True, msg
        finally:
            if own_driver:
                try:
                    driver.close()
                except Exception:
                    pass
    except Exception as e:
        return False, f"Flow chalate parlam na: {e}"


def signup(url: str, fields: dict, submit_text: str = "Sign up",
           success_markers: tuple[str, ...] = (),
           driver=None) -> tuple[bool, str]:
    """AUTO sign-up: fill the registration form + submit + verify the
    success state. Never raises. Needs the user's own account details
    in ``fields`` — Mark never stores a password."""
    if not (url or "").strip():
        return False, "Sign-up-er jonno URL dao."
    if not fields:
        return False, "Sign-up form bhorar jonno field dao — {label: value}."
    ok, msg = _run_flow(signup_steps(url, fields, submit_text,
                                     success_markers), driver=driver)
    if not ok:
        return False, msg
    if success_markers:
        return True, (f"✅ Sign up holo mone hochhe — page-e "
                      f"'{success_markers[0]}' dekhlam.")
    return True, ("✅ Sign-up form submit korlam — success message page-e "
                  "check koro (site-er design bodle gele verify korte pari ni).")


def login(url: str, fields: dict, submit_text: str = "Log in",
          success_markers: tuple[str, ...] = (),
          driver=None) -> tuple[bool, str]:
    """AUTO login: fill the login form + submit + verify the logged-in
    state. Never raises. Mark never stores the password."""
    if not (url or "").strip():
        return False, "Login-er jonno URL dao."
    if not fields:
        return False, "Login form bhorar jonno field dao — {label: value}."
    ok, msg = _run_flow(login_steps(url, fields, submit_text,
                                   success_markers), driver=driver)
    if not ok:
        return False, msg
    if success_markers:
        return True, (f"✅ Login holo mone hochhe — page-e "
                      f"'{success_markers[0]}' dekhlam.")
    return True, ("✅ Login form submit korlam — logged-in state page-e "
                  "check koro (site-er design bodle gele verify korte pari ni).")


# ── Render Static Site ───────────────────────────────────────────────────────

def render_static_steps(service_name: str, repo_url: str,
                        branch: str = "main") -> list[dict]:
    """Step list for a Render STATIC SITE deploy (Web Service-er moto,
    sudhu 'Static Site' bechhe)."""
    repo = (repo_url or "").strip().rstrip("/").split("/")[-1]
    owner_repo = (repo_url or "").strip().rstrip("/").replace(
        "https://github.com/", "")
    steps: list[dict] = [
        {"label": "Render dashboard khola", "action": "navigate",
         "url": "https://dashboard.render.com",
         "verify": {"url_contains": "dashboard.render.com"}},
        {"label": "Repo list asha", "action": "wait", "wait_s": 3},
        {"label": "New button chaplam", "action": "click",
         "selectors": RENDER_SELECTORS["new_button"]},
        {"label": "Static Site bechlam", "action": "click",
         "selectors": ["text=Static Site", "a:has-text('Static Site')",
                       "button:has-text('Static Site')"]},
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
        {"label": "Create Static Site chaplam", "action": "click",
         "selectors": ["button:has-text('Create Static Site')",
                       "text=Create Static Site",
                       "form button[type='submit']"]},
        {"label": "Deploy shuru holo kina dekha", "action": "wait",
         "wait_s": 5,
         "verify": {"url_regex": r"dashboard\\.render\\.com/static/srv-"}},
    ])
    return steps


def render_static_deploy(service_name: str, repo_url: str,
                         branch: str = "main",
                         driver=None) -> tuple[bool, str]:
    """Deploy a STATIC SITE on Render in the user's logged-in Chrome.
    Never raises. Needs the user's Render account + connected repo."""
    try:
        service_name = (service_name or "").strip().lower()
        repo_url = (repo_url or "").strip()
        if not service_name:
            return False, "Service-er naam dao."
        if not repo_url.startswith("https://github.com/"):
            return False, ("Repo URL-ta github.com-er hote hobe — "
                           "e.g. https://github.com/owner/repo")
        ok, msg = _run_flow(render_static_steps(service_name, repo_url,
                                                branch), driver=driver)
        if not ok:
            return False, msg
        return True, ("✅ Static Site deploy shuru holo — dashboard.render.com-e "
                      "giue service-ta kholo, prothom deploy-e koyek minute lagte pare.")
    except Exception as e:
        return False, f"Static Site deploy korte parlam na: {e}"


# ── MANUAL mode: watch + narrate while the user clicks ──────────────────────

def run_manual(url: str, success_markers: tuple[str, ...] = (),
               driver=None, narrate_fn=None, stop_fn=None,
               poll_s: float = 3.0, timeout_s: float = 300.0
               ) -> tuple[bool, str]:
    """MANUAL mode: open the URL in the user's Chrome and WATCH while
    the user clicks/types. Narrates (via ``narrate_fn``) when the page
    URL changes or a success marker appears. Returns when a success
    marker is seen, ``stop_fn()`` is True ('tumi koro' — hand over to
    AUTO), or the timeout hits. Never raises; the page stays open.

    ``narrate_fn(text)`` and ``stop_fn()`` are injectable for tests.
    """
    try:
        url = (url or "").strip()
        if not url:
            return False, "Manual mode-er jonno URL dao."
        own_driver = False
        if driver is None:
            driver, _backend, msg = ensure_driver()
            if driver is None:
                return False, msg
            own_driver = True
        say = narrate_fn or (lambda t: None)
        try:
            ok, msg = driver.navigate(url)
            if not ok:
                return False, msg
            say(f"Page khullam: {url} — tumi click koro, ami dekhchi.")
            last_url = driver.current_url() or url
            last_seen = ""
            deadline = time.monotonic() + float(timeout_s)
            while time.monotonic() < deadline:
                if stop_fn is not None and stop_fn():
                    return False, ("Tumi 'tumi koro' bolle — AUTO mode-e "
                                   "baki step ami korbo.")
                cur = ""
                try:
                    cur = driver.current_url() or ""
                except Exception:
                    pass
                if cur and cur != last_url:
                    last_url = cur
                    say(f"Page bodle gelo: {cur}")
                ok2, page = driver.read_text()
                page = page if ok2 else ""
                for marker in (success_markers or ()):
                    if marker and marker.lower() in (page or "").lower():
                        say(f"Success dekhlam: '{marker}'")
                        return True, (f"✅ Manual-e hoye gelo — page-e "
                                      f"'{marker}' dekhlam.")
                snippet = (page or "")[:120].strip()
                if snippet and snippet != last_seen:
                    last_seen = snippet
                    # Only narrate real changes, not every poll.
                    if len(snippet) > 20:
                        say(f"Page-e ekhon: {snippet[:80]}…")
                time.sleep(float(poll_s))
            return False, ("Manual mode-er somoy sesh holo (timeout) — "
                           "page khula ache, 'tumi koro' bolle ami korbo.")
        finally:
            # Manual mode NEVER closes the driver: the page must stay
            # open in the user's Chrome for them to keep clicking. The
            # caller owns the driver lifecycle from here.
            pass
    except Exception as e:
        return False, f"Manual mode chalate parlam na: {e}"
