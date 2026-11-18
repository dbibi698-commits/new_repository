"""core/exe_package.py — 📦 What goes into the Mark-LVII EXE package.

The chrome-extension/ directory is EXCLUDED from the EXE (standing
user rule: the product talks only about direct browser control, and
the word must not ship inside the EXE either). Secrets are excluded
too — config/api_keys.json and config/jarvis_link.json never ship.

``EXCLUDES`` is the single source of truth: the EXE build (rsync)
and the tests both read it, so the package cannot drift from the rule.
"""
from __future__ import annotations

import os

# rsync-style excludes, relative to the project root.
EXCLUDES = (
    "python/",
    "__pycache__/",
    "chrome-extension/",   # standing rule: never ships in the EXE
    "config/jarvis_link.json",
    "config/api_keys.json",
    ".git/",
    "*.pyc",
)


def is_excluded(rel_path: str) -> bool:
    """True when ``rel_path`` (project-relative, '/' separators) must
    NOT go into the EXE package."""
    rel = (rel_path or "").replace(os.sep, "/").strip("/")
    if not rel:
        return False
    for pat in EXCLUDES:
        if pat.endswith("/"):
            # Directory exclude: the dir itself or anything under it.
            if rel == pat.rstrip("/") or rel.startswith(pat):
                return True
        elif pat.startswith("*."):
            if rel.endswith(pat[1:]):
                return True
        elif rel == pat:
            return True
    return False


def package_files(root: str) -> list[str]:
    """Project-relative paths that WOULD go into the EXE (excludes
    applied). Never raises; unreadable dirs are skipped."""
    out: list[str] = []
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
            if rel_dir == ".":
                rel_dir = ""
            # Prune excluded dirs so walk never descends into them.
            dirnames[:] = [
                d for d in dirnames
                if not is_excluded((rel_dir + "/" + d).strip("/"))]
            for name in filenames:
                rel = (rel_dir + "/" + name).strip("/") if rel_dir else name
                if not is_excluded(rel):
                    out.append(rel)
    except Exception:
        pass
    return sorted(out)


def rsync_exclude_args() -> list[str]:
    """``--exclude`` args for the rsync build command."""
    return [f"--exclude={pat}" for pat in EXCLUDES]
