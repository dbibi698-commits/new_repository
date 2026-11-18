"""core/apk_selfheal.py — Self-healing APK build for Mark-LVII.

Wraps the existing GitHub Actions dispatch (core/connectors.py's
``github_dispatch_workflow``, the same mechanism ``build_apk`` uses) with
poll → diagnose → fix → re-dispatch, up to 3 attempts.

WHAT IT DOES
    1. Dispatch the workflow (reuse, never re-implement, the dispatch).
    2. Poll the workflow run until it completes.
    3. On failure, fetch the failing job's log tail and classify it into a
       KNOWN error class, each with a fix (or an honest stop):
         dependency      → pin/adjust the dependency version in the build
                           file, then re-dispatch.
         manifest        → fix the named AndroidManifest attribute, then
                           re-dispatch.
         missing_secret  → NOT auto-fixable. Never invents a secret or a
                           keystore — stops and tells the user what to add.
         syntax          → reports file + line; applies ONLY a safe
                           mechanical fix for a known pattern (a missing
                           import for a known symbol), else stops.
         transient       → re-dispatch unchanged (network / 5xx / runner
                           lost / rate limit).
         unknown         → reported, not silently fixed.
         auth            → token/permission problem — stops, never retried
                           blindly.
    4. Hard cap of 3 dispatches. No infinite loops, ever.

RULES
    * Every public function returns a plain-words string and never raises.
    * No real token is ever read from code or printed; the token comes from
      core/connectors.get_token("github_token") exactly like build_apk.
    * Fixes are applied through the GitHub Contents API (read + push via
      core/connectors.github_push_file) — a commit on the repo, never a
      local edit of something the build does not use.
    * ``request_fn`` / ``dispatch_fn`` / ``log_fn`` / ``read_fn`` /
      ``push_fn`` / ``sleep_fn`` are injectable so tests can run with a
      mocked GitHub API and mocked build logs — no network, no real build.

Polling cost: a real build takes minutes, so the default poll is every
20 s for up to 30 polls (~10 min). Callers that cannot wait (the plugin)
run this on a background thread.
"""
from __future__ import annotations

import base64
import io
import re
import time
import zipfile
from datetime import datetime, timezone

try:
    import requests as _requests
except Exception:  # pragma: no cover - requirements.txt lists it
    _requests = None

_GH = "https://api.github.com"
_MAX_ATTEMPTS = 3
_MAX_LOG_CHARS = 4000
_POLL_INTERVAL_S = 20
_MAX_POLLS = 30

# Build files that can carry a dependency version, in search order.
_DEPENDENCY_FILES = (
    "app/build.gradle",
    "app/build.gradle.kts",
    "build.gradle",
    "build.gradle.kts",
)
_MANIFEST_PATH = "AndroidManifest.xml"

# Manifest attributes with a safe mechanical default. Anything else is
# reported, not guessed.
_MANIFEST_DEFAULTS = {
    "android:exported": "true",
}

# Plugins whose version is unambiguous when the log says the plugin was
# not found: (dependency coordinate, known-good version).
_PLUGIN_VERSIONS = {
    "com.android.application": ("com.android.tools.build:gradle", "8.5.2"),
    "com.android.library": ("com.android.tools.build:gradle", "8.5.2"),
    "org.jetbrains.kotlin.android": (
        "org.jetbrains.kotlin:kotlin-gradle-plugin", "2.0.0"),
}

# Gradle version for a JDK class-file major version the wrapper cannot
# read ("Unsupported class file major version 65" = JDK 21, etc.).
_GRADLE_FOR_CLASS_MAJOR = {65: "8.5", 66: "8.8", 67: "8.10", 68: "8.11"}

# Symbols whose import is unambiguous — the ONLY syntax fixes applied
# mechanically. Anything else is reported with file + line, not guessed.
_KNOWN_IMPORTS = {
    "Intent": "android.content.Intent",
    "Bundle": "android.os.Bundle",
    "Context": "android.content.Context",
    "SharedPreferences": "android.content.SharedPreferences",
    "Log": "android.util.Log",
    "Toast": "android.widget.Toast",
    "TextView": "android.widget.TextView",
    "Button": "android.widget.Button",
    "EditText": "android.widget.EditText",
    "ImageView": "android.widget.ImageView",
    "View": "android.view.View",
    "Uri": "android.net.Uri",
    "Handler": "android.os.Handler",
    "Looper": "android.os.Looper",
    "Activity": "android.app.Activity",
    "AppCompatActivity": "androidx.appcompat.app.AppCompatActivity",
    "RecyclerView": "androidx.recyclerview.widget.RecyclerView",
    "LinearLayoutManager": "androidx.recyclerview.widget.LinearLayoutManager",
    "Gson": "com.google.gson.Gson",
    "JSONObject": "org.json.JSONObject",
    "JSONArray": "org.json.JSONArray",
    "JSONException": "org.json.JSONException",
    "UUID": "java.util.UUID",
    "ArrayList": "java.util.ArrayList",
    "HashMap": "java.util.HashMap",
}

_CLASS_LABEL = {
    "dependency": "dependency/version error",
    "manifest": "AndroidManifest error",
    "missing_secret": "missing secret / keystore",
    "syntax": "Kotlin/Java syntax error",
    "transient": "network / transient error",
    "auth": "GitHub token / permission problem",
    "gradle_version": "Gradle version error",
    "kotlin_version": "Kotlin version error",
    "dex": "DEX / 64K methods error",
    "resource": "Android resource error",
    "sdk": "Android SDK error",
    "unknown": "unknown build error",
}


# ── small utilities (never raise) ────────────────────────────────────────────

def _trunc(text: str, limit: int = 600) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _github_token() -> str:
    try:
        from core import connectors as _conn
        return _conn.get_token("github_token")
    except Exception:
        return ""


