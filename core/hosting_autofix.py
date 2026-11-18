"""core/hosting_autofix.py — 🛠️ Hosting Auto-Fix: Render deploy fail hole
nijei thik koro.

Loop (max 3 attempts): latest deploy dekho -> fail hole deploy logs ano ->
error classify koro -> fix apply koro -> redeploy koro -> abar check koro.
Live hole kichui kora lagbe na — "live, kichu lagbe na" bolei sesh.

Fixes this module can REALLY apply (anything else stops honestly with the
log tail + what the user should do):
  * missing_env_var with a KNOWN safe default (PORT=10000, NODE_ENV=
    production, PYTHON_VERSION=3.12) — set via the Render API single-key
    PUT (core/render_deploy.set_env_var — other vars untouched).
  * dependency — a pip/npm install failed on a package version: bump/pin
    that package in requirements.txt (or package.json) through the GitHub
    Contents API and redeploy.
  * transient — the deploy failed with a network/timeout error: redeploy
    once, same code.

Fixes it NEVER guesses: an unknown env var's value (the user must say it),
a start command / port-binding bug (code change — reported with the exact
log lines), or anything needing a secret (never invented, never committed).

Every function returns a short string or a dict and never raises.
No Qt anywhere — runs on worker threads.
"""
from __future__ import annotations

import base64
import json
import re

try:
    import requests as _requests
except Exception:  # pragma: no cover - requirements.txt lists it
    _requests = None

try:
    from core import connectors as _conn
except Exception:  # pragma: no cover - never on a real install
    _conn = None

try:
    from core import render_deploy as _rd
except Exception:  # pragma: no cover - never on a real install
    _rd = None

_GH = "https://api.github.com"
_MAX_ATTEMPTS = 3

# Env vars with a safe default the fixer may set on its own. Anything else
# needs the user's value — the fixer asks instead of guessing.
_KNOWN_DEFAULTS = {
    "PORT": "10000",
    "NODE_ENV": "production",
    "PYTHON_VERSION": "3.12",
}

# (regex, kind, key-group) — first match wins.
_MISSING_ENV_RES = (
    re.compile(r"missing environment variable[:\s]+([A-Z][A-Z0-9_]*)", re.I),
    re.compile(r"environment variable ([A-Z][A-Z0-9_]*) (?:is not set|not found|required)", re.I),
    re.compile(r"KeyError:\s*['\"]([A-Z][A-Z0-9_]*)['\"]", re.I),
    re.compile(r"process\.env\.([A-Z][A-Z0-9_]*) is (?:not defined|undefined)", re.I),
)

_DEPENDENCY_RES = (
    re.compile(r"ERROR: Could not find a version that satisfies the requirement (\S+)", re.I),
    re.compile(r"ERROR: No matching distribution found for (\S+)", re.I),
    re.compile(r"npm ERR!.*(?:notarget|404).*['\"]([^'\"]+)['\"]", re.I),
    re.compile(r"Could not resolve dependency.*['\"]([^'\"]+)['\"]", re.I),
)


# ── classification (pure — unit-tested) ──────────────────────────────────────

