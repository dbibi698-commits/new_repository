"""core/auto_push.py — 🚀 AUTO-PUSH built software to GitHub.

After a successful build + test, push the built project to GitHub:
  - via the SAVED GitHub token (config api_keys.json -> github_token)
    using connectors.github_push_file / github_create_repo (Contents API)
  - or the browser flow (GitHub web UI, mouse-driven) when no token
    exists — the user is told plainly which path ran.

One-tap via auto_push_project(); automatic when the Settings toggle
`auto_push_enabled` is ON (Software Builder box). Reports the repo URL
on success, or the exact reason it stopped. Never raises, never pushes
without a token OR the browser flow, never includes secrets (config/,
__pycache__, .env, *.key, api_keys.json are skipped).

The repo name is derived from the project name (sanitised) unless the
caller passes one.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from memory.config_manager import get_plugin_config, save_plugin_config

_NS = "auto_push"

_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules",
              "config", ".idea", ".vscode"}
_SKIP_SUFFIX = {".pyc", ".pyo", ".log", ".key", ".pem", ".env"}
_SKIP_NAMES = {"api_keys.json", "jarvis_link.json", ".env"}


def auto_push_enabled() -> bool:
    try:
        return bool((get_plugin_config(_NS) or {}).get("auto_push_enabled"))
    except Exception:
        return False


def set_auto_push(enabled: bool) -> str:
    try:
        cfg = dict(get_plugin_config(_NS) or {})
        cfg["auto_push_enabled"] = bool(enabled)
        save_plugin_config(_NS, cfg)
        return ("🚀 Auto-push " + ("ON holo — build shesh hole GitHub-e "
                                    "push korbo (token thakle)." if enabled
                                    else "OFF holo — push korbo na."))
    except Exception as e:
        return f"Auto-push setting bodlate parlam na: {e}"


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(name or "mark-project").strip())
    s = s.strip("-._") or "mark-project"
    return s[:100]


def _collect_files(folder: Path, cap_files: int = 200,
                   cap_bytes: int = 5 * 1024 * 1024) -> list[tuple[str, bytes]]:
    """Walk a project folder, skipping secrets/build junk. Returns
    [(repo_path, bytes)]. Never raises."""
    out: list[tuple[str, bytes]] = []
    total = 0
    try:
        for p in sorted(folder.rglob("*")):
            if len(out) >= cap_files or total >= cap_bytes:
                break
            if not p.is_file():
                continue
            if any(part in _SKIP_DIRS for part in p.parts):
                continue
            if p.name in _SKIP_NAMES or p.suffix.lower() in _SKIP_SUFFIX:
                continue
            try:
                data = p.read_bytes()
            except Exception:
                continue
            if len(data) > 1 * 1024 * 1024:
                continue
            out.append((str(p.relative_to(folder)).replace("\\", "/"), data))
            total += len(data)
    except Exception:
        pass
    return out


def auto_push_project(folder: str, repo_name: str = "",
                      private: bool = True, create_if_missing: bool = True,
                      push_via_browser=None) -> str:
    """Push a built project to GitHub. Returns the repo URL or a plain
    reason it stopped. Never raises."""
    try:
        root = Path(str(folder or "").strip()).expanduser()
        if not root.is_dir():
            return f"Project folder-ta pelam na: {root}"
        files = _collect_files(root)
        if not files:
            return ("🚀 Push korar moto file pelam na — folder-ta khali ba "
                    "sudhu secret/build file ache.")
        from core import connectors as _c
        token = _c._token("github_token", None)
        repo = _slug(repo_name or root.name)
        if token:
            owner = ""
            try:
                # Who owns the token? /user via the connector's request.
                st, data, _err = _c._req(
                    "GET", "https://api.github.com/user",
                    headers={"Authorization": f"Bearer {token}"})
                if st == 200 and isinstance(data, dict):
                    owner = str(data.get("login") or "")
            except Exception:
                owner = ""
            if not owner:
                return ("🚀 GitHub token-ta kaj korche na (401) — push "
                        "holo na. Settings-e notun token dao.")
            if create_if_missing:
                created = _c.github_create_repo(
                    token, repo, description=f"Built by Mark-LVII on "
                    f"{datetime.now():%Y-%m-%d}", private=bool(private))
                created_s = str(created or "")
                if created_s.startswith("✅"):
                    pass  # created fine
                elif "already ache" in created_s:
                    pass  # fine — push into the existing repo
                else:
                    return f"🚀 Repo banate parlam na: {created_s[:300]}"
            pushed, failed = 0, 0
            for rel, data in files:
                try:
                    res = _c.github_push_file(token, owner, repo, rel,
                                              data.decode("utf-8", "replace"),
                                              f"Mark-LVII auto-push: {rel}")
                    if isinstance(res, str) and res.startswith("✅"):
                        pushed += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
            url = f"https://github.com/{owner}/{repo}"
            if pushed == 0:
                return (f"🚀 Push holo na — {failed} ta file fail holo. "
                        f"Repo: {url}")
            return (f"🚀 GitHub-e push holo: {url} "
                    f"({pushed} ta file, {failed} ta fail)")
        # No token — browser flow (if the caller wired one).
        if push_via_browser is not None:
            try:
                res = push_via_browser(repo, files)
                return str(res or "Browser flow diye push korar chesta korlam.")
            except Exception as e:
                return f"🚀 Browser flow-e push holo na: {e}"
        return ("🚀 Auto-push holo na — GitHub token set kora nei "
                "(Settings > 🔗 CONNECTORS > GitHub token). Token dile "
                "abar bolo, ba browser flow diye push korbo.")
    except Exception as e:
        return f"Auto-push korte parlam na: {e}"