def _http(method: str, url: str, headers: dict | None = None,
          params: dict | None = None, payload=None,
          timeout: int = 20) -> tuple[int, object, str]:
    """Default transport: (status, parsed-JSON-or-text, error-string)."""
    if _requests is None:
        return 0, None, "requests install kora nei — `pip install requests` dao."
    try:
        r = _requests.request(method, url, headers=headers or {},
                              params=params, json=payload, timeout=timeout)
    except Exception as e:
        return 0, None, f"network error: {e}"
    try:
        data = r.json()
    except Exception:
        data = r.text
    if r.status_code >= 400:
        msg = ""
        if isinstance(data, dict):
            msg = str(data.get("message", "") or "")
        return r.status_code, data, msg or f"HTTP {r.status_code}"
    return r.status_code, data, ""


def _headers() -> dict:
    return {"Authorization": f"Bearer {_github_token()}",
            "Accept": "application/vnd.github+json"}


# ── dispatch / polling (reuses connectors' dispatch) ─────────────────────────

def _default_dispatch(owner: str, repo: str, workflow: str,
                      ref: str) -> str:
    """The same dispatch build_apk uses. Returns its plain-words string;
    success starts with ✅."""
    try:
        from core import connectors as _conn
        return _conn.github_dispatch_workflow(None, owner, repo, workflow, ref)
    except Exception as e:
        return f"Dispatch korte parlam na: {e}"


def _dispatch_ok(result: str) -> bool:
    return str(result or "").strip().startswith("✅")


def _latest_run(owner: str, repo: str, workflow: str, ref: str,
                request_fn, since_iso: str) -> dict | None:
    """Newest run of this workflow created at/after `since_iso`, else None."""
    try:
        st, data, _ = request_fn(
            "GET",
            f"{_GH}/repos/{owner}/{repo}/actions/workflows/{workflow}/runs",
            headers=_headers(), params={"per_page": 5})
        if st != 200 or not isinstance(data, dict):
            return None
        runs = data.get("workflow_runs") or []
        for run in runs:
            if not isinstance(run, dict):
                continue
            created = str(run.get("created_at") or "")
            if created >= since_iso:
                return run
        return None
    except Exception:
        return None


def _poll_run(owner: str, repo: str, workflow: str, ref: str, request_fn,
              sleep_fn, poll_interval_s: int, max_polls: int) -> tuple[dict | None, str]:
    """Poll until the newest run completes. Returns (run, note);
    run is None when no run ever appeared."""
    since = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run = None
    for _ in range(max(1, max_polls)):
        try:
            run = _latest_run(owner, repo, workflow, ref, request_fn, since)
        except Exception:
            run = None
        if run is not None and str(run.get("status") or "") == "completed":
            return run, ""
        if run is not None and str(run.get("status") or "") not in (
                "queued", "in_progress", "waiting", "pending", ""):
            return run, ""
        try:
            sleep_fn(max(1, int(poll_interval_s or _POLL_INTERVAL_S)))
        except Exception:
            pass
    if run is None:
        return None, "run pelam na"
    return run, "run sesh holo na"


# ── log tail ─────────────────────────────────────────────────────────────────

def _default_log(owner: str, repo: str, job_id: int) -> str:
    """Download one job's logs (GitHub returns a zip of per-step text
    files) and return the tail as text. '' when unavailable."""
    if _requests is None:
        return ""
    try:
        r = _requests.get(
            f"{_GH}/repos/{owner}/{repo}/actions/jobs/{job_id}/logs",
            headers=_headers(), timeout=30)
        if r.status_code != 200 or not r.content:
            return ""
        raw = r.content
        if raw[:2] == b"PK":
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    parts = []
                    for name in z.namelist():
                        try:
                            parts.append(z.read(name).decode("utf-8", "replace"))
                        except Exception:
                            continue
                    text = "\n".join(parts)
            except Exception:
                text = raw.decode("utf-8", "replace")
        else:
            text = raw.decode("utf-8", "replace")
        return text[-_MAX_LOG_CHARS:]
    except Exception:
        return ""


def _fetch_log_tail(owner: str, repo: str, run: dict, request_fn,
                    log_fn) -> str:
    """Log tail of the failed job of a completed run ('' when unavailable)."""
    try:
        run_id = run.get("id")
        if not run_id:
            return ""
        st, data, _ = request_fn(
            "GET", f"{_GH}/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
            headers=_headers(), params={"per_page": 30})
        if st != 200 or not isinstance(data, dict):
            return ""
        jobs = [j for j in (data.get("jobs") or []) if isinstance(j, dict)]
        failed = [j for j in jobs if str(j.get("conclusion") or "") == "failure"]
        target = failed[0] if failed else (jobs[0] if jobs else None)
        if target is None or not target.get("id"):
            return ""
        try:
            text = log_fn(owner, repo, int(target["id"]))
        except Exception:
            text = ""
        return str(text or "")[-_MAX_LOG_CHARS:]
    except Exception:
        return ""


# ── classification ───────────────────────────────────────────────────────────

