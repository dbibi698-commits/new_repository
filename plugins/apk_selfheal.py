"""plugins/apk_selfheal.py — Self-healing APK build plugin.

"apk_build_selfheal" — dispatch an APK build on GitHub Actions, watch it,
and if it fails, fix the problem itself and rebuild (up to 3 attempts).
Use this instead of plain `build_apk` when a build has already failed, or
when you want Mark to keep trying instead of stopping at the first error.

A build takes minutes, so run() starts the work on a background thread and
returns at once; the result lands in the activity log / content panel.
Never raises. No Qt here.
"""
from __future__ import annotations

import threading

PLUGIN = {
    "name": "apk_build_selfheal",
    "description": (
        "Build an Android APK on GitHub Actions WITH self-healing: if the "
        "build fails, Mark reads the failing log, fixes the known problem "
        "itself (dependency version, AndroidManifest attribute, missing "
        "import, or a transient retry) and rebuilds, up to 3 attempts. "
        "Use when a build failed, or when asked to build an APK and fix it "
        "if it breaks. Do NOT use for a plain first-time build — that is "
        "build_apk. Needs repo as owner/name and the workflow file."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "repo": {"type": "STRING",
                     "description": "GitHub repo as owner/name, e.g. dbibi698-commits/jarvis-backend"},
            "workflow": {"type": "STRING",
                         "description": "Workflow file, e.g. build-apk.yml"},
            "ref": {"type": "STRING",
                    "description": "Branch or tag to build (default: main)"},
        },
        "required": ["repo", "workflow"],
    },
}


def _run_bg(repo: str, workflow: str, ref: str, player) -> None:
    """Background worker: the self-heal can take minutes (polling)."""
    try:
        from core import apk_selfheal
        result = apk_selfheal.build_apk_selfheal(repo, workflow, ref=ref)
    except Exception as e:
        result = f"APK self-heal chalate parlam na: {e}"
    if player:
        try:
            player.write_log(f"JARVIS: {result}")
        except Exception:
            pass
        try:
            player.show_content("APK self-heal", result)
        except Exception:
            pass


def run(parameters: dict, player=None, session_memory=None) -> str:
    parameters = parameters or {}
    repo = str(parameters.get("repo") or "").strip()
    workflow = str(parameters.get("workflow") or "").strip()
    ref = str(parameters.get("ref") or "main").strip() or "main"
    if not repo or not workflow:
        return "APK self-heal-er jonno repo (owner/name) ar workflow file — duitoi dao."
    try:
        threading.Thread(target=_run_bg, args=(repo, workflow, ref, player),
                         daemon=True, name="apk-selfheal").start()
    except Exception as e:
        return f"APK self-heal start korte parlam na: {e}"
    result = (f"APK self-heal cholche — {repo} ({workflow} @ {ref}): build "
              "dispatch kore wait korchi; fail hole nije fix kore abar build "
              "debo (max 3 bar). Sesh hole ekhane janabo.")
    if player:
        try:
            player.write_log(f"JARVIS: {result}")
        except Exception:
            pass
    return result
