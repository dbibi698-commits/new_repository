"""core/render_deploy.py — 🚀 Render REST API for the Render Deploy agent.

The Render Deploy agent card (core/agent_cards.py) and the render_deploy
tool both talk to Render through here: list services, trigger a deploy,
read deploy status + logs, and set environment variables. The API key comes
from the saved Render API key (plugin_config["connectors"]["render_api_key"]
— Plugin Settings > 🔗 CONNECTORS; never in code, never in chat).

Every function returns a short human-readable string or a (value, error)
pair and never raises, so a tool call on a worker thread can hand the
result straight to the user. ``requests`` is already in requirements.txt.

Render API facts this module relies on (api.render.com/v1):
  * GET  /services?limit=20            — list services (paginated envelope)
  * GET  /services/{id}                — one service (repo URL, details)
  * POST /services/{id}/deploys        — trigger a deploy, {"clearCache": false}
  * GET  /services/{id}/deploys?limit= — deploys, newest first
  * GET  /services/{id}/deploys/{deployId}/logs — deploy logs
  * GET  /services/{id}/env-vars       — env vars (keys + values)
  * PUT  /services/{id}/env-vars/{key} — add/update ONE var, merged into
    the set (body {"value": ...}). NOTE: PUT /env-vars (no key) REPLACES
    the whole set — never use it here.
"""
from __future__ import annotations

import json

try:
    import requests as _requests
except Exception:  # pragma: no cover - requirements.txt lists it
    _requests = None

try:
    from core import connectors as _conn
except Exception:  # pragma: no cover - never on a real install
    _conn = None

_BASE = "https://api.render.com/v1"
_TIMEOUT = 20
_DEFAULT_SERVICE = "mark-lvii-dashboard"


# ── plumbing ─────────────────────────────────────────────────────────────────

def render_key() -> str:
    """The saved Render API key, or \"\" when not set. Never raises."""
    try:
        if _conn is None:
            return ""
        return str(_conn.get_token("render_api_key") or "").strip()
    except Exception:
        return ""


def _headers() -> dict | None:
    key = render_key()
    if not key:
        return None
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


def _no_key() -> str:
    return ("Render API key set kora nei — Plugin Settings > 🔗 CONNECTORS > "
            "Render API key-e key-ta bosao (Render dashboard > Account "
            "Settings > API Keys), tarpor abar bolo.")


def _req(method: str, path: str, payload: dict | None = None):
    """(status, parsed-json-or-None, error-string). Never raises."""
    if _requests is None:
        return 0, None, "requests install kora nei — `pip install requests` dao."
    headers = _headers()
    if headers is None:
        return 0, None, _no_key()
    try:
        r = _requests.request(method, _BASE + path, headers=headers,
                              json=payload, timeout=_TIMEOUT)
    except Exception as e:
        return 0, None, f"Render API-te jete parlam na: {e}"
    try:
        data = r.json() if r.content else None
    except Exception:
        data = None
    if r.status_code >= 400:
        return r.status_code, data, f"Render API HTTP {r.status_code}"
    return r.status_code, data, ""


def _svc_of(item) -> dict:
    if isinstance(item, dict):
        return item.get("service", item) if isinstance(item.get("service"), dict) else item
    return {}


# ── services ─────────────────────────────────────────────────────────────────

def list_services() -> tuple[list[dict], str]:
    """([{"id", "name", "url", "repo"}], error). Error is \"\" on success."""
    st, data, err = _req("GET", "/services?limit=20")
    if err:
        return [], err
    items = data if isinstance(data, list) else (data or {}).get("services", [])
    out = []
    for item in items or []:
        svc = _svc_of(item)
        if not svc.get("id"):
            continue
        det = svc.get("serviceDetails") or {}
        out.append({
            "id": str(svc.get("id", "")),
            "name": str(svc.get("name", "")),
            "url": str(det.get("url", "") or svc.get("url", "") or ""),
            "repo": str(svc.get("repo", "") or ""),
        })
    return out, ""


def find_service(name_substr: str = "mark-lvii") -> dict | None:
    """First service whose name contains `name_substr`, or None. Never raises."""
    try:
        services, err = list_services()
        if err:
            return None
        needle = (name_substr or "").strip().lower()
        for svc in services:
            if needle in str(svc.get("name", "")).lower():
                return svc
        return None
    except Exception:
        return None


def get_service(service_id: str) -> tuple[dict, str]:
    """(service dict, error). Never raises."""
    service_id = (service_id or "").strip()
    if not service_id:
        return {}, "Service id dao."
    st, data, err = _req("GET", f"/services/{service_id}")
    if err:
        return {}, err
    return _svc_of(data or {}), ""


# ── deploys ──────────────────────────────────────────────────────────────────