def classify_failure(log_text: str) -> dict:
    """Log tail → {class, auto_fixable, detail}. Pure function, never raises.

    Order matters: a missing secret outranks everything else (it must never
    trigger a fix attempt), then dependency, manifest, syntax, transient.
    """
    log = str(log_text or "")
    low = log.lower()
    try:
        # (c) missing secret / keystore — NEVER auto-fixable.
        secret_re = re.compile(
            r"(secret\b.{0,60}\b(not found|missing|not set|not configured|undefined)"
            r"|missing\b.{0,40}\bsecret"
            r"|keystore\b.{0,60}\b(not found|missing|does not exist|no such file)"
            r"|no such file.{0,40}keystore"
            r"|signingconfig\b.{0,40}\bnot found"
            r"|keystore_password|signing_key\b.{0,40}\bnot found)",
            re.I | re.S)
        m = secret_re.search(log)
        if m:
            return {"class": "missing_secret", "auto_fixable": False,
                    "detail": _trunc(" ".join(m.group(0).split()), 200)}
        # Auth problems (dispatch-side, e.g. bad token) — also never retried.
        if re.search(r"bad credentials|401 unauthorized|\b401\b.*token|"
                     r"token.*(expired|invalid|revoked)|permission denied"
                     r"|resource not accessible by integration", low):
            return {"class": "auth", "auto_fixable": False,
                    "detail": "GitHub token / permission problem"}
        # (f) Android SDK — the runner has no SDK / compileSdk missing.
        # Checked before dependency: "SDK location not found" must never
        # be mistaken for a missing library.
        sdk_re = re.compile(
            r"(sdk location not found[^\n]{0,120}"
            r"|android_home.{0,40}(not set|is not set|not found)"
            r"|android sdk.{0,60}(not found|not installed|missing)"
            r"|compileSdk.{0,60}(not specified|is not specified|missing)"
            r"|sdkmanager.{0,60}(not found|failed))", re.I)
        m = sdk_re.search(log)
        if m:
            return {"class": "sdk", "auto_fixable": False,
                    "detail": _trunc(" ".join(m.group(0).split()), 200)}
        # (g) Gradle version — the wrapper is too old for the JDK/AGP, or
        # the log names a minimum Gradle version. Checked before
        # dependency: "Could not find org.gradle..." would match the dep
        # pattern first and the pin logic cannot fix a Gradle version.
        gv_re = re.compile(
            r"(minimum supported gradle version is[^\n]{0,80}"
            r"|gradle version[^\n]{0,80}(is required|required|too old|not supported)"
            r"|unsupported class file major version[^\n]{0,80}"
            r"|could not find org\.gradle[^\n]{0,120}"
            r"|this version of the android gradle plugin requires gradle[^\n]{0,80}"
            r"|gradle-[0-9][^\s]*-bin\.zip[^\n]{0,80}(not found|404|failed))", re.I)
        m = gv_re.search(log)
        if m:
            return {"class": "gradle_version", "auto_fixable": True,
                    "detail": _trunc(" ".join(m.group(0).split()), 200)}
        # (h) Kotlin version — plugin loaded twice, or a Kotlin version
        # the AGP rejects. (A plain "Could not find ... kotlin-gradle-
        # plugin" stays a dependency — the pin logic handles that one.)
        kv_re = re.compile(
            r"(kotlin gradle plugin was loaded multiple times[^\n]{0,120}"
            r"|kotlin version[^\n]{0,80}(not compatible|incompatible|is not supported)"
            r"|incompatible kotlin version[^\n]{0,120}"
            r"|the kotlin gradle plugin[^\n]{0,80}(requires|needs)[^\n]{0,80}"
            r"|kotlin-stdlib[^\n]{0,60}version conflict[^\n]{0,80})", re.I)
        m = kv_re.search(log)
        if m:
            return {"class": "kotlin_version", "auto_fixable": True,
                    "detail": _trunc(" ".join(m.group(0).split()), 200)}
        # (a) dependency / version.
        dep_re = re.compile(
            r"(could not (?:find|resolve|download)[^\n]{0,160}"
            r"|failed to resolve:[^\n]{0,160}"
            r"|unable to resolve dependency[^\n]{0,160}"
            r"|could not get resource[^\n]{0,120}"
            r"|version conflict[^\n]{0,160}"
            r"|plugin (?:with id|)\s*'[^']+' was not found[^\n]{0,120}"
            r"|plugin \[id: '[^']+'[^\n]{0,40}was not found[^\n]{0,120})", re.I)
        m = dep_re.search(log)
        if m:
            return {"class": "dependency", "auto_fixable": True,
                    "detail": _trunc(" ".join(m.group(0).split()), 200)}
        # (b) AndroidManifest.
        man_re = re.compile(
            r"(android:exported needs to be explicitly specified[^\n]{0,120}"
            r"|manifest merger failed[^\n]{0,160}"
            r"|androidmanifest\.xml[^\n]{0,160}"
            r"|attribute '?(android:[a-zA-Z]+)'?[^.\n]{0,80}"
            r"(not found|missing|required))", re.I)
        m = man_re.search(log)
        if m:
            return {"class": "manifest", "auto_fixable": True,
                    "detail": _trunc(" ".join(m.group(0).split()), 200)}
        # (i) DEX / 64K — too many methods for one dex file.
        dex_re = re.compile(
            r"(cannot fit requested classes in a single dex file[^\n]{0,120}"
            r"|dexarchivemergerexception[^\n]{0,120}"
            r"|the number of method references in a \.dex file cannot exceed 64k[^\n]{0,80}"
            r"|transformdexarchivewithdexmerger[^\n]{0,80}failed[^\n]{0,80})", re.I)
        m = dex_re.search(log)
        if m:
            return {"class": "dex", "auto_fixable": True,
                    "detail": _trunc(" ".join(m.group(0).split()), 200)}
        # (j) Android resources — AAPT linking failed, a resource is
        # missing or duplicated. Reported, never guessed: the missing file
        # has to be added by hand.
        res_re = re.compile(
            r"(aapt[^\n]{0,40}error: resource[^\n]{0,120}"
            r"|failed linking references[^\n]{0,120}"
            r"|resource linking failed[^\n]{0,120}"
            r"|duplicate resources?[^\n]{0,120}"
            r"|error: (?:failed to find|resource)[^\n]{0,80}not found[^\n]{0,80})", re.I)
        m = res_re.search(log)
        if m:
            return {"class": "resource", "auto_fixable": False,
                    "detail": _trunc(" ".join(m.group(0).split()), 200)}
        # (d) Kotlin / Java syntax.
        syn_re = re.compile(
            r"(unresolved reference:\s*[A-Za-z_][A-Za-z0-9_]*"
            r"|cannot find symbol[^\n]{0,120}"
            r"|syntax error[^\n]{0,120}"
            r"|';' expected[^\n]{0,120}"
            r"|error:\s*(class|interface|enum) expected[^\n]{0,80}"
            r"|expecting (a top level|member) declaration[^\n]{0,80}"
            r"|type mismatch[^\n]{0,120}"
            r"|overload resolution ambiguity[^\n]{0,120}"
            r"|none of the following functions can be called[^\n]{0,120}"
            r"|compilation failed[^\n]{0,120})", re.I)
        m = syn_re.search(log)
        if m:
            return {"class": "syntax", "auto_fixable": True,
                    "detail": _trunc(" ".join(m.group(0).split()), 200)}
        # (e) network / transient.
        if re.search(
                r"(connection (reset|timed out|refused)|timed out|timeout|read timed out"
                r"|temporary failure|socket ?timeout|network (error|is unreachable)"
                r"|502 bad gateway|503 service unavailable|504 gateway time-out"
                r"|http 429|too many requests"
                r"|internal server error|api rate limit|rate limit exceeded"
                r"|runner.*lost communication|runner has received a shutdown signal"
                r"|could not get .*https?://[^\s]+ (500|502|503))", low):
            return {"class": "transient", "auto_fixable": True,
                    "detail": "network / transient failure — re-dispatch unchanged"}
        return {"class": "unknown", "auto_fixable": False,
                "detail": _trunc(log[-300:] if log else "kono log pelam na", 200)}
    except Exception:
        return {"class": "unknown", "auto_fixable": False,
                "detail": "log classify korte parlam na"}