def classify_hosting_failure(log_text: str) -> dict:
    """{kind, key, detail, fix} for a deploy log. Pure — no network."""
    try:
        text = str(log_text or "")
        if not text.strip():
            return {"kind": "unknown", "key": "", "detail": "Log khali.",
                    "fix": "none"}
        low = text.lower()
        for rx in _MISSING_ENV_RES:
            m = rx.search(text)
            if m:
                key = m.group(1).upper()
                return {"kind": "missing_env_var", "key": key,
                        "detail": f"Env var {key} set kora nei.",
                        "fix": ("set_default" if key in _KNOWN_DEFAULTS
                                else "ask_user")}
        for rx in _DEPENDENCY_RES:
            m = rx.search(text)
            if m:
                pkg = m.group(1).strip().strip("'\"")
                return {"kind": "dependency", "key": pkg,
                        "detail": f"Package {pkg}-er version pelam na.",
                        "fix": "pin_package"}
        if ("no open ports detected" in low or "timed out" in low
                and "port" in low) or "application failed to respond" in low:
            return {"kind": "port", "key": "PORT",
                    "detail": "App PORT-e listen korche na / respond korche na.",
                    "fix": "none"}
        if "out of memory" in low or "killed" in low and "memory" in low:
            return {"kind": "out_of_memory", "key": "",
                    "detail": "Deploy memory sesh hoye geche.",
                    "fix": "none"}
        if ("connection" in low and ("timed out" in low or "reset" in low)
                or "temporary failure" in low or "network is unreachable" in low):
            return {"kind": "transient", "key": "",
                    "detail": "Network/timeout error — khoniker gondogol hote pare.",
                    "fix": "redeploy"}
        if "error" in low or "failed" in low or "traceback" in low:
            return {"kind": "build_failed", "key": "",
                    "detail": "Build/deploy fail koreche — log-e error ache.",
                    "fix": "none"}
        return {"kind": "unknown", "key": "",
                "detail": "Log-e chena error pelam na.",
                "fix": "none"}
    except Exception:
        return {"kind": "unknown", "key": "", "detail": "Log porte parlam na.",
                "fix": "none"}


# ── GitHub file patch (for the dependency fix) ───────────────────────────────

def _gh_headers() -> dict | None:
    try:
        tok = (_conn.get_token("github_token") or "").strip() if _conn else ""
    except Exception:
        tok = ""
    if not tok:
        return None
    return {"Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json"}


def _gh_read(owner: str, repo: str, path: str) -> tuple[str, str]:
    """(file content, sha) or (\"\", \"\"). Never raises."""
    if _requests is None:
        return "", ""
    headers = _gh_headers()
    if headers is None:
        return "", ""
    try:
        r = _requests.get(f"{_GH}/repos/{owner}/{repo}/contents/{path}",
                          headers=headers, timeout=20)
        if r.status_code != 200:
            return "", ""
        data = r.json()
        content = base64.b64decode(data.get("content", "") or "").decode(
            "utf-8", errors="ignore")
        return content, str(data.get("sha", "") or "")
    except Exception:
        return "", ""


def _gh_write(owner: str, repo: str, path: str, content: str, sha: str,
              message: str) -> bool:
    """Commit a file change via the Contents API. Never raises."""
    if _requests is None:
        return False
    headers = _gh_headers()
    if headers is None:
        return False
    try:
        payload = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode(),
            "sha": sha,
        }
        r = _requests.put(f"{_GH}/repos/{owner}/{repo}/contents/{path}",
                          headers=headers, json=payload, timeout=20)
        return r.status_code in (200, 201)
    except Exception:
        return False


def _repo_of(service: dict) -> tuple[str, str]:
    """(owner, repo) from a Render service dict's repo URL, or (\"\", \"\")."""
    try:
        url = str((service or {}).get("repo", "") or "")
        m = re.search(r"github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", url)
        if m:
            return m.group(1), m.group(2)
        return "", ""
    except Exception:
        return "", ""


def _pin_package_in_requirements(owner: str, repo: str, package: str) -> bool:
    """Drop the failing package's version pin from requirements.txt (so pip
    picks the newest working one) and commit. Returns True on commit."""
    try:
        content, sha = _gh_read(owner, repo, "requirements.txt")
        if not content or not sha:
            return False
        pkg = (package or "").strip()
        if not pkg:
            return False
        lines, changed = [], False
        for line in content.splitlines():
            stripped = line.strip()
            base = re.split(r"[<>=!~\s\[]", stripped, maxsplit=1)[0].lower()
            if base == pkg.lower() and re.search(r"[<>=!~]", stripped):
                lines.append(pkg)  # unpinned — pip picks the newest
                changed = True
            else:
                lines.append(line)
        if not changed:
            return False
        new = "\n".join(lines) + "\n"
        return _gh_write(owner, repo, "requirements.txt", new, sha,
                         f"Hosting auto-fix: unpin {pkg} (deploy fail)")
    except Exception:
        return False