def list_deploys(service_id: str, limit: int = 5) -> tuple[list[dict], str]:
    """Newest-first deploys: [{"id", "status", "commit", "created_at"}]."""
    service_id = (service_id or "").strip()
    if not service_id:
        return [], "Service id dao."
    st, data, err = _req("GET", f"/services/{service_id}/deploys?limit={int(limit)}")
    if err:
        return [], err
    items = data if isinstance(data, list) else (data or {}).get("deploys", [])
    out = []
    for item in items or []:
        dep = item.get("deploy", item) if isinstance(item, dict) else {}
        if not isinstance(dep, dict) or not dep.get("id"):
            continue
        commit = dep.get("commit") or {}
        out.append({
            "id": str(dep.get("id", "")),
            "status": str(dep.get("status", "")),
            "commit": str(commit.get("id", "") or "")[:8],
            "created_at": str(dep.get("createdAt", "") or ""),
        })
    return out, ""


def latest_deploy(service_id: str) -> tuple[dict, str]:
    """(newest deploy dict, error)."""
    deps, err = list_deploys(service_id, limit=1)
    if err:
        return {}, err
    if not deps:
        return {}, "Ei service-er kono deploy pelam na."
    return deps[0], ""


def trigger_deploy(service_id: str = "") -> str:
    """Trigger a deploy of a service (auto-finds mark-lvii-dashboard when
    no id is given). Returns a short human-readable string. Never raises."""
    try:
        if not render_key():
            return _no_key()
        sid = (service_id or "").strip()
        if not sid:
            svc = find_service("mark-lvii")
            if not svc:
                return ("Render-e mark-lvii-dashboard service pelam na — age "
                        "RENDER_DEPLOY.md-er steps-e service-ta banao, tarpor "
                        "deploy bolo.")
            sid = svc["id"]
        st, data, err = _req("POST", f"/services/{sid}/deploys",
                             payload={"clearCache": False})
        if err:
            return f"Render deploy start korte parlam na: {err}."
        # POST /deploys answers {"deploy": {...}} — unwrap the envelope.
        dep = {}
        if isinstance(data, dict):
            inner = data.get("deploy")
            dep = inner if isinstance(inner, dict) else data
        did = str(dep.get("id", "") or "")
        return ("⏳ Render deploy shuru holo"
                + (f" (deploy {did})" if did else "")
                + " — dashboard update hochhe, koyek minute lagbe.")
    except Exception as e:
        return f"Render deploy start korte parlam na: {e}"


def deploy_status(service_id: str = "") -> str:
    """One-line status of the latest deploy. Never raises."""
    try:
        if not render_key():
            return _no_key()
        sid = (service_id or "").strip()
        if not sid:
            svc = find_service("mark-lvii")
            if not svc:
                return "Render-e mark-lvii-dashboard service pelam na."
            sid = svc["id"]
        dep, err = latest_deploy(sid)
        if err:
            return err
        return (f"Render deploy: {dep.get('status', '?')}"
                + (f" (commit {dep.get('commit', '')})" if dep.get("commit") else "")
                + (f" — {dep.get('created_at', '')}" if dep.get("created_at") else ""))
    except Exception as e:
        return f"Deploy status dekhte parlam na: {e}"


def deploy_logs(service_id: str, deploy_id: str, limit: int = 200) -> str:
    """Plain-text tail of a deploy's logs, or \"\" when unavailable.
    Never raises."""
    try:
        sid, did = (service_id or "").strip(), (deploy_id or "").strip()
        if not sid or not did:
            return ""
        st, data, err = _req(
            "GET", f"/services/{sid}/deploys/{did}/logs?limit={int(limit)}")
        if err or not data:
            return ""
        items = data if isinstance(data, list) else (data or {}).get("logs", [])
        lines = []
        for item in items or []:
            if isinstance(item, dict):
                lines.append(str(item.get("message", "") or ""))
            elif isinstance(item, str):
                lines.append(item)
        return "\n".join(l for l in lines if l)
    except Exception:
        return ""


# ── env vars ─────────────────────────────────────────────────────────────────

def list_env_var_keys(service_id: str) -> tuple[list[str], str]:
    """(env var key names, error). Values are never returned. Never raises."""
    try:
        sid = (service_id or "").strip()
        if not sid:
            return [], "Service id dao."
        st, data, err = _req("GET", f"/services/{sid}/env-vars?limit=100")
        if err:
            return [], err
        items = data if isinstance(data, list) else []
        keys = []
        for item in items:
            ev = (item or {}).get("envVar") or {}
            if ev.get("key"):
                keys.append(str(ev["key"]))
        return keys, ""
    except Exception as e:
        return [], f"Env var list pelam na: {e}"


def set_env_var(service_id: str, key: str, value: str) -> str:
    """Add/update ONE env var (merged — other vars are untouched). The
    single-key PUT is used on purpose: PUT /env-vars without a key REPLACES
    the whole set. A change needs a deploy to take effect. Never raises."""
    try:
        sid, key = (service_id or "").strip(), (key or "").strip()
        if not sid or not key:
            return "Service id ar env var-er naam — duitoi lagbe."
        st, data, err = _req("PUT", f"/services/{sid}/env-vars/{key}",
                             payload={"value": str(value or "")})
        if err:
            return f"Env var {key} set korte parlam na: {err}."
        return (f"✅ Env var {key} set holo — deploy korle kaj korbe "
                f"(ekhono deploy hoy ni).")
    except Exception as e:
        return f"Env var set korte parlam na: {e}"
