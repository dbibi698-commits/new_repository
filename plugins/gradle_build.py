"""plugins/gradle_build.py — 🛠️ GRADLE / KOTLIN: Android app likhe build koro.

Mark writes the Android project (build.gradle.kts + Kotlin MainActivity +
manifest + settings + Gradle wrapper) into a folder, pushes it to a GitHub
repo when asked, and triggers the GitHub Actions build through the
self-healing APK builder (poll → classify → fix → rebuild, max 3
attempts). When this PC has Java + Gradle (or a gradlew wrapper), a local
`gradlew assembleDebug` is also offered — otherwise it says plainly that
the local toolchain is missing and the Actions path is the way.

Call when the user asks: gradle/kotlin diye android app banao, build.gradle
likho, kotlin code likho, apk build koro, local gradle build koro.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN = {
    "name": "gradle_build",
    "description": (
        "Write an Android app with Gradle/Kotlin — build.gradle.kts + "
        "Kotlin MainActivity + manifest + settings into a folder, push it "
        "to a GitHub repo, and build the APK on GitHub Actions with "
        "self-healing (auto-fix on failure). Also runs a local Gradle build "
        "when Java + Gradle exist on this PC. Call when the user asks: "
        "gradle build, kotlin app banao, android project likho, apk build koro."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "folder": {"type": "STRING",
                       "description": "Folder to write the Android project into."},
            "package": {"type": "STRING",
                        "description": "App package, e.g. com.example.myapp."},
            "app_name": {"type": "STRING",
                         "description": "App display name."},
            "kotlin_code": {"type": "STRING",
                            "description": "Full MainActivity.kt contents "
                                           "(empty = default template)."},
            "repo": {"type": "STRING",
                     "description": "GitHub repo owner/name to push + build "
                                    "(empty = local folder only)."},
            "workflow": {"type": "STRING",
                         "description": "Workflow file for the Actions build, "
                                        "e.g. build-apk.yml."},
            "local": {"type": "BOOLEAN",
                      "description": "True = also try a local Gradle build "
                                     "on this PC (needs Java + Gradle)."},
        },
        "required": [],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Write scaffold → (push) → (Actions build) → (local build).
    Returns a short string, never raises."""
    try:
        params = parameters or {}
        folder = str(params.get("folder") or "").strip()
        if not folder:
            return ("Folder-er path dao — Android project-ta kothay likhbo? "
                    "(jemon C:\\Users\\...\\my-app)")
        from core import gradle_build as _gb
        parent = Path(folder).expanduser().parent
        if not parent.is_dir():
            return (f"Folder-ta pelam na: {folder} — parent folder-ta "
                    f"({parent}) nei, age folder-ta banao.")
        ok, msg, _files = _gb.write_android_scaffold(
            folder,
            package=str(params.get("package") or "com.example.app"),
            app_name=str(params.get("app_name") or "My App"),
            kotlin_code=str(params.get("kotlin_code") or ""))
        if not ok:
            return msg
        lines = [msg]
        repo = str(params.get("repo") or "").strip()
        workflow = str(params.get("workflow") or "").strip()
        if repo:
            owner, _, name = repo.partition("/")
            if owner and name:
                lines.append(_gb.push_scaffold_to_repo(owner, name, folder))
            else:
                lines.append("Repo-ta owner/name akare dao — push holo na.")
        if repo and workflow:
            lines.append(_gb.build_android(repo, workflow))
        elif repo and not workflow:
            lines.append("Workflow file dao (jemon build-apk.yml) — tahole "
                         "GitHub Actions-e build dibo.")
        if params.get("local"):
            lines.append(_gb.local_gradle_build(folder))
        return "\n\n".join(lines)
    except Exception as e:
        return f"Gradle build korte parlam na: {e}"
