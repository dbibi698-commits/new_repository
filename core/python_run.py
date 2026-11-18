"""core/python_run.py — 🐍 PYTHON RUN: run Python code directly on this PC.

Mark IS Python, so this is the direct path — no API, no bridge, no upload:
paste a snippet and it runs here with the bundled Python, or point at a
project folder and its main.py runs (with a venv + requirements.txt install
first, best-effort). Big projects are fine — there is no size cap on the PC.

SAFETY (the user's own code on their own PC):
  * Only the user's own code runs — code the user pasted, code from the
    user's own project folder, or code the paired phone sends through the
    Jarvis Link relay (the inbox loop only processes messages for THIS
    paired PC). Code from a stranger is never executed.
  * Every run has a timeout (snippet 60 s default, project 300 s default)
    and a capped output (8 000 chars per stream) so a runaway print loop
    can never flood the chat or hang the app.
  * Runs as the user's own process (sys.executable) in a temp dir (snippet)
    or in the project folder — no sandbox is claimed, and none is needed:
    this is the user's own machine and their own code.

Every public function returns a plain-words string (or a dict for the
structured one) and never raises. No Qt anywhere — worker threads only.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_DEFAULT_TIMEOUT_S = 60
_MAX_TIMEOUT_S = 300
_PROJECT_TIMEOUT_S = 300
_MAX_PROJECT_TIMEOUT_S = 900
_MAX_OUT_CHARS = 8000
_VENV_TIMEOUT_S = 120
_PIP_TIMEOUT_S = 180

_PHONE_PREFIX = "PYTHON_RUN::"


# ── small utilities (never raise) ────────────────────────────────────────────

def _trunc(text: str, limit: int = _MAX_OUT_CHARS) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…(output {limit} char-e kata holo, mool {len(text)} char chilo)"


def _python_exe() -> str:
    """The Python running this app (the bundled one in the EXE)."""
    return sys.executable or "python"


def python_version() -> str:
    """e.g. '3.12.8'. Never raises."""
    try:
        return sys.version.split()[0]
    except Exception:
        return "?"


def _run(argv: list[str], cwd: str | Path | None, timeout: int,
         env: dict | None = None) -> dict:
    """Run argv, capture output. Returns {ok, stdout, stderr, exit_code,
    timed_out, elapsed_s}. Never raises."""
    started = time.time()
    try:
        r = subprocess.run(
            [str(a) for a in argv], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=max(1, int(timeout)),
            cwd=str(cwd) if cwd else None, env=env)
        return {"ok": r.returncode == 0,
                "stdout": r.stdout or "", "stderr": r.stderr or "",
                "exit_code": r.returncode, "timed_out": False,
                "elapsed_s": round(time.time() - started, 1)}
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        return {"ok": False, "stdout": out, "stderr": err,
                "exit_code": -1, "timed_out": True,
                "elapsed_s": round(time.time() - started, 1)}
    except FileNotFoundError:
        return {"ok": False, "stdout": "", "stderr": "",
                "exit_code": -1, "timed_out": False,
                "elapsed_s": round(time.time() - started, 1),
                "missing": True}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e),
                "exit_code": -1, "timed_out": False,
                "elapsed_s": round(time.time() - started, 1)}


def _format(res: dict, timeout: int, what: str = "Code") -> str:
    """Structured run result → plain-words string. Never raises."""
    try:
        if res.get("missing"):
            return (f"{what} chalate parlam na — Python interpreter pelam na "
                    "ei PC-te.")
        if res.get("timed_out"):
            tail = ""
            if res.get("stdout"):
                tail = "\nOutput (timeout-er age):\n" + _trunc(res["stdout"])
            if res.get("stderr"):
                tail += "\nError:\n" + _trunc(res["stderr"])
            return (f"⏱️ {what} {timeout}s-e shesh holo na — timeout. "
                    "Timeout bariye abar bolo, ba code-ta choto koro." + tail)
        parts = []
        if res.get("stdout"):
            parts.append("Output:\n" + _trunc(res["stdout"]))
        if res.get("stderr"):
            parts.append("Error:\n" + _trunc(res["stderr"]))
        tail = f" (exit code {res.get('exit_code', '?')}, {res.get('elapsed_s', '?')}s)"
        if not parts:
            return f"{what} chollo, kintu kono output dilo na." + tail
        return "\n\n".join(parts) + tail
    except Exception as e:
        return f"{what}-er result dekhate parlam na: {e}"


# ── snippets ─────────────────────────────────────────────────────────────────

def run_snippet(code: str, timeout: int = _DEFAULT_TIMEOUT_S,
                python_exe: str | None = None) -> dict:
    """Run Python code text with this PC's Python. Returns the structured
    dict from _run() plus {"code_error": msg} when the code is empty.
    Never raises."""
    try:
        code = (code or "").strip()
        if not code:
            return {"ok": False, "stdout": "", "stderr": "",
                    "exit_code": -1, "timed_out": False, "elapsed_s": 0.0,
                    "code_error": "Code dao — khali snippet chalate parbo na."}
        timeout = max(1, min(int(timeout or _DEFAULT_TIMEOUT_S),
                             _MAX_TIMEOUT_S))
        exe = (python_exe or "").strip() or _python_exe()
        with tempfile.TemporaryDirectory(prefix="mark-pyrun-") as td:
            fpath = Path(td) / "main.py"
            fpath.write_text(code, encoding="utf-8")
            return _run([exe, str(fpath)], cwd=td, timeout=timeout)
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e),
                "exit_code": -1, "timed_out": False, "elapsed_s": 0.0}


def run_snippet_text(code: str, timeout: int = _DEFAULT_TIMEOUT_S) -> str:
    """Snippet → plain-words string (for the plugin / voice / relay).
    Never raises."""
    try:
        res = run_snippet(code, timeout=timeout)
        if res.get("code_error"):
            return str(res["code_error"])
        return "🐍 Python Run — " + _format(res, max(
            1, min(int(timeout or _DEFAULT_TIMEOUT_S), _MAX_TIMEOUT_S)))
    except Exception as e:
        return f"Python code chalate parlam na: {e}"


# ── projects ─────────────────────────────────────────────────────────────────

def _venv_python(folder: Path) -> str | None:
    """python.exe inside folder/.venv, or None. Never raises."""
    try:
        if os.name == "nt":
            cand = folder / ".venv" / "Scripts" / "python.exe"
        else:
            cand = folder / ".venv" / "bin" / "python"
        return str(cand) if cand.is_file() else None
    except Exception:
        return None


def _pip_install(venv_python: str, req_file: Path,
                 timeout: int = _PIP_TIMEOUT_S) -> tuple[bool, str]:
    """pip install -r requirements.txt into the venv. Best-effort:
    returns (ok, short-note). Never raises."""
    try:
        res = _run([venv_python, "-m", "pip", "install", "--quiet",
                    "-r", str(req_file)], cwd=req_file.parent,
                   timeout=max(10, min(int(timeout or _PIP_TIMEOUT_S), 600)))
        if res.get("ok"):
            return True, "requirements install holo"
        err = (res.get("stderr") or res.get("stdout") or "").strip()
        return False, ("requirements install holo na — system Python diye "
                       "chalacchi" + (f": {err[:160]}" if err else ""))
    except Exception as e:
        return False, f"pip install korte parlam na: {e}"


def run_project(folder: str, entry: str = "main.py",
                timeout: int = _PROJECT_TIMEOUT_S,
                install_requirements: bool = True,
                python_exe: str | None = None) -> str:
    """Run a project folder: venv (best-effort) + pip install -r
    requirements.txt (best-effort, when the file exists) + run the entry
    file. Big projects are fine — no size cap on the PC. Returns a
    plain-words string. Never raises."""
    try:
        root = Path(str(folder or "").strip()).expanduser()
        if not str(folder or "").strip():
            return "Project folder-ta pelam na: (khali) — folder-er path dao."
        if not root.is_dir():
            return f"Project folder-ta pelam na: {folder or '(khali)'}."
        entry_name = (entry or "main.py").strip() or "main.py"
        entry_path = root / entry_name
        if not entry_path.is_file():
            # One .py file in the folder? Use it and say so.
            pys = sorted(p for p in root.glob("*.py") if p.is_file())
            if len(pys) == 1 and entry_name == "main.py":
                entry_path = pys[0]
                entry_name = entry_path.name
            else:
                return (f"Entry file pelam na: {entry_name} — folder-e "
                        f"{entry_name} ache kina dekho, ba entry-r naam dao.")
        timeout = max(10, min(int(timeout or _PROJECT_TIMEOUT_S),
                              _MAX_PROJECT_TIMEOUT_S))
        notes: list[str] = []
        exe = (python_exe or "").strip() or _python_exe()
        venv_py = _venv_python(root)
        if venv_py is None:
            # Best-effort venv — if it fails, the system Python runs it.
            venv_res = _run([exe, "-m", "venv", str(root / ".venv")],
                            cwd=root, timeout=_VENV_TIMEOUT_S)
            venv_py = _venv_python(root)
            if venv_py:
                notes.append("venv banalam (.venv)")
            else:
                notes.append("venv banate parlam na — system Python diye chalacchi")
        else:
            notes.append("ager .venv use korlam")
        req_file = root / "requirements.txt"
        if install_requirements and req_file.is_file() and venv_py:
            ok, note = _pip_install(venv_py, req_file)
            notes.append(note)
            if not ok:
                venv_py = None  # fall back to the system Python below
        run_exe = venv_py or exe
        res = _run([run_exe, str(entry_path)], cwd=root, timeout=timeout)
        head = (f"🐍 Project Run — {root.name}/{entry_name} "
                f"({run_exe == venv_py and venv_py and 'venv' or 'system Python'}):")
        if notes:
            head += "\n" + " • ".join(notes)
        return head + "\n" + _format(res, timeout, "Project")
    except Exception as e:
        return f"Project chalate parlam na: {e}"


# ── libraries (advanced round) ───────────────────────────────────────────────

# One-click install list for the Plugin Settings "Libraries" box.
COMMON_LIBRARIES = [
    {"name": "requests", "desc": "HTTP requests — API call, web fetch."},
    {"name": "Pillow", "desc": "Image edit — resize, convert, draw."},
    {"name": "flask", "desc": "Web app / dashboard banano."},
    {"name": "fastapi", "desc": "REST API banano (uvicorn soho cholbe)."},
    {"name": "pandas", "desc": "CSV/Excel data analyze."},
    {"name": "beautifulsoup4", "desc": "HTML parse — web scraping."},
    {"name": "openpyxl", "desc": "Excel file pora/likha."},
]

_LIB_NAME_RE = None  # compiled lazily below


def _valid_lib_name(name: str) -> bool:
    """A pip package name — letters, digits, -, _, . only, no flags."""
    try:
        import re as _re
        global _LIB_NAME_RE
        if _LIB_NAME_RE is None:
            _LIB_NAME_RE = _re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")
        return bool(_LIB_NAME_RE.match(str(name or "").strip()))
    except Exception:
        return False


def list_installed_packages(python_exe: str | None = None,
                            run_fn=None) -> dict:
    """pip list --format=json. Returns {ok, packages: [{name, version}],
    note}. `run_fn` is injectable for tests (defaults to _run). Never
    raises."""
    try:
        exe = (python_exe or "").strip() or _python_exe()
        runner = run_fn or _run
        res = runner([exe, "-m", "pip", "list", "--format=json"],
                     cwd=None, timeout=60)
        if not isinstance(res, dict) or not res.get("ok"):
            err = ""
            if isinstance(res, dict):
                err = (res.get("stderr") or res.get("stdout") or "").strip()
            return {"ok": False, "packages": [],
                    "note": "pip list korte parlam na"
                            + (f": {err[:160]}" if err else "")}
        import json as _json
        try:
            pkgs = _json.loads(res.get("stdout") or "[]")
        except Exception:
            pkgs = []
        out = [{"name": str(p.get("name", "")), "version": str(p.get("version", ""))}
               for p in pkgs if isinstance(p, dict) and p.get("name")]
        return {"ok": True, "packages": out,
                "note": f"{len(out)} ta package install ache"}
    except Exception as e:
        return {"ok": False, "packages": [],
                "note": f"pip list korte parlam na: {e}"}


def install_library(name: str, python_exe: str | None = None,
                    run_fn=None) -> tuple[bool, str]:
    """pip install <name> (one package). Best-effort, needs internet.
    Returns (ok, note). Never raises."""
    try:
        name = (name or "").strip()
        if not _valid_lib_name(name):
            return False, ("Library-r naam-ta thik dao — sudhu letter, "
                           "number, -, _ ar . cholbe (jemon 'requests').")
        exe = (python_exe or "").strip() or _python_exe()
        runner = run_fn or _run
        res = runner([exe, "-m", "pip", "install", "--quiet", name],
                     cwd=None, timeout=_PIP_TIMEOUT_S)
        if isinstance(res, dict) and res.get("ok"):
            return True, f"✅ '{name}' install holo."
        err = ""
        if isinstance(res, dict):
            err = (res.get("stderr") or res.get("stdout") or "").strip()
        return False, ("❌ '{name}' install holo na — internet check koro"
                       .format(name=name)
                       + (f": {err[:200]}" if err else ""))
    except Exception as e:
        return False, f"Library install korte parlam na: {e}"


def libraries_text(python_exe: str | None = None) -> str:
    """One plain-words summary for the box / card. Never raises."""
    try:
        res = list_installed_packages(python_exe=python_exe)
        lines = [f"🐍 Libraries — Python {python_version()}:"]
        if res.get("ok"):
            pkgs = res.get("packages") or []
            names = {p["name"].lower(): p["version"] for p in pkgs}
            lines.append(f"  • {len(pkgs)} ta package install ache.")
            for lib in COMMON_LIBRARIES:
                ver = names.get(lib["name"].lower())
                mark = f"✅ {ver}" if ver else "❌ install nei"
                lines.append(f"  • {lib['name']} — {mark} ({lib['desc']})")
            others = [p["name"] for p in pkgs
                      if p["name"].lower() not in
                      {l["name"].lower() for l in COMMON_LIBRARIES}][:10]
            if others:
                lines.append("  • Aro: " + ", ".join(others))
        else:
            lines.append("  • " + str(res.get("note", "")))
        lines.append("  • Install korte: library-r naam likhe Install chapo "
                     "(internet lagbe).")
        return "\n".join(lines)
    except Exception as e:
        return f"Libraries dekhte parlam na: {e}"


# ── phone relay ──────────────────────────────────────────────────────────────

def handle_phone_request(text: str, timeout: int = _DEFAULT_TIMEOUT_S) -> str:
    """Run code the paired phone sent (kind=python_run, or kind=text with
    the PYTHON_RUN:: prefix). `text` is the raw code, or the prefixed
    text. Returns the result string for send_result(). Never raises."""
    try:
        code = (text or "").strip()
        if code.startswith(_PHONE_PREFIX):
            code = code[len(_PHONE_PREFIX):].strip()
        if not code:
            return "Python code pelam na — phone theke code pathao."
        return run_snippet_text(code, timeout=timeout)
    except Exception as e:
        return f"Phone-er Python code chalate parlam na: {e}"


def is_phone_request(text: str) -> bool:
    """True when a relay text message carries Python code to run."""
    try:
        return str(text or "").strip().startswith(_PHONE_PREFIX)
    except Exception:
        return False