# ── repo file access (defaults use the Contents API) ─────────────────────────

def _default_read(owner: str, repo: str, path: str, ref: str,
                  request_fn) -> tuple[str | None, str | None]:
    """(decoded content, sha) or (None, None). Never raises."""
    try:
        st, data, _ = request_fn(
            "GET", f"{_GH}/repos/{owner}/{repo}/contents/{path}",
            headers=_headers(), params={"ref": ref or "main"})
        if st != 200 or not isinstance(data, dict):
            return None, None
        content = data.get("content") or ""
        try:
            text = base64.b64decode("".join(str(content).split())).decode(
                "utf-8", "replace")
        except Exception:
            return None, None
        return text, str(data.get("sha") or "")
    except Exception:
        return None, None


def _default_push(owner: str, repo: str, path: str, content: str,
                  message: str) -> str:
    """Push one file via connectors.github_push_file. Returns its string."""
    try:
        from core import connectors as _conn
        return _conn.github_push_file(None, owner, repo, path, content, message)
    except Exception as e:
        return f"Push korte parlam na: {e}"


# ── fixes ────────────────────────────────────────────────────────────────────

def _pick_version(log: str, coord: str, current: str) -> str:
    """A concrete version for `coord` named in the log, other than `current`."""
    try:
        versions = re.findall(r"(?<![\d.])(\d+\.\d+(?:\.\d+)?(?:[-+][A-Za-z0-9.]+)?)",
                              log)
        for v in versions:
            if v and v != current:
                return v
    except Exception:
        pass
    return ""


def _fix_dependency(log: str, owner: str, repo: str, workflow: str, ref: str,
                    read_fn, push_fn) -> tuple[bool, str]:
    """Pin a dynamic dependency version, or swap a failed concrete version
    for another one the log names. Also handles "Plugin [id: 'x'] was not
    found" for known plugins by adding the missing version to the plugin
    block. Returns (applied, message)."""
    try:
        # Plugin id not found — the plugin block has no version for a
        # known plugin. Add the known version; never invent a new one.
        plug_m = re.search(
            r"plugin (?:\[id: '|with id ')([a-z0-9_.\-]+)'", log, re.I)
        if plug_m:
            plug_id = plug_m.group(1)
            known = _PLUGIN_VERSIONS.get(plug_id)
            if not known:
                return False, (f"Plugin '{plug_id}' pelam na, kintu er "
                               "version ami janina — build file-e plugin-ta "
                               "khule version-ta bosao.")
            _coord, version = known
            for path in ("build.gradle.kts", "build.gradle"):
                try:
                    content, _sha = read_fn(owner, repo, path, ref)
                except Exception:
                    content = None
                if not content or plug_id not in content:
                    continue
                # kts: id("x") / id("x") version "y"; groovy: id 'x' / id 'x' version 'y'
                kts_m = re.search(re.escape(f'id("{plug_id}")')
                                  + r"(\s+version\s+\"[^\"]+\")?", content)
                grv_m = None
                if not kts_m:
                    grv_m = re.search(re.escape(f"id '{plug_id}'")
                                      + r"(\s+version\s+'[^']+')?", content)
                m = kts_m or grv_m
                if not m:
                    continue
                if m.group(1):
                    return False, (f"Plugin '{plug_id}'-er version already "
                                   "ache — version-tai bhul hote pare, nije "
                                   "version-ta thik koro.")
                quote = '"' if kts_m else "'"
                new_content = (content[:m.end()] +
                               f" version {quote}{version}{quote}" +
                               content[m.end():])
                try:
                    res = push_fn(owner, repo, path, new_content,
                                  f"self-heal: add version {version} to plugin {plug_id}")
                except Exception as e:
                    return False, f"fix-ta push korte parlam na: {e}"
                if str(res or "").strip().startswith("✅"):
                    return True, (f"{path}-e plugin '{plug_id}'-er version "
                                  f"{version} bosiye dilam, tarpor abar build dilam.")
                return False, f"fix-ta push holo na: {_trunc(res, 200)}"
            return False, (f"Plugin '{plug_id}'-r line-ta root build file-e "
                           "pelam na — plugin block-ta khule dekho.")
        m = re.search(
            r"(?:could not (?:find|resolve|download)|failed to resolve:|"
            r"unable to resolve dependency)[^\n]*?"
            r"([A-Za-z0-9_.\-]+:[A-Za-z0-9_.\-]+(?::[^\s'\"\),;]+)?)",
            log, re.I)
        if not m:
            m = re.search(r"([A-Za-z0-9_.\-]+:[A-Za-z0-9_.\-]+(?::[0-9][^\s'\"\),;]*)?)",
                          log)
        if not m:
            return False, "log-e dependency-r naam pelam na — nije dekhte hobe."
        coord_full = m.group(1)
        parts = coord_full.split(":")
        group, artifact = parts[0], parts[1]
        coord = f"{group}:{artifact}"
        current_in_log = parts[2] if len(parts) > 2 else ""
        for path in (f".github/workflows/{workflow}",) + _DEPENDENCY_FILES:
            try:
                content, _sha = read_fn(owner, repo, path, ref)
            except Exception:
                content = None
            if not content or coord not in content:
                continue
            vm = re.search(re.escape(group) + r":" + re.escape(artifact)
                           + r":([^\s'\"\)\],;]+)", content)
            if not vm:
                continue
            current = vm.group(1)
            target = ""
            if current in ("+", "latest.release", "latest.integration") \
                    or current.startswith("["):
                target = _pick_version(log, coord, current) or current_in_log
            elif current_in_log and current == current_in_log:
                target = _pick_version(log, coord, current)
            if not target:
                return False, (f"{coord}-r version-ta file-e ache ({current}), "
                               "kintu log-e bodle dewar moto onno kono version "
                               "pelam na — nije version-ta thik koro.")
            new_content = content.replace(
                f"{group}:{artifact}:{current}",
                f"{group}:{artifact}:{target}", 1)
            if new_content == content:
                continue
            try:
                res = push_fn(owner, repo, path, new_content,
                              f"self-heal: pin {coord} to {target}")
            except Exception as e:
                return False, f"fix-ta push korte parlam na: {e}"
            if str(res or "").strip().startswith("✅"):
                return True, (f"{path}-e {coord}-r version {current} theke "
                              f"{target} kore dilam, tarpor abar build dilam.")
            return False, f"fix-ta push holo na: {_trunc(res, 200)}"
        return False, (f"{coord}-r line-ta build file-e pelam na — "
                       "dependency-ta kothay ache nije dekhe version-ta thik koro.")
    except Exception as e:
        return False, f"dependency fix korte parlam na: {e}"


