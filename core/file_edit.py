"""core/file_edit.py — ✏️ FILE EDIT tool (PC files, safe by design).

- edit_file(path, old, new): replaces ONE exact occurrence of `old` in a
  text file, shows a unified diff FIRST, keeps a `.bak` backup, and only
  writes when `confirmed=True` (the plugin asks the user / the confirm
  gate first). Never overwrites blindly, never writes binary files.
- preview_diff(path, old, new): the diff text without touching anything.
- append_file(path, text): appends lines (also backed up + confirmed).
- read_snippet(path, start, lines): read a window of a file.

Guard rails (honest, plain): refuses to touch config/api_keys.json,
config/jarvis_link.json and any .bak file itself; refuses binary files;
refuses to replace when the old text appears 0 or 2+ times (ambiguous).
Everything returns a short string and never raises.
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path

_PROTECTED = {"api_keys.json", "jarvis_link.json"}


def _resolve(path: str) -> tuple[Path | None, str]:
    p = Path(str(path or "").strip()).expanduser()
    if not str(path or "").strip():
        return None, "File-er path dao."
    if p.name in _PROTECTED:
        return None, (f"⚠️ {p.name} — ei file-ta edit kora jabe na "
                      "(keys/secrets thake). Settings theke bodlao.")
    if p.suffix.lower() == ".bak":
        return None, "⚠️ .bak backup file edit kora jabe na."
    return p, ""


def _is_text(p: Path) -> bool:
    try:
        with open(p, "rb") as f:
            chunk = f.read(8192)
        if b"\x00" in chunk:
            return False
        chunk.decode("utf-8")
        return True
    except Exception:
        return False


def preview_diff(path: str, old: str, new: str) -> str:
    """Unified diff of the planned edit, without writing anything."""
    try:
        p, err = _resolve(path)
        if p is None:
            return err
        if not p.is_file():
            return f"File-ta pelam na: {p}"
        if not _is_text(p):
            return "⚠️ Binary file — edit korbo na."
        text = p.read_text(encoding="utf-8", errors="replace")
        old_s, new_s = str(old or ""), str(new or "")
        if not old_s:
            return "Ki bodlabo — purono text dao."
        count = text.count(old_s)
        if count == 0:
            return (f"⚠️ Purono text-ta file-e pelam na — kichu bodlai ni.\n"
                    f"File: {p}")
        if count > 1:
            return (f"⚠️ Purono text-ta {count} bar ache — konta bodlabo "
                    f"bujhte parlam na. Aro nirdisto text dao.")
        new_text = text.replace(old_s, new_s, 1)
        diff = difflib.unified_diff(
            text.splitlines(), new_text.splitlines(),
            fromfile=f"a/{p.name}", tofile=f"b/{p.name}", lineterm="")
        body = "\n".join(list(diff)[:80])
        return (f"✏️ Diff preview — {p}:\n{body}\n"
                f"(Confirm korle .bak backup rekhe save korbo.)")
    except Exception as e:
        return f"Diff dekhte parlam na: {e}"


def edit_file(path: str, old: str, new: str, confirmed: bool = False) -> str:
    """Replace one exact occurrence. Shows the diff and stops unless
    confirmed=True. Keeps a .bak backup before writing."""
    try:
        if not confirmed:
            return (preview_diff(path, old, new)
                    + "\n\n⚠️ Save korte 'confirm' bolo — nahole kichu "
                      "likhbo na.")
        p, err = _resolve(path)
        if p is None:
            return err
        if not p.is_file():
            return f"File-ta pelam na: {p}"
        if not _is_text(p):
            return "⚠️ Binary file — edit korbo na."
        text = p.read_text(encoding="utf-8", errors="replace")
        old_s, new_s = str(old or ""), str(new or "")
        count = text.count(old_s)
        if count == 0:
            return "⚠️ Purono text-ta pelam na — kichu bodlai ni."
        if count > 1:
            return (f"⚠️ Purono text-ta {count} bar ache — konta bodlabo "
                    "bujhte parlam na.")
        bak = p.with_suffix(p.suffix + ".bak")
        bak.write_text(text, encoding="utf-8")
        p.write_text(text.replace(old_s, new_s, 1), encoding="utf-8")
        return (f"✏️ Edit holo: {p}\n"
                f"Backup: {bak} (vul hole restore korte bolle fire pabe.)")
    except Exception as e:
        return f"Edit korte parlam na: {e}"


def append_file(path: str, text: str, confirmed: bool = False) -> str:
    """Append lines to a text file (backup first, confirm first)."""
    try:
        if not confirmed:
            return (f"✏️ Append preview — {path}:\n"
                    f"+ {str(text or '')[:500]}\n\n"
                    f"⚠️ Save korte 'confirm' bolo.")
        p, err = _resolve(path)
        if p is None:
            return err
        if not p.is_file():
            return f"File-ta pelam na: {p}"
        if not _is_text(p):
            return "⚠️ Binary file — edit korbo na."
        old = p.read_text(encoding="utf-8", errors="replace")
        bak = p.with_suffix(p.suffix + ".bak")
        bak.write_text(old, encoding="utf-8")
        with open(p, "a", encoding="utf-8") as f:
            f.write(str(text or "") + ("\n" if not str(text or "").endswith("\n") else ""))
        return f"✏️ Append holo: {p} (backup: {bak})"
    except Exception as e:
        return f"Append korte parlam na: {e}"


def read_snippet(path: str, start: int = 1, lines: int = 20) -> str:
    """Read a window of a text file. Never raises."""
    try:
        p, err = _resolve(path)
        if p is None:
            return err
        if not p.is_file():
            return f"File-ta pelam na: {p}"
        if not _is_text(p):
            return "⚠️ Binary file — porte parbo na."
        all_lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        s = max(1, int(start or 1))
        n = max(1, min(int(lines or 20), 100))
        window = all_lines[s - 1:s - 1 + n]
        if not window:
            return f"File-ta {len(all_lines)} line — {s} number line nei."
        out = [f"📄 {p} — line {s}-{s + len(window) - 1} / {len(all_lines)}:"]
        for i, line in enumerate(window, s):
            out.append(f"{i:>5} | {line[:200]}")
        return "\n".join(out)
    except Exception as e:
        return f"File porte parlam na: {e}"