# ── the loop ─────────────────────────────────────────────────────────────────

def autofix(service_id: str = "", max_attempts: int = _MAX_ATTEMPTS) -> str:
    """Check the latest deploy of a service and auto-fix it when it failed.
    Returns a short human-readable string. Never raises."""
    try:
        if _rd is None:
            return "Render deploy module pelam na."
        sid = (service_id or "").strip()
        if not sid:
            svc = _rd.find_service("mark-lvii")
            if not svc:
                return ("Render-e mark-lvii-dashboard service pelam na — age "
                        "RENDER_DEPLOY.md-er steps-e service-ta banao.")
            sid = svc["id"]
        attempts = max(1, min(int(max_attempts or _MAX_ATTEMPTS), 5))
        for attempt in range(1, attempts + 1):
            dep, err = _rd.latest_deploy(sid)
            if err:
                return f"Deploy dekhte parlam na: {err}"
            status = str(dep.get("status", "") or "")
            if status == "live":
                return "✅ Deploy live ache — kichu fix kora lagbe na."
            if status not in ("deactivated", "update_failed", "build_failed",
                              "canceled", "failed"):
                return (f"Deploy ekhono {status} — sesh hote dao, tarpor "
                        f"abar check koro.")
            logs = _rd.deploy_logs(sid, str(dep.get("id", "") or ""))
            found = classify_hosting_failure(logs)
            kind, key, fix = found["kind"], found["key"], found["fix"]
            if fix == "set_default":
                msg = _rd.set_env_var(sid, key, _KNOWN_DEFAULTS[key])
                if "✅" not in msg:
                    return f"Env var {key} set korte parlam na: {msg}"
                _rd.trigger_deploy(sid)
                if attempt == attempts:
                    return (f"Env var {key} set kore redeploy dilam "
                            f"({attempt}/{attempts}) — deploy sesh hole abar "
                            f"check koro.")
                continue
            if fix == "ask_user":
                return (f"Deploy fail: env var {key} set kora nei. {key}-er "
                        f"value-ta bolo (chat-e pathiyo na — Plugin Settings > "
                        f"🔗 CONNECTORS-e ba Render dashboard-e bosao), tarpor "
                        f"abar deploy bolo.")
            if fix == "pin_package":
                svc, _e = _rd.get_service(sid)
                owner, repo = _repo_of(svc)
                if not owner:
                    return (f"Deploy fail: package {key}-er version pelam na, "
                            f"kintu repo-r thikana pelam na — Render service-er "
                            f"repo connect ache kina dekho.")
                if not _pin_package_in_requirements(owner, repo, key):
                    return (f"Deploy fail: package {key}-er version pelam na, "
                            f"kintu requirements.txt thik korte parlam na — "
                            f"GitHub token ache kina dekho.")
                _rd.trigger_deploy(sid)
                if attempt == attempts:
                    return (f"Package {key} unpin kore redeploy dilam "
                            f"({attempt}/{attempts}) — deploy sesh hole abar "
                            f"check koro.")
                continue
            if fix == "redeploy":
                _rd.trigger_deploy(sid)
                if attempt == attempts:
                    return (f"Network/timeout error chilo — redeploy dilam "
                            f"({attempt}/{attempts}). Deploy sesh hole abar "
                            f"check koro.")
                continue
            tail = (logs or "").strip().splitlines()[-5:]
            tail_txt = "\n".join(tail) if tail else "log pelam na"
            return (f"Deploy fail ({kind}) — auto-fix kora gelo na. Log-er "
                    f"shesh kotha:\n{tail_txt}\nEi error-ta code-er — ami "
                    f"andaje fix korbo na, log-ta dekhe bolo ki korbo.")
        return (f"{attempts} bar try korlam, deploy ekhono live hoy ni — "
                f"Render dashboard-e deploy log dekho.")
    except Exception as e:
        return f"Hosting auto-fix korte parlam na: {e}"