def _fix_manifest(log: str, owner: str, repo: str, ref: str,
                  read_fn, push_fn) -> tuple[bool, str]:
    """Fix the named manifest attribute. Only attributes in
    _MANIFEST_DEFAULTS are written; anything else is reported."""
    try:
        attr_m = re.search(r"(android:[a-zA-Z]+)", log)
        attr = attr_m.group(1) if attr_m else ""
        if not attr or attr not in _MANIFEST_DEFAULTS:
            named = attr or "?"
            return False, (f"AndroidManifest-e '{named}' attribute-er problem, "
                           "kintu er safe default ami janina — manifest-ta "
                           "nije khule attribute-ta thik koro.")
        for path in (_MANIFEST_PATH, "app/src/main/AndroidManifest.xml"):
            try:
                content, _sha = read_fn(owner, repo, path, ref)
            except Exception:
                content = None
            if not content or "<manifest" not in content:
                continue
            # The classic AGP failure: an <activity> with an intent-filter
            # and no android:exported. Add the attribute to its opening tag.
            fixed = content
            for tag_m in list(re.finditer(r"<activity\b[^>]*>", content)):
                tag = tag_m.group(0)
                if attr in tag:
                    continue
                close = content.find("</activity>", tag_m.end())
                block = content[tag_m.end():close if close != -1 else len(content)]
                if "<intent-filter" not in block:
                    continue
                new_tag = tag[:-1].rstrip() + f' {attr}="{_MANIFEST_DEFAULTS[attr]}">'
                fixed = fixed[:tag_m.start()] + new_tag + fixed[tag_m.end():]
                break
            if fixed != content:
                try:
                    res = push_fn(owner, repo, path, fixed,
                                  f"self-heal: add {attr} to manifest activity")
                except Exception as e:
                    return False, f"manifest fix push korte parlam na: {e}"
                if str(res or "").strip().startswith("✅"):
                    return True, (f"{path}-e activity-te {attr}="
                                  f"\"{_MANIFEST_DEFAULTS[attr]}\" bosiye "
                                  "dilam, tarpor abar build dilam.")
                return False, f"manifest fix push holo na: {_trunc(res, 200)}"
        return False, ("manifest-e intent-filter-wala activity pelam na — "
                       "AndroidManifest.xml nije khule dekho.")
    except Exception as e:
        return False, f"manifest fix korte parlam na: {e}"


