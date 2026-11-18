"""core/file_organizer.py — 🗂️ FILE ORGANIZER: folder sajano.

Sorts a folder's files into subfolders by type (Images, Documents,
Videos, Audio, Archives, Code, Other). DRY-RUN IS THE DEFAULT: the
first run only shows the preview — nothing moves until the user says
so (dry_run=False). Real moves only, never a fake "organized" message.
No Qt, no network. Every public function returns a plain value and never
raises.
"""
from __future__ import annotations

from pathlib import Path

_CATEGORIES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg",
               ".heic", ".tiff"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt",
                  ".xls", ".xlsx", ".csv", ".ppt", ".pptx"},
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"},
    "Audio": {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"},
    "Archives": {".zip", ".7z", ".rar", ".tar", ".gz"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".java",
             ".kt", ".c", ".cpp"},
}


def category_for(path: Path) -> str:
    """Which subfolder a file belongs in. Pure. Never raises."""
    try:
        ext = str(path.suffix or "").lower()
        for name, exts in _CATEGORIES.items():
            if ext in exts:
                return name
        return "Other"
    except Exception:
        return "Other"


def plan_folder(folder: str) -> dict:
    """Preview the moves without moving anything. Returns {ok, folder,
    moves: [{file, dest}], skipped, error}. Never raises."""
    try:
        root = Path(str(folder or "").strip()).expanduser()
        if not root.is_dir():
            return {"ok": False, "folder": str(folder or ""),
                    "moves": [], "skipped": 0,
                    "error": f"Folder-ta pelam na: {folder or '(khali)'}"}
        moves: list[dict] = []
        skipped = 0
        for p in sorted(root.iterdir()):
            if not p.is_file():
                skipped += 1
                continue
            if p.name.startswith("."):
                skipped += 1
                continue
            dest = root / category_for(p) / p.name
            if dest == p:
                skipped += 1
                continue
            moves.append({"file": p.name, "dest": str(dest.relative_to(root)),
                          "category": category_for(p)})
        return {"ok": True, "folder": str(root), "moves": moves,
                "skipped": skipped, "error": ""}
    except Exception as e:
        return {"ok": False, "folder": str(folder or ""), "moves": [],
                "skipped": 0, "error": f"Folder dekhte parlam na: {e}"}


def organize_folder(folder: str, dry_run: bool = True) -> dict:
    """Dry-run (default): preview only. dry_run=False: move the files for
    real. Returns {ok, folder, moved, planned, error}. Never raises."""
    try:
        plan = plan_folder(folder)
        if not plan.get("ok"):
            return {"ok": False, "folder": plan.get("folder", ""),
                    "moved": 0, "planned": 0, "error": plan.get("error", "")}
        moves = plan["moves"]
        if dry_run:
            return {"ok": True, "folder": plan["folder"], "moved": 0,
                    "planned": len(moves), "moves": moves,
                    "error": "", "dry_run": True}
        root = Path(plan["folder"])
        moved = 0
        failed: list[str] = []
        for m in moves:
            src = root / m["file"]
            dest = root / m["dest"]
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists() and dest != src:
                    # Never overwrite — keep both, numbered.
                    stem, suffix = dest.stem, dest.suffix
                    n = 2
                    while (dest.parent / f"{stem} ({n}){suffix}").exists():
                        n += 1
                    dest = dest.parent / f"{stem} ({n}){suffix}"
                src.rename(dest)
                moved += 1
            except Exception as e:
                failed.append(f"{m['file']} ({e})")
        return {"ok": True, "folder": plan["folder"], "moved": moved,
                "planned": len(moves), "moves": moves,
                "error": ("Kichu file sorate parlam na: " + "; ".join(failed[:3])
                          if failed else ""), "dry_run": False}
    except Exception as e:
        return {"ok": False, "folder": str(folder or ""), "moved": 0,
                "planned": 0, "error": f"Folder sajate parlam na: {e}"}


def organize_text(folder: str, dry_run: bool = True) -> str:
    """One plain-words string for chat / cards. Never raises."""
    try:
        res = organize_folder(folder, dry_run=dry_run)
        if not res.get("ok"):
            return f"🗂️ File Organizer — {res.get('error', '')}"
        moves = res.get("moves") or []
        if not moves:
            return (f"🗂️ File Organizer — {res.get('folder')} already sajano, "
                    "sorabar moto file pelam na.")
        lines = [f"🗂️ File Organizer — {res.get('folder')}:"]
        by_cat: dict[str, int] = {}
        for m in moves:
            by_cat[m["category"]] = by_cat.get(m["category"], 0) + 1
        for cat, n in sorted(by_cat.items()):
            lines.append(f"  • {cat}: {n} ta file")
        if res.get("dry_run"):
            lines.append("👀 Eta sudhu preview — kichu sorai ni. Sotti "
                         "sorate hole 'organize koro' bolo.")
        else:
            lines.append(f"✅ {res.get('moved', 0)} ta file soralam.")
        return "\n".join(lines)
    except Exception as e:
        return f"File Organizer chalate parlam na: {e}"