def _fix_syntax(log: str, owner: str, repo: str, ref: str,
                read_fn, push_fn) -> tuple[bool, str]:
    """Only fix: a missing import for a KNOWN symbol. Anything else →
    file + line report, no edit."""
    try:
        sym_m = re.search(r"unresolved reference:\s*([A-Za-z_][A-Za-z0-9_]*)",
                          log, re.I)
        if not sym_m:
            sym_m = re.search(r"cannot find symbol\s*\n?\s*symbol:\s*"
                              r"(?:class|variable|method)\s+([A-Za-z_][A-Za-z0-9_]*)",
                              log, re.I)
        file_m = re.search(r"e:\s*(\S+\.(?:kt|java)):\s*\((\d+),\s*\d+\)", log)
        if not file_m:
            file_m = re.search(r"(\S+\.(?:kt|java)):(\d+):", log)
        file_path = ""
        line_no = ""
        if file_m:
            raw_path = file_m.group(1)
            line_no = file_m.group(2)
            # Repo-relative path: keep from app/ or src/ onward.
            for marker in ("app/", "src/"):
                idx = raw_path.find(marker)
                if idx != -1:
                    file_path = raw_path[idx:]
                    break
            else:
                file_path = raw_path.lstrip("/").split("/")[-1]
        symbol = sym_m.group(1) if sym_m else ""
        if not symbol:
            where = f"{file_path}:{line_no}" if file_path else "log-e"
            return False, (f"syntax error {where} — ki bhul bujhlam na, "
                           "file-ta khule nije thik koro.")
        fq = _KNOWN_IMPORTS.get(symbol)
        if not fq:
            where = f"{file_path}:{line_no}" if file_path else symbol
            return False, (f"'{symbol}'-r import ami chinina — {where}-e "
                           "error ache, file-ta khule nije import-ta bosao.")
        if not file_path:
            return False, (f"'{symbol}'-r import ({fq}) lagbe, kintu kon "
                           "file-e bujhlam na — log-e file-er naam dekho.")
        try:
            content, _sha = read_fn(owner, repo, file_path, ref)
        except Exception:
            content = None
        if not content:
            return False, (f"{file_path} repo-te pelam na — '{symbol}'-r "
                           f"import ({fq}) oi file-e bosate hobe.")
        if f"import {fq}" in content:
            return False, (f"{file_path}-e {fq} import already ache — "
                           "error-ta onno kichu, nije dekho.")
        pkg_m = re.search(r"^package\s+[^\n]+\n", content, re.M)
        new_content = (content[:pkg_m.end()] + f"import {fq}\n" + content[pkg_m.end():]
                       if pkg_m else f"import {fq}\n" + content)
        try:
            res = push_fn(owner, repo, file_path, new_content,
                          f"self-heal: add missing import {fq}")
        except Exception as e:
            return False, f"syntax fix push korte parlam na: {e}"
        if str(res or "").strip().startswith("✅"):
            return True, (f"{file_path}:{line_no}-e '{symbol}'-r missing "
                          f"import ({fq}) bosiye dilam, tarpor abar build dilam.")
        return False, f"syntax fix push holo na: {_trunc(res, 200)}"
    except Exception as e:
        return False, f"syntax fix korte parlam na: {e}"


def _fix_gradle_version(log: str, owner: str, repo: str, ref: str,
                        read_fn, push_fn) -> tuple[bool, str]:
    """Bump the Gradle wrapper to the version the log names (or a
    known-good one for the JDK). Returns (applied, message)."""
    try:
        target = ""
        m = re.search(r"minimum supported gradle version is\s+"
                      r"(\d+\.\d+(?:\.\d+)?)", log, re.I)
        if m:
            target = m.group(1)
        if not target:
            m = re.search(r"unsupported class file major version\s+(\d+)",
                          log, re.I)
            if m:
                target = _GRADLE_FOR_CLASS_MAJOR.get(int(m.group(1)), "8.7")
        if not target:
            m = re.search(r"requires gradle\s+(\d+\.\d+(?:\.\d+)?)", log, re.I)
            if m:
                target = m.group(1)
        if not target:
            target = "8.7"
        path = "gradle/wrapper/gradle-wrapper.properties"
        try:
            content, _sha = read_fn(owner, repo, path, ref)
        except Exception:
            content = None
        if not content or "distributionUrl" not in content:
            return False, ("Gradle wrapper-er properties file-ta repo-te "
                           "pelam na — gradle/wrapper/gradle-wrapper.properties "
                           f"khule distributionUrl-e Gradle {target} bosao.")
        new_content = re.sub(
            r"gradle-(\d+\.\d+(?:\.\d+)?)-bin\.zip",
            f"gradle-{target}-bin.zip", content, count=1)
        if new_content == content:
            return False, ("Gradle wrapper-e version-ta pelam na — "
                           "gradle-wrapper.properties nije khule dekho.")
        try:
            res = push_fn(owner, repo, path, new_content,
                          f"self-heal: bump Gradle wrapper to {target}")
        except Exception as e:
            return False, f"fix-ta push korte parlam na: {e}"
        if str(res or "").strip().startswith("✅"):
            return True, (f"Gradle wrapper {target}-e bump korlam, tarpor "
                          "abar build dilam.")
        return False, f"fix-ta push holo na: {_trunc(res, 200)}"
    except Exception as e:
        return False, f"gradle version fix korte parlam na: {e}"


def _fix_kotlin_version(log: str, owner: str, repo: str, ref: str,
                        read_fn, push_fn) -> tuple[bool, str]:
    """Pin the Kotlin version the log requires (version catalog first,
    then the root build file). Returns (applied, message)."""
    try:
        target = ""
        m = re.search(r"requires? kotlin[^\n]{0,60}?(\d+\.\d+(?:\.\d+)?)",
                      log, re.I)
        if m:
            target = m.group(1)
        if not target:
            target = "2.0.0"
        # 1) Version catalog.
        toml_path = "gradle/libs.versions.toml"
        try:
            content, _sha = read_fn(owner, repo, toml_path, ref)
        except Exception:
            content = None
        if content and re.search(r"kotlin\s*=\s*\"", content):
            new_content = re.sub(r'(kotlin\s*=\s*")[^"]+(")',
                                 rf"\g<1>{target}\g<2>", content, count=1)
            if new_content != content:
                try:
                    res = push_fn(owner, repo, toml_path, new_content,
                                  f"self-heal: pin Kotlin to {target}")
                except Exception as e:
                    return False, f"fix-ta push korte parlam na: {e}"
                if str(res or "").strip().startswith("✅"):
                    return True, (f"libs.versions.toml-e Kotlin {target} "
                                  "kore dilam, tarpor abar build dilam.")
                return False, f"fix-ta push holo na: {_trunc(res, 200)}"
        # 2) Root build file plugin version.
        for path in ("build.gradle.kts", "build.gradle"):
            try:
                content, _sha = read_fn(owner, repo, path, ref)
            except Exception:
                content = None
            if not content or "org.jetbrains.kotlin.android" not in content:
                continue
            kts_m = re.search(
                r'id\("org\.jetbrains\.kotlin\.android"\)\s+version\s+"[^"]+"',
                content)
            grv_m = None
            if not kts_m:
                grv_m = re.search(
                    r"id 'org\.jetbrains\.kotlin\.android'\s+version\s+'[^']+'",
                    content)
            m = kts_m or grv_m
            if not m:
                continue
            quote = '"' if kts_m else "'"
            if kts_m:
                repl = (f'id("org.jetbrains.kotlin.android") version '
                        f"{quote}{target}{quote}")
            else:
                repl = (f"id 'org.jetbrains.kotlin.android' version "
                        f"{quote}{target}{quote}")
            new_content = content[:m.start()] + repl + content[m.end():]
            try:
                res = push_fn(owner, repo, path, new_content,
                              f"self-heal: pin Kotlin plugin to {target}")
            except Exception as e:
                return False, f"fix-ta push korte parlam na: {e}"
            if str(res or "").strip().startswith("✅"):
                return True, (f"{path}-e Kotlin plugin {target} kore dilam, "
                              "tarpor abar build dilam.")
            return False, f"fix-ta push holo na: {_trunc(res, 200)}"
        return False, (f"Kotlin {target} lagbe, kintu version-ta kothay "
                       "bosabo pelam na — libs.versions.toml ba root "
                       "build file-e kotlin version-ta khule dekho.")
    except Exception as e:
        return False, f"kotlin version fix korte parlam na: {e}"


def _fix_dex(log: str, owner: str, repo: str, ref: str,
             read_fn, push_fn) -> tuple[bool, str]:
    """Enable multidex (64K methods). Returns (applied, message)."""
    try:
        for path in ("app/build.gradle.kts", "app/build.gradle"):
            try:
                content, _sha = read_fn(owner, repo, path, ref)
            except Exception:
                content = None
            if not content or "defaultConfig" not in content:
                continue
            if "multiDexEnabled" in content:
                return False, ("multiDex already ON ache — 64K error-ta "
                               "onno kichu theke asche, log-ta nije dekho.")
            is_kts = path.endswith(".kts")
            new_content = content
            dc_m = re.search(r"defaultConfig\s*\{", content)
            if not dc_m:
                continue
            insert_at = dc_m.end()
            new_content = (content[:insert_at] +
                           ("\n        multiDexEnabled = true" if is_kts
                            else "\n        multiDexEnabled true") +
                           content[insert_at:])
            dep_line = ('\n    implementation("androidx.multidex:multidex:2.0.1")'
                        if is_kts else
                        "\n    implementation 'androidx.multidex:multidex:2.0.1'")
            dep_m = re.search(r"dependencies\s*\{", new_content)
            if dep_m:
                new_content = (new_content[:dep_m.end()] + dep_line +
                               new_content[dep_m.end():])
            if new_content == content:
                continue
            try:
                res = push_fn(owner, repo, path, new_content,
                              "self-heal: enable multidex (64K)")
            except Exception as e:
                return False, f"fix-ta push korte parlam na: {e}"
            if str(res or "").strip().startswith("✅"):
                return True, (f"{path}-e multidex ON korlam "
                              "(multiDexEnabled + multidex lib), tarpor abar "
                              "build dilam.")
            return False, f"fix-ta push holo na: {_trunc(res, 200)}"
        return False, ("app/build.gradle(.kts)-e defaultConfig pelam na — "
                       "multidex nije on korte hobe.")
    except Exception as e:
        return False, f"dex fix korte parlam na: {e}"


def apply_fix(classified: dict, log_text: str, owner: str, repo: str,
              workflow: str, ref: str, read_fn, push_fn) -> tuple[bool, str]:
    """Apply the fix for a classified failure. (applied, message).
    Returns (False, reason) for every not-auto-fixable class — those never
    touch the repo. Never raises."""
    try:
        cls = str((classified or {}).get("class") or "unknown")
        if cls == "missing_secret":
            return False, ("secret/keystore missing — ami nije secret banate "
                           "parbo na. GitHub repo Settings > Secrets-e "
                           "secret-ta bosao, tarpor abar build dao.")
        if cls == "auth":
            return False, ("GitHub token / permission problem — token-ta "
                           "thik ache kina dekho, tarpor abar build dao.")
        if cls == "unknown":
            return False, ("error-ta amar chena class-er baire — ki bhul "
                           "bujhte parlam na, log-ta nije dekho.")
        if cls == "transient":
            return True, "network/transient mone hocche — kichu na bodle abar build dilam."
        if cls == "gradle_version":
            return _fix_gradle_version(log_text, owner, repo, ref,
                                       read_fn, push_fn)
        if cls == "kotlin_version":
            return _fix_kotlin_version(log_text, owner, repo, ref,
                                       read_fn, push_fn)
        if cls == "dex":
            return _fix_dex(log_text, owner, repo, ref, read_fn, push_fn)
        if cls == "resource":
            return False, ("resource error — AAPT linking fail holo, kono "
                           "resource missing ba duplicate. Kon file-e ki "
                           "missing log-e lekha ache — oi resource-ta (layout / "
                           "drawable / string) repo-te bosao, tarpor abar "
                           "build dao.")
        if cls == "sdk":
            return False, ("Android SDK pelam na — runner-e SDK setup lagbe. "
                           "Workflow file-e setup-android step ache kina dekho "
                           "(actions/setup-java + android-sdk), ba ANDROID_HOME "
                           "set koro, tarpor abar build dao.")
        if cls == "dependency":
            return _fix_dependency(log_text, owner, repo, workflow, ref,
                                   read_fn, push_fn)
        if cls == "manifest":
            return _fix_manifest(log_text, owner, repo, ref, read_fn, push_fn)
        if cls == "syntax":
            return _fix_syntax(log_text, owner, repo, ref, read_fn, push_fn)
        return False, f"'{cls}' class-er fix ami janina — log-ta nije dekho."
    except Exception as e:
        return False, f"fix apply korte parlam na: {e}"


# ── the self-healing build ───────────────────────────────────────────────────

def build_apk_selfheal(repo: str, workflow: str, ref: str = "main",
                       max_attempts: int = 3, request_fn=None,
                       dispatch_fn=None, log_fn=None, read_fn=None,
                       push_fn=None, sleep_fn=None, poll_interval_s: int = _POLL_INTERVAL_S,
                       max_polls: int = _MAX_POLLS) -> str:
    """Dispatch an APK build, poll it, and on failure fix the problem and
    rebuild — up to `max_attempts` dispatches (hard cap 3 by default).
    Returns a plain-words report. Never raises."""
    try:
        repo = (repo or "").strip()
        workflow = (workflow or "").strip()
        ref = (ref or "main").strip()
        attempts = max(1, min(int(max_attempts or 3), 3))
        if "/" not in repo:
            return "Repo-ta owner/name akare dao, jemon dbibi698-commits/jarvis-backend."
        owner, name = repo.split("/", 1)
        if not owner or not name or not workflow:
            return "owner, repo ar workflow file — tintei lagbe."
        req = request_fn or _http
        disp = dispatch_fn or _default_dispatch
        logf = log_fn or _default_log
        sleep = sleep_fn or time.sleep

        def _read(o, r, p, rf):
            return _default_read(o, r, p, rf, req)

        readf = read_fn or _read
        pushf = push_fn or _default_push

        if dispatch_fn is None and not _github_token():
            return ("GitHub token set kora nei — Plugin Settings > 🔗 CONNECTORS > "
                    "GitHub token-e PAT bosao, tarpor abar bolo.")

        lines = [f"APK self-heal — {owner}/{name} ({workflow} @ {ref}):"]
        for attempt in range(1, attempts + 1):
            try:
                disp_result = disp(owner, name, workflow, ref)
            except Exception as e:
                disp_result = f"Dispatch korte parlam na: {e}"
            if not _dispatch_ok(disp_result):
                cls = classify_failure(str(disp_result))
                lines.append(f"• Attempt {attempt}: dispatch holo na — "
                             f"{_trunc(disp_result, 200)}")
                if cls.get("class") == "transient" and attempt < attempts:
                    lines.append("  Fix: transient mone hocche — abar dispatch korchi.")
                    continue
                lines.append(f"  Stop: {_CLASS_LABEL.get(cls.get('class'), 'unknown')} — "
                             "abar dispatch kore labh nei.")
                lines.append(f"Final: build holo na ({attempt}/{attempts} attempt).")
                return "\n".join(lines)
            lines.append(f"• Attempt {attempt}: build dispatch holo — run-er "
                         f"jonno wait korchi…")
            try:
                run, note = _poll_run(owner, name, workflow, ref, req, sleep,
                                      poll_interval_s, max_polls)
            except Exception as e:
                run, note = None, f"poll korte parlam na: {e}"
            if run is None:
                lines.append(f"  Run pelam na ({note}) — "
                             "GitHub Actions page-e dekho run-ta elo kina.")
                if attempt < attempts:
                    lines.append("  Fix: transient mone hocche — abar dispatch korchi.")
                    continue
                lines.append(f"Final: build-er run pelam na ({attempt}/{attempts} attempt).")
                return "\n".join(lines)
            conclusion = str(run.get("conclusion") or "").lower()
            status = str(run.get("status") or "")
            run_url = str(run.get("html_url") or "")
            if status == "completed" and conclusion == "success":
                lines.append(f"• Attempt {attempt}: ✅ build success holo!"
                             + (f" Run: {run_url}" if run_url else ""))
                lines.append(f"Final: APK build holo — attempt {attempt}/{attempts}. "
                             "GitHub Actions page-e APK artifact pabe.")
                return "\n".join(lines)
            if status != "completed":
                lines.append(f"  Run sesh holo na ({note or status}) — "
                             "GitHub Actions page-e status dekho.")
                if attempt < attempts:
                    continue
                lines.append(f"Final: build sesh holo na ({attempt}/{attempts} attempt).")
                return "\n".join(lines)
            # Failed run — fetch the log tail, classify, fix or stop.
            try:
                log_text = _fetch_log_tail(owner, name, run, req, logf)
            except Exception:
                log_text = ""
            cls = classify_failure(log_text)
            label = _CLASS_LABEL.get(cls.get("class"), "unknown build error")
            lines.append(f"• Attempt {attempt}: build fail holo — {label}.")
            if cls.get("detail"):
                lines.append(f"  Log: {_trunc(cls['detail'], 200)}")
            if not cls.get("auto_fixable"):
                _ok, why = apply_fix(cls, log_text, owner, name, workflow, ref,
                                     readf, pushf)
                lines.append(f"  Stop: {why}")
                lines.append(f"Final: build holo na ({attempt}/{attempts} attempt) — "
                             "uporer kotha moto thik kore abar build dao.")
                return "\n".join(lines)
            try:
                applied, fix_msg = apply_fix(cls, log_text, owner, name, workflow,
                                             ref, readf, pushf)
            except Exception as e:
                applied, fix_msg = False, f"fix apply korte parlam na: {e}"
            lines.append(f"  Fix: {fix_msg}")
            if not applied:
                lines.append(f"Final: build holo na ({attempt}/{attempts} attempt) — "
                             "fix-ta apply holo na, tai ar rebuild korlam na.")
                return "\n".join(lines)
            if attempt >= attempts:
                lines.append(f"Final: {attempts} bar try korlam, fix diyeo "
                             "build holo na — log-ta nije dekho, ba amake log-ta dao.")
                return "\n".join(lines)
            lines.append("  Abar build dicchi…")
        lines.append(f"Final: {attempts} bar try korlam, build holo na.")
        return "\n".join(lines)
    except Exception as e:
        return f"APK self-heal chalate parlam na: {e}"
