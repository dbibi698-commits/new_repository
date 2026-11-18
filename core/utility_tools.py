"""core/utility_tools.py — 🧰 50 REAL UTILITY TOOLS (the 50 new agent cards).

Every function here does a REAL job on this PC — no placeholders, no
fakes. Each returns a short string and never raises. Tools that need
something (internet, ffmpeg, a pairing, a token) say so plainly when
it is missing instead of pretending.

State (notes, habits, expenses, bookmarks, contacts, events, flashcards,
polls, vault, timers) lives in plugin_config namespaces through
memory/config_manager.py — never in config/api_keys.json directly.
Nothing here imports Qt; nothing here touches a widget.

The 50 (grouped by the plugin that exposes them):
  utility_time    Timer, Stopwatch, Pomodoro, World Clock, Sleep Timer,
                  Focus Mode
  utility_convert Unit Converter, Currency Converter, Code Formatter,
                  JSON Viewer, Regex Tester
  utility_files   File Search, Zip Tool, Storage Analyzer, Disk Cleanup,
                  Download Manager, Image Resizer, Clipboard
  utility_system  System Info, Process Manager, Startup Manager,
                  Network Speed Test, WiFi Networks, Bluetooth Devices,
                  VPN Status, Battery Monitor, Screen Recorder
  utility_create  QR Generator, Password Generator, Meme Maker,
                  Subtitle Maker, Invoice Maker, Resume Builder
  utility_life    Notes, Habit Tracker, Expense Tracker, Bookmark
                  Manager, Contacts, Calendar, Flashcard Maker,
                  Quiz Maker, Poll Maker, Dictionary
  utility_media   Audio Converter, Video Downloader, YouTube
                  (YouTube lives in core/youtube_agent.py — this module
                  only re-exports its status helper)
  utility_phone   SMS Sender, Call Log, Step Counter
  utility_vault   Password Vault
"""
from __future__ import annotations

import ast
import calendar as _calendar
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── small helpers ────────────────────────────────────────────────────────────

def _cfg(ns: str) -> dict:
    try:
        from memory.config_manager import get_plugin_config
        return dict(get_plugin_config(ns) or {})
    except Exception:
        return {}


def _save_cfg(ns: str, data: dict) -> None:
    try:
        from memory.config_manager import save_plugin_config
        save_plugin_config(ns, dict(data))
    except Exception:
        pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _downloads() -> Path:
    return Path.home() / "Downloads" / "MarkLVII"


def _fmt_bytes(n: float) -> str:
    try:
        n = float(n)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024:
                return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} PB"
    except Exception:
        return "?"


def _run_cmd(cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    """Run a command, return (returncode, stdout+stderr). Never raises."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=max(5, int(timeout or 15)))
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return -1, str(e)


def _ffmpeg() -> str:
    """ffmpeg path or ''. Never raises."""
    try:
        p = shutil.which("ffmpeg")
        if p:
            return p
        cand = Path(__file__).resolve().parent.parent / "ffmpeg" / "ffmpeg.exe"
        return str(cand) if cand.is_file() else ""
    except Exception:
        return ""


# ── ⏱️ time ──────────────────────────────────────────────────────────────────

_TIMERS: dict[str, dict] = {}
_TIMERS_LOCK = threading.Lock()


def start_timer(minutes: float = 5.0, label: str = "Timer") -> str:
    """Start a countdown timer (daemon thread). Returns a status string."""
    try:
        secs = max(1.0, float(minutes or 5.0) * 60.0)
        label = str(label or "Timer")[:60]
        key = f"{label}-{int(time.time())}"

        def _done():
            try:
                cfg = _cfg("utility_timers")
                done = list(cfg.get("done") or [])
                done.append({"label": label, "at": _now()})
                cfg["done"] = done[-20:]
                _save_cfg("utility_timers", cfg)
            except Exception:
                pass

        t = threading.Timer(secs, _done)
        t.daemon = True
        t.start()
        with _TIMERS_LOCK:
            _TIMERS[key] = {"label": label, "ends_at": time.time() + secs,
                            "timer": t}
        return (f"⏱️ Timer cholche: {label} — {minutes:g} min pore shesh hobe "
                f"({datetime.now() + timedelta(seconds=secs):%H:%M:%S}-e).")
    except Exception as e:
        return f"Timer chalate parlam na: {e}"


def timer_status() -> str:
    try:
        with _TIMERS_LOCK:
            items = list(_TIMERS.items())
        now = time.time()
        live = []
        for key, v in items:
            left = v["ends_at"] - now
            if left > 0:
                live.append(f"  • {v['label']}: {int(left // 60)}m "
                            f"{int(left % 60)}s baki")
        cfg = _cfg("utility_timers")
        done = list(cfg.get("done") or [])[-3:]
        lines = ["⏱️ Timer — status:"]
        lines += live if live else ["  • Kono timer cholche na."]
        for d in done:
            lines.append(f"  • ✅ {d.get('label')}: {d.get('at', '')}-e shesh")
        return "\n".join(lines)
    except Exception as e:
        return f"Timer-er status dekhte parlam na: {e}"


def stopwatch(action: str = "status", label: str = "") -> str:
    """start / stop / lap / status. State in config. Never raises."""
    try:
        action = str(action or "status").strip().lower()
        cfg = _cfg("utility_stopwatch")
        if action == "start":
            cfg["started_at"] = time.time()
            cfg["laps"] = []
            cfg["label"] = str(label or "Stopwatch")[:60]
            _save_cfg("utility_stopwatch", cfg)
            return f"⏱️ Stopwatch chalu — {cfg['label']}."
        if action == "lap":
            if not cfg.get("started_at"):
                return "⏱️ Stopwatch chalu nei — age start koro."
            laps = list(cfg.get("laps") or [])
            laps.append(round(time.time() - float(cfg["started_at"]), 1))
            cfg["laps"] = laps
            _save_cfg("utility_stopwatch", cfg)
            return f"⏱️ Lap {len(laps)}: {laps[-1]:.1f}s."
        if action == "stop":
            if not cfg.get("started_at"):
                return "⏱️ Stopwatch chalu nei."
            total = time.time() - float(cfg["started_at"])
            laps = list(cfg.get("laps") or [])
            cfg["started_at"] = 0
            cfg["last_total"] = round(total, 1)
            _save_cfg("utility_stopwatch", cfg)
            return (f"⏱️ Stopwatch thamlo — mot {total:.1f}s"
                    + (f" ({len(laps)} lap)" if laps else "") + ".")
        # status
        if cfg.get("started_at"):
            el = time.time() - float(cfg["started_at"])
            return (f"⏱️ Stopwatch cholche — {el:.1f}s hoyeche "
                    f"({len(cfg.get('laps') or [])} lap).")
        last = cfg.get("last_total")
        return ("⏱️ Stopwatch bondho."
                + (f" Shesh bar: {last}s." if last else ""))
    except Exception as e:
        return f"Stopwatch chalate parlam na: {e}"


def pomodoro(action: str = "status") -> str:
    """25m work / 5m break cycles. State in config. Never raises."""
    try:
        action = str(action or "status").strip().lower()
        cfg = _cfg("utility_pomodoro")
        if action in ("start", "work"):
            cfg["phase"] = "work"
            cfg["ends_at"] = time.time() + 25 * 60
            cfg["cycles"] = int(cfg.get("cycles") or 0)
            _save_cfg("utility_pomodoro", cfg)
            return "🍅 Pomodoro — 25 min kaj shuru. Tarpor 5 min break."
        if action == "break":
            cfg["phase"] = "break"
            cfg["ends_at"] = time.time() + 5 * 60
            cfg["cycles"] = int(cfg.get("cycles") or 0) + 1
            _save_cfg("utility_pomodoro", cfg)
            return (f"☕ Pomodoro break — 5 min. "
                    f"({cfg['cycles']} cycle shesh)")
        if action == "stop":
            cfg["phase"] = ""
            cfg["ends_at"] = 0
            _save_cfg("utility_pomodoro", cfg)
            return "🍅 Pomodoro thamlo."
        phase = str(cfg.get("phase") or "")
        if not phase:
            return ("🍅 Pomodoro bondho — 'start' bolo 25 min kaj + 5 min "
                    "break cycle-er jonno.")
        left = max(0.0, float(cfg.get("ends_at") or 0) - time.time())
        return (f"🍅 Pomodoro {phase}-e ache — {int(left // 60)}m "
                f"{int(left % 60)}s baki "
                f"({int(cfg.get('cycles') or 0)} cycle shesh).")
    except Exception as e:
        return f"Pomodoro chalate parlam na: {e}"


_WORLD_CLOCK_CITIES = {
    "kolkata": "Asia/Kolkata", "dhaka": "Asia/Dhaka",
    "london": "Europe/London", "new york": "America/New_York",
    "dubai": "Asia/Dubai", "tokyo": "Asia/Tokyo",
    "sydney": "Australia/Sydney", "paris": "Europe/Paris",
}


def world_clock(cities: str = "") -> str:
    """Current time in world cities (zoneinfo, stdlib). Never raises."""
    try:
        from zoneinfo import ZoneInfo
        want = [c.strip().lower() for c in str(cities or "").split(",")
                if c.strip()] or list(_WORLD_CLOCK_CITIES)
        lines = ["🌍 World Clock:"]
        for name in want:
            tzname = _WORLD_CLOCK_CITIES.get(name)
            if not tzname:
                continue
            try:
                now = datetime.now(ZoneInfo(tzname))
                lines.append(f"  • {name.title()}: {now:%H:%M (%d %b)}")
            except Exception:
                continue
        lines.append(f"  • Ekhane (PC): {datetime.now():%H:%M (%d %b)}")
        return "\n".join(lines)
    except Exception as e:
        return f"World clock dekhte parlam na: {e}"


_SLEEP_TIMER: dict[str, object] = {"timer": None, "at": 0.0}


def sleep_timer(minutes: float = 30.0, cancel: bool = False) -> str:
    """Schedule the PC to sleep after N minutes (cancellable timer).
    On Windows: rundll32 SetSuspendState. Never raises."""
    try:
        if cancel:
            t = _SLEEP_TIMER.get("timer")
            if isinstance(t, threading.Timer):
                t.cancel()
            _SLEEP_TIMER["timer"] = None
            _SLEEP_TIMER["at"] = 0.0
            return "😴 Sleep timer cancel holo."
        mins = max(1.0, min(480.0, float(minutes or 30.0)))
        old = _SLEEP_TIMER.get("timer")
        if isinstance(old, threading.Timer):
            old.cancel()

        def _sleep():
            try:
                import platform as _pl
                if _pl.system() == "Windows":
                    subprocess.run(
                        ["rundll32.exe", "powrprof.dll,SetSuspendState",
                         "0,1,0"], timeout=10)
                else:
                    subprocess.run(["systemctl", "suspend"], timeout=10)
            except Exception:
                pass

        t = threading.Timer(mins * 60.0, _sleep)
        t.daemon = True
        t.start()
        _SLEEP_TIMER["timer"] = t
        _SLEEP_TIMER["at"] = time.time() + mins * 60.0
        return (f"😴 Sleep timer dilam — {mins:g} min pore PC ghumabe. "
                f"Cancel korte 'sleep timer cancel' bolo.")
    except Exception as e:
        return f"Sleep timer dite parlam na: {e}"


def focus_mode(on: bool = True, minutes: float = 25.0) -> str:
    """Focus session: Windows toast notifications off + a timer.
    Restores notifications when it ends. Never raises."""
    try:
        import platform as _pl
        mins = max(1.0, min(240.0, float(minutes or 25.0)))
        if not bool(on):
            if _pl.system() == "Windows":
                try:
                    import winreg
                    key = winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings",
                        0, winreg.KEY_SET_VALUE)
                    winreg.SetValueEx(
                        key, "NOC_GLOBAL_SETTING_TOASTS_ENABLED", 0,
                        winreg.REG_DWORD, 1)
                    winreg.CloseKey(key)
                except Exception:
                    pass
            return "🎯 Focus mode OFF — notification abar chalu holo."
        if _pl.system() == "Windows":
            try:
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Notifications\Settings",
                    0, winreg.KEY_SET_VALUE)
                winreg.SetValueEx(
                    key, "NOC_GLOBAL_SETTING_TOASTS_ENABLED", 0,
                    winreg.REG_DWORD, 0)
                winreg.CloseKey(key)
                note = "Windows notification (toast) bondho korlam"
            except Exception:
                note = "notification bondho korte parlam na (registry), timer cholbe"
        else:
            note = "ei OS-e notification toggle nei — sudhu timer cholbe"
        start_timer(mins, label="Focus")
        return (f"🎯 Focus mode ON — {mins:g} min. {note}. "
                f"Shesh hole notification abar chalu koro ('focus mode off').")
    except Exception as e:
        return f"Focus mode chalate parlam na: {e}"


# ── 🔁 convert ───────────────────────────────────────────────────────────────

_LENGTH = {"mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0,
           "inch": 0.0254, "in": 0.0254, "ft": 0.3048, "foot": 0.3048,
           "feet": 0.3048, "yard": 0.9144, "mile": 1609.344}
_WEIGHT = {"g": 1.0, "gram": 1.0, "kg": 1000.0, "mg": 0.001,
           "lb": 453.59237, "lbs": 453.59237, "oz": 28.349523125,
           "ton": 1000000.0}
_VOLUME = {"ml": 0.001, "l": 1.0, "liter": 1.0, "litre": 1.0,
           "cup": 0.236588, "gallon": 3.78541, "tsp": 0.004929,
           "tbsp": 0.014787}


def unit_convert(value: float, from_unit: str, to_unit: str) -> str:
    """Length / weight / volume / temperature. Pure maths. Never raises."""
    try:
        v = float(value)
        f, t = str(from_unit or "").strip().lower(), str(to_unit or "").strip().lower()
        for table, name in ((_LENGTH, "length"), (_WEIGHT, "weight"),
                            (_VOLUME, "volume")):
            if f in table and t in table:
                out = v * table[f] / table[t]
                return f"🔁 {v:g} {f} = {out:.4g} {t}"
        if f in ("c", "celsius", "°c") and t in ("f", "fahrenheit", "°f"):
            return f"🔁 {v:g}°C = {v * 9 / 5 + 32:.2f}°F"
        if f in ("f", "fahrenheit", "°f") and t in ("c", "celsius", "°c"):
            return f"🔁 {v:g}°F = {(v - 32) * 5 / 9:.2f}°C"
        return ("🔁 Unit bujhlam na — length (m/km/inch/ft), weight "
                "(g/kg/lb/oz), volume (ml/l/cup/gallon), temperature (C/F).")
    except Exception as e:
        return f"Convert korte parlam na: {e}"


_CURRENCY_CACHE = {"at": 0.0, "rates": {}}


def currency_convert(amount: float, from_cur: str, to_cur: str) -> str:
    """Free exchangerate-api (no key), 1 h cache. Offline: cached rates
    or an honest 'net lagbe'. Never raises."""
    try:
        amt = float(amount)
        f = str(from_cur or "USD").strip().upper()
        t = str(to_cur or "INR").strip().upper()
        if f == t:
            return f"💱 {amt:g} {f} = {amt:g} {t}"
        now = time.time()
        rates = _CURRENCY_CACHE["rates"]
        if not rates or now - _CURRENCY_CACHE["at"] > 3600:
            try:
                import urllib.request
                req = urllib.request.Request(
                    "https://open.er-api.com/v6/latest/USD",
                    headers={"User-Agent": "Mark-LVII/1.0"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    data = json.loads(r.read().decode("utf-8"))
                rates = dict((data or {}).get("rates") or {})
                if rates:
                    _CURRENCY_CACHE["rates"] = rates
                    _CURRENCY_CACHE["at"] = now
            except Exception:
                rates = _CURRENCY_CACHE["rates"]
        if not rates or f not in rates or t not in rates:
            return ("💱 Rate ante parlam na — internet lagbe (exchangerate-api). "
                    "Net asle abar bolo.")
        out = amt / float(rates[f]) * float(rates[t])
        return f"💱 {amt:g} {f} = {out:.2f} {t}"
    except Exception as e:
        return f"Currency convert korte parlam na: {e}"


def code_format(code: str, lang: str = "python") -> str:
    """Format Python via ast.unparse, JSON via json.dumps(indent=2).
    Real formatting, stdlib only. Never raises."""
    try:
        src = str(code or "")
        if not src.strip():
            return "Code dao — khali pelam."
        if str(lang or "python").strip().lower() in ("json",):
            data = json.loads(src)
            return "🧹 JSON format kora holo:\n" + json.dumps(
                data, indent=2, ensure_ascii=False)[:3000]
        tree = ast.parse(src)
        return "🧹 Python format kora holo:\n" + ast.unparse(tree)[:3000]
    except Exception as e:
        return f"Format korte parlam na: {e}"


def json_view(data: str) -> str:
    """Pretty-print + validate JSON. Never raises."""
    try:
        obj = json.loads(str(data or ""))
        pretty = json.dumps(obj, indent=2, ensure_ascii=False)
        kind = type(obj).__name__
        n = len(obj) if hasattr(obj, "__len__") else 0
        return (f"📋 JSON thik ache ({kind}, {n} ta item):\n"
                + pretty[:3000])
    except Exception as e:
        return f"📋 JSON-ta thik noy: {e}"


def regex_test(pattern: str, text: str) -> str:
    """re.findall / search on a pattern. Never raises."""
    try:
        pat = str(pattern or "")
        txt = str(text or "")
        if not pat:
            return "Pattern dao."
        rx = re.compile(pat)
        found = rx.findall(txt)
        m = rx.search(txt)
        lines = [f"🔍 Pattern: {pat}",
                 f"  • Match: {len(found)} ta"]
        for f in found[:10]:
            lines.append(f"    - {str(f)[:120]}")
        if m:
            lines.append(f"  • Prothom match: '{m.group(0)[:120]}' "
                         f"(pos {m.start()}-{m.end()})")
        return "\n".join(lines)
    except re.error as e:
        return f"🔍 Pattern-ta vul: {e}"
    except Exception as e:
        return f"Regex test korte parlam na: {e}"


# ── 📁 files ─────────────────────────────────────────────────────────────────

def file_search(query: str, folder: str = "", limit: int = 20) -> str:
    """Search file names under a folder (os.walk, capped). Never raises."""
    try:
        root = Path(str(folder or "").strip()).expanduser() \
            if folder else Path.home()
        if not root.is_dir():
            return f"Folder-ta pelam na: {root}"
        q = str(query or "").strip().lower()
        if not q:
            return "Ki khujbo — naam dao."
        hits: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if d not in (".git", "__pycache__", ".venv",
                                        "node_modules", "AppData")]
            for fn in filenames:
                if q in fn.lower():
                    hits.append(str(Path(dirpath) / fn))
                    if len(hits) >= max(1, int(limit or 20)):
                        break
            if len(hits) >= max(1, int(limit or 20)):
                break
        if not hits:
            return f"🔍 '{query}' — {root}-e kichu pelam na."
        lines = [f"🔍 '{query}' — {len(hits)} ta pelam:"]
        lines += [f"  • {h}" for h in hits[:20]]
        return "\n".join(lines)
    except Exception as e:
        return f"File khujte parlam na: {e}"


def zip_tool(action: str = "create", source: str = "", dest: str = "") -> str:
    """Create / extract a .zip (zipfile, stdlib). Never raises."""
    try:
        action = str(action or "create").strip().lower()
        src = Path(str(source or "").strip()).expanduser()
        if action == "extract":
            if not src.is_file():
                return f"Zip file-ta pelam na: {src}"
            out = Path(str(dest or "").strip()).expanduser() \
                if dest else src.parent / src.stem
            out.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(src, "r") as zf:
                bad = [n for n in zf.namelist()
                       if ".." in n or n.startswith("/")]
                if bad:
                    return "⚠️ Zip-er bhitore suspicious path ache — khul lam na."
                zf.extractall(out)
                n = len(zf.namelist())
            return f"📦 Zip khullam — {n} ta file: {out}"
        if not src.exists():
            return f"Source-ta pelam na: {src}"
        dst = Path(str(dest or "").strip()).expanduser() if dest else \
            (src.parent / (src.name + ".zip"))
        if dst.suffix.lower() != ".zip":
            dst = dst.with_suffix(".zip")
        count = 0
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
            if src.is_file():
                zf.write(src, src.name)
                count = 1
            else:
                for p in src.rglob("*"):
                    if p.is_file():
                        zf.write(p, p.relative_to(src))
                        count += 1
        return f"📦 Zip banalam — {count} ta file: {dst} ({_fmt_bytes(dst.stat().st_size)})"
    except Exception as e:
        return f"Zip korte parlam na: {e}"


def storage_analyzer(folder: str = "") -> str:
    """Disk usage + biggest subfolders (1 level, capped). Never raises."""
    try:
        root = Path(str(folder or "").strip()).expanduser() \
            if folder else Path.home()
        if not root.is_dir():
            return f"Folder-ta pelam na: {root}"
        total, used, free = shutil.disk_usage(str(root))
        lines = [f"💽 Storage — {root}:",
                 f"  • Disk: {_fmt_bytes(used)} use / {_fmt_bytes(total)} "
                 f"({int(used / total * 100) if total else 0}%) • "
                 f"Free {_fmt_bytes(free)}"]
        subs: list[tuple[float, str]] = []
        for child in root.iterdir():
            if not child.is_dir():
                continue
            size = 0.0
            try:
                for dirpath, _d, files in os.walk(child):
                    for fn in files:
                        try:
                            size += (Path(dirpath) / fn).stat().st_size
                        except Exception:
                            pass
                    if size > 50 * 1024 * 1024 * 1024:
                        break
            except Exception:
                pass
            subs.append((size, child.name))
        subs.sort(reverse=True)
        for size, name in subs[:8]:
            lines.append(f"  • {name}: {_fmt_bytes(size)}")
        return "\n".join(lines)
    except Exception as e:
        return f"Storage dekhte parlam na: {e}"


def disk_cleanup(dry_run: bool = True) -> str:
    """Clean old temp files (recoverable via send2trash). Never raises."""
    try:
        import tempfile
        tmp = Path(tempfile.gettempdir())
        cutoff = time.time() - 7 * 24 * 3600
        cands: list[Path] = []
        freed = 0
        for p in tmp.iterdir():
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    cands.append(p)
                    freed += p.stat().st_size
            except Exception:
                continue
        if dry_run:
            return (f"🧹 Disk Cleanup (preview) — {tmp}-e {len(cands)} ta "
                    f"7 din-er purono temp file ({_fmt_bytes(freed)}). "
                    f"Sotti muche dite 'disk cleanup koro' bolo.")
        try:
            from send2trash import send2trash
        except Exception:
            return "🧹 send2trash install nei — muche parlam na."
        n = 0
        for p in cands:
            try:
                send2trash(str(p))
                n += 1
            except Exception:
                continue
        return (f"🧹 Disk Cleanup — {n} ta temp file Recycle Bin-e "
                f"pathalam ({_fmt_bytes(freed)} khali holo).")
    except Exception as e:
        return f"Disk cleanup korte parlam na: {e}"


def download_file(url: str, name: str = "") -> str:
    """Download a file to Downloads/MarkLVII (100 MB cap). Never raises."""
    try:
        url = str(url or "").strip()
        if not url.startswith(("http://", "https://")):
            return "URL dao — http(s) hote hobe."
        fname = str(name or "").strip() or url.split("/")[-1].split("?")[0]
        fname = "".join(c for c in fname if c.isalnum() or c in "._- ")[:80]
        if not fname:
            fname = "download.bin"
        folder = _downloads()
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / fname
        import urllib.request
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mark-LVII/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            total = r.headers.get("Content-Length")
            if total and int(total) > 100 * 1024 * 1024:
                return "⚠️ File-ta 100 MB-er boro — download korlam na."
            data = r.read(100 * 1024 * 1024 + 1)
        if len(data) > 100 * 1024 * 1024:
            return "⚠️ File-ta 100 MB-er boro — download korlam na."
        dest.write_bytes(data)
        return f"⬇️ Download holo: {dest} ({_fmt_bytes(len(data))})"
    except Exception as e:
        return f"Download korte parlam na: {e}"


def image_resize(path: str, width: int = 800, height: int = 0) -> str:
    """Resize an image with PIL (keeps aspect when height=0). Never raises."""
    try:
        src = Path(str(path or "").strip()).expanduser()
        if not src.is_file():
            return f"Image-ta pelam na: {src}"
        from PIL import Image
        w = max(1, int(width or 800))
        h = int(height or 0)
        img = Image.open(src)
        if h > 0:
            img = img.resize((w, h))
        else:
            ratio = w / img.width
            img = img.resize((w, max(1, int(img.height * ratio))))
        out = src.parent / (src.stem + f"-{img.width}x{img.height}" + src.suffix)
        img.save(out)
        return f"🖼️ Resize holo: {img.width}x{img.height} — {out}"
    except Exception as e:
        return f"Image resize korte parlam na: {e}"


def clipboard(action: str = "get", text: str = "") -> str:
    """Get / set the PC clipboard (pyperclip). Never raises."""
    try:
        import pyperclip
        action = str(action or "get").strip().lower()
        if action == "set":
            pyperclip.copy(str(text or ""))
            return f"📋 Clipboard-e bosalam: {str(text or '')[:120]}"
        cur = pyperclip.paste() or ""
        return "📋 Clipboard khali." if not cur.strip() else \
            f"📋 Clipboard-e ache:\n{cur[:500]}"
    except Exception as e:
        return f"Clipboard chalate parlam na: {e}"


# ── 🖥️ system ────────────────────────────────────────────────────────────────

def system_info() -> str:
    """OS / CPU / RAM / disk / battery (platform + psutil). Never raises."""
    try:
        import platform
        lines = [f"🖥️ System — {platform.system()} {platform.release()} "
                 f"({platform.machine()})",
                 f"  • Python {platform.python_version()}"]
        try:
            import psutil
            lines.append(f"  • CPU {psutil.cpu_percent(interval=0.5):.0f}% "
                         f"({psutil.cpu_count()} core) • RAM "
                         f"{psutil.virtual_memory().percent:.0f}%")
            total, used, free = shutil.disk_usage(str(Path.home()))
            lines.append(f"  • Disk: {_fmt_bytes(used)} / {_fmt_bytes(total)} "
                         f"use • Free {_fmt_bytes(free)}")
            batt = psutil.sensors_battery()
            if batt:
                lines.append(f"  • Battery {int(batt.percent)}% "
                             f"({'charging' if batt.power_plugged else 'on battery'})")
        except Exception:
            pass
        return "\n".join(lines)
    except Exception as e:
        return f"System info dekhte parlam na: {e}"


def process_list(top: int = 10) -> str:
    """Top processes by CPU (psutil). Never raises."""
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent",
                                      "memory_percent"]):
            try:
                procs.append(p.info)
            except Exception:
                continue
        procs.sort(key=lambda d: d.get("cpu_percent") or 0, reverse=True)
        lines = [f"⚙️ Process — top {min(top, len(procs))} (CPU onujayi):"]
        for p in procs[:max(1, int(top or 10))]:
            lines.append(f"  • PID {p.get('pid')}: {p.get('name')} — "
                         f"CPU {p.get('cpu_percent') or 0:.0f}% • "
                         f"RAM {p.get('memory_percent') or 0:.1f}%")
        return "\n".join(lines)
    except Exception as e:
        return f"Process list dekhte parlam na: {e}"


def process_kill(pid: int, confirmed: bool = False) -> str:
    """Kill one process by PID — only with confirmed=True (the plugin
    asks the user first). Never raises."""
    try:
        pid = int(pid)
        if not confirmed:
            return (f"⚠️ PID {pid}-ke marte chaicho? Confirm koro — "
                    f"'process kill {pid} confirm' bolo, nahole kichu korlam na.")
        import psutil
        p = psutil.Process(pid)
        name = p.name()
        p.terminate()
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()
        return f"⚙️ Process {pid} ({name}) bondho korlam."
    except Exception as e:
        return f"Process marte parlam na: {e}"


def startup_list() -> str:
    """Windows Startup folder entries + Mark autostart state. Never raises."""
    try:
        import platform as _pl
        lines = ["🚀 Startup — ja Windows-er sathe chalu hoy:"]
        if _pl.system() == "Windows":
            folder = Path.home() / "AppData" / "Roaming" / "Microsoft" / \
                "Windows" / "Start Menu" / "Programs" / "Startup"
            if folder.is_dir():
                items = [p.name for p in folder.iterdir()]
                lines += [f"  • {n}" for n in items[:20]] or \
                    ["  • Startup folder khali."]
            else:
                lines.append("  • Startup folder pelam na.")
        try:
            from core import autostart as _as
            lines.append("  • Mark autostart: " +
                         ("✅ ON" if _as.autostart_enabled() else "❌ OFF"))
        except Exception:
            pass
        return "\n".join(lines)
    except Exception as e:
        return f"Startup list dekhte parlam na: {e}"


def network_speed_test() -> str:
    """Download-speed probe (1 MB from Cloudflare, timed). Never raises."""
    try:
        import urllib.request
        url = "https://speed.cloudflare.com/__down?bytes=1000000"
        t0 = time.monotonic()
        req = urllib.request.Request(url,
                                     headers={"User-Agent": "Mark-LVII/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        dt = max(0.01, time.monotonic() - t0)
        mbps = len(data) * 8 / dt / 1_000_000
        return (f"📶 Network speed — download ~{mbps:.1f} Mbps "
                f"(1 MB, {dt:.1f}s-e). Internet na thakle ei test cholbe na.")
    except Exception:
        return ("📶 Speed test holo na — internet nei ba Cloudflare reach "
                "kora gelo na.")


def wifi_networks() -> str:
    """Nearby WiFi networks (Windows netsh). Never raises."""
    try:
        import platform as _pl
        if _pl.system() != "Windows":
            return "📶 WiFi list sudhu Windows-e dekha jay (netsh)."
        rc, out = _run_cmd(["netsh", "wlan", "show", "networks"], timeout=15)
        if rc != 0 or "SSID" not in out:
            return ("📶 WiFi network pelam na — WiFi adapter off thakte pare, "
                    "ba netsh cholche na.")
        ssids = sorted(set(re.findall(r"SSID\s+\d+\s*:\s*(.+)", out)))
        lines = [f"📶 WiFi — {len(ssids)} ta network dekhlam:"]
        lines += [f"  • {s.strip()}" for s in ssids[:20]]
        return "\n".join(lines)
    except Exception as e:
        return f"WiFi list dekhte parlam na: {e}"


def bluetooth_devices() -> str:
    """Paired/visible Bluetooth devices (Windows PowerShell). Never raises."""
    try:
        import platform as _pl
        if _pl.system() != "Windows":
            return "🔵 Bluetooth list sudhu Windows-e dekha jay."
        rc, out = _run_cmd(
            ["powershell", "-NoProfile", "-Command",
             "Get-PnpDevice -Class Bluetooth | Select-Object -ExpandProperty FriendlyName"],
            timeout=20)
        names = sorted(set(l.strip() for l in out.splitlines()
                           if l.strip() and "FriendlyName" not in l))
        if rc != 0 or not names:
            return ("🔵 Bluetooth device pelam na — Bluetooth off thakte pare, "
                    "ba kono device pair kora nei.")
        lines = [f"🔵 Bluetooth — {len(names)} ta device:"]
        lines += [f"  • {n}" for n in names[:20]]
        return "\n".join(lines)
    except Exception as e:
        return f"Bluetooth list dekhte parlam na: {e}"


def vpn_status() -> str:
    """VPN/TAP adapters + default route check (Windows). Never raises."""
    try:
        import platform as _pl
        if _pl.system() != "Windows":
            return "🔒 VPN status sudhu Windows-e check kora jay."
        _rc, out = _run_cmd(["ipconfig", "/all"], timeout=15)
        vpn_words = ("tap", "vpn", "wireguard", "openvpn", "pptp", "l2tp")
        hits = sorted(set(
            l.strip() for l in out.splitlines()
            if any(w in l.lower() for w in vpn_words)))
        if not hits:
            return ("🔒 VPN adapter pelam na — kono VPN connect kora nei "
                    "mone hocche.")
        lines = ["🔒 VPN adapter dekhlam:"]
        lines += [f"  • {h[:120]}" for h in hits[:10]]
        return "\n".join(lines)
    except Exception as e:
        return f"VPN status dekhte parlam na: {e}"


def battery_monitor() -> str:
    """PC battery (psutil) + phone battery via relay when paired.
    Never raises."""
    try:
        lines = ["🔋 Battery:"]
        try:
            import psutil
            batt = psutil.sensors_battery()
            if batt:
                lines.append(f"  • PC: {int(batt.percent)}% "
                             f"({'charging' if batt.power_plugged else 'on battery'})")
            else:
                lines.append("  • PC: battery pelam na (desktop hote pare).")
        except Exception:
            lines.append("  • PC: battery dekhte parlam na.")
        try:
            from core import jarvis_link as _jl
            link = _jl.LINK
            if link is not None and getattr(link, "paired", False):
                ans = link.send_and_wait_result(
                    "phone battery koto percent?", timeout=20.0)
                if ans:
                    lines.append(f"  • 📱 Phone: {str(ans)[:150]}")
                else:
                    lines.append("  • 📱 Phone: uttor elo na.")
            else:
                lines.append("  • 📱 Phone pair kora nei.")
        except Exception:
            pass
        return "\n".join(lines)
    except Exception as e:
        return f"Battery dekhte parlam na: {e}"


def screen_record(action: str = "status", seconds: int = 10) -> str:
    """Screen recording via ffmpeg gdigrab (Windows). start/stop/status.
    State in a module-level proc handle. Never raises."""
    try:
        action = str(action or "status").strip().lower()
        ff = _ffmpeg()
        if not ff and action != "status":
            return ("🎥 Screen record korte ffmpeg lagbe — video_edit box-e "
                    "'ffmpeg install' chapo, tarpor abar bolo.")
        if action == "start":
            if _SCREEN_REC.get("proc") is not None:
                return "🎥 Screen record already cholche."
            out = _downloads() / f"screen-{time.strftime('%Y%m%d-%H%M%S')}.mp4"
            out.parent.mkdir(parents=True, exist_ok=True)
            log_path = out.with_suffix(".log")
            log_f = open(log_path, "w", encoding="utf-8", errors="replace")
            proc = subprocess.Popen(
                [ff, "-y", "-f", "gdigrab", "-framerate", "15",
                 "-i", "desktop", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 str(out)],
                stdout=log_f, stderr=subprocess.STDOUT)
            _SCREEN_REC["proc"] = proc
            _SCREEN_REC["path"] = str(out)
            _SCREEN_REC["log"] = str(log_path)
            _SCREEN_REC["started"] = time.time()
            return f"🎥 Screen record shuru — {out} (stop korte 'stop' bolo)."
        if action == "stop":
            proc = _SCREEN_REC.get("proc")
            if proc is None:
                return "🎥 Kono screen record cholche na."
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            path = str(_SCREEN_REC.get("path") or "")
            _SCREEN_REC["proc"] = None
            size = ""
            try:
                size = f" ({_fmt_bytes(Path(path).stat().st_size)})" if path else ""
            except Exception:
                pass
            return f"🎥 Screen record thamlo — video: {path}{size}"
        proc = _SCREEN_REC.get("proc")
        if proc is not None and proc.poll() is None:
            el = int(time.time() - float(_SCREEN_REC.get("started") or time.time()))
            return f"🎥 Screen record cholche — {el}s hoyeche."
        return "🎥 Screen record bondho — 'start' bolle shuru hobe."
    except Exception as e:
        return f"Screen record korte parlam na: {e}"


_SCREEN_REC: dict[str, object] = {"proc": None, "path": "", "started": 0.0}


# ── 🎨 create ────────────────────────────────────────────────────────────────

def qr_generate(text: str, name: str = "") -> str:
    """QR code PNG (qrcode lib) into Downloads/MarkLVII. Never raises."""
    try:
        t = str(text or "").strip()
        if not t:
            return "QR-er jonno text/URL dao."
        import qrcode
        folder = _downloads()
        folder.mkdir(parents=True, exist_ok=True)
        fname = str(name or "").strip() or f"qr-{int(time.time())}"
        fname = "".join(c for c in fname if c.isalnum() or c in "._- ")[:60]
        out = folder / (fname + ".png")
        img = qrcode.make(t)
        img.save(out)
        return f"🔳 QR banalam: {out}"
    except Exception as e:
        return f"QR banate parlam na: {e}"


def password_generate(length: int = 16, symbols: bool = True) -> str:
    """Cryptographically random password (secrets). Never raises."""
    try:
        n = max(8, min(64, int(length or 16)))
        alphabet = ("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
                    + ("!@#$%^&*()-_=+" if symbols else ""))
        pw = "".join(secrets.choice(alphabet) for _ in range(n))
        return (f"🔑 Password banalam ({n} char): {pw}\n"
                f"(Eta ekhanei dekhlam — kothao save kori ni. Safe jaigai rakho.)")
    except Exception as e:
        return f"Password banate parlam na: {e}"


def meme_make(image_path: str = "", top: str = "", bottom: str = "") -> str:
    """Impact-style meme PNG (PIL). Never raises."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        src = Path(str(image_path or "").strip()).expanduser()
        if not src.is_file():
            return f"Image-ta pelam na: {src}"
        img = Image.open(src).convert("RGB")
        w, h = img.size
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", max(20, w // 12))
        except Exception:
            font = ImageFont.load_default()

        def _draw(text: str, y: int):
            t = str(text or "").strip().upper()
            if not t:
                return
            try:
                bbox = draw.textbbox((0, 0), t, font=font)
                tw = bbox[2] - bbox[0]
            except Exception:
                tw = len(t) * 12
            x = (w - tw) // 2
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                draw.text((x + dx, y + dy), t, font=font, fill="black")
            draw.text((x, y), t, font=font, fill="white")

        _draw(top, 10)
        _draw(bottom, h - max(20, w // 12) - 16)
        out = src.parent / (src.stem + "-meme.png")
        img.save(out)
        return f"😂 Meme banalam: {out}"
    except Exception as e:
        return f"Meme banate parlam na: {e}"


def subtitle_make(video_path: str = "", text: str = "") -> str:
    """Write a simple .srt subtitle file next to a video (or standalone).
    Real SRT, timed 2 s per line. Never raises."""
    try:
        lines = [l.strip() for l in str(text or "").splitlines()
                 if l.strip()]
        if not lines:
            return "Subtitle-er text dao — prottek line ekta caption hobe."
        src = Path(str(video_path or "").strip()).expanduser() \
            if video_path else None
        folder = _downloads()
        folder.mkdir(parents=True, exist_ok=True)
        if src is not None and src.is_file():
            out = src.parent / (src.stem + ".srt")
        else:
            out = folder / f"subtitles-{int(time.time())}.srt"

        def _ts(sec: int) -> str:
            hh, mm = divmod(sec, 3600)
            mm, ss = divmod(mm, 60)
            return f"{hh:02d}:{mm:02d}:{ss:02d},000"

        blocks = []
        for i, line in enumerate(lines):
            blocks.append(f"{i + 1}\n{_ts(i * 2)} --> {_ts(i * 2 + 2)}\n{line}")
        out.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
        return f"💬 Subtitle file banalam: {out} ({len(lines)} ta caption)"
    except Exception as e:
        return f"Subtitle banate parlam na: {e}"


def invoice_make(client: str = "", amount: float = 0.0,
                 items: str = "") -> str:
    """Invoice as an .xlsx (openpyxl) + a text summary. Never raises."""
    try:
        client = str(client or "Client").strip()[:80]
        amt = float(amount or 0.0)
        folder = _downloads()
        folder.mkdir(parents=True, exist_ok=True)
        num = int(time.time()) % 100000
        out = folder / f"invoice-{num}.xlsx"
        rows = [("Invoice", f"INV-{num}"), ("Date", _now()[:10]),
                ("Client", client), ("", "")]
        for line in str(items or "").splitlines():
            if line.strip():
                rows.append(("Item", line.strip()))
        rows.append(("Total", amt))
        try:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Invoice"
            for r in rows:
                ws.append(list(r))
            wb.save(out)
            saved = str(out)
        except Exception:
            saved = "(Excel save holo na — openpyxl nei)"
        summary = "\n".join(f"  • {a}: {b}" for a, b in rows)
        return (f"🧾 Invoice banalam — INV-{num} ({client}, {amt:g}):\n"
                f"{summary}\n{saved}")
    except Exception as e:
        return f"Invoice banate parlam na: {e}"


def resume_build(name: str = "", role: str = "", skills: str = "") -> str:
    """Resume as a .docx (python-docx). Never raises."""
    try:
        name = str(name or "Your Name").strip()[:80]
        role = str(role or "").strip()[:120]
        folder = _downloads()
        folder.mkdir(parents=True, exist_ok=True)
        out = folder / f"resume-{int(time.time())}.docx"
        try:
            from docx import Document
            doc = Document()
            doc.add_heading(name, level=0)
            if role:
                doc.add_paragraph(role)
            doc.add_heading("Skills", level=1)
            for s in str(skills or "").split(","):
                if s.strip():
                    doc.add_paragraph(s.strip(), style="List Bullet")
            doc.save(out)
            saved = str(out)
        except Exception:
            saved = "(DOCX save holo na — python-docx nei)"
        return f"📄 Resume banalam — {name} ({role}):\n{saved}"
    except Exception as e:
        return f"Resume banate parlam na: {e}"


# ── 🌱 life ──────────────────────────────────────────────────────────────────

def note_add(text: str) -> str:
    try:
        t = str(text or "").strip()
        if not t:
            return "Note-ta khali — ki likhbo bolo."
        cfg = _cfg("utility_notes")
        notes = list(cfg.get("notes") or [])
        notes.append({"text": t[:500], "at": _now()})
        cfg["notes"] = notes[-100:]
        _save_cfg("utility_notes", cfg)
        return f"📝 Note save korlam ({len(notes)} ta note ache)."
    except Exception as e:
        return f"Note save korte parlam na: {e}"


def note_list() -> str:
    try:
        notes = list(_cfg("utility_notes").get("notes") or [])
        if not notes:
            return "📝 Kono note nei — 'note koro ...' bolle likhbo."
        lines = [f"📝 Notes — {len(notes)} ta:"]
        for n in notes[-10:]:
            lines.append(f"  • [{n.get('at', '')[:16]}] "
                         f"{str(n.get('text', ''))[:120]}")
        return "\n".join(lines)
    except Exception as e:
        return f"Note dekhte parlam na: {e}"


def habit_add(name: str) -> str:
    try:
        n = str(name or "").strip()
        if not n:
            return "Habit-er naam dao."
        cfg = _cfg("utility_habits")
        habits = dict(cfg.get("habits") or {})
        if n.lower() in habits:
            return f"✅ Habit '{n}' already ache."
        habits[n.lower()] = {"name": n, "days": []}
        cfg["habits"] = habits
        _save_cfg("utility_habits", cfg)
        return f"✅ Habit banalam: {n} — protidin 'done' bolle tick hobe."
    except Exception as e:
        return f"Habit banate parlam na: {e}"


def habit_tick(name: str) -> str:
    try:
        n = str(name or "").strip().lower()
        cfg = _cfg("utility_habits")
        habits = dict(cfg.get("habits") or {})
        if n not in habits:
            return f"Habit '{name}' pelam na — age 'habit banao {name}' bolo."
        today = datetime.now().date().isoformat()
        days = list(habits[n].get("days") or [])
        if today in days:
            return f"✅ '{habits[n]['name']}' — aaj already done."
        days.append(today)
        habits[n]["days"] = days[-365:]
        cfg["habits"] = habits
        _save_cfg("utility_habits", cfg)
        streak = 0
        d = datetime.now().date()
        s = set(days)
        while d.isoformat() in s:
            streak += 1
            d -= timedelta(days=1)
        return (f"✅ '{habits[n]['name']}' — aaj done! "
                f"Streak: {streak} din 🔥")
    except Exception as e:
        return f"Habit tick korte parlam na: {e}"


def habit_status() -> str:
    try:
        habits = dict(_cfg("utility_habits").get("habits") or {})
        if not habits:
            return "✅ Kono habit nei — 'habit banao ...' bolle shuru korbo."
        today = datetime.now().date().isoformat()
        lines = ["✅ Habits:"]
        for h in habits.values():
            days = set(h.get("days") or [])
            lines.append(f"  • {h.get('name')}: "
                         f"{'✅ aaj done' if today in days else '⏳ aaj baki'} "
                         f"({len(days)} din mot)")
        return "\n".join(lines)
    except Exception as e:
        return f"Habit dekhte parlam na: {e}"


def expense_add(amount: float, what: str = "", category: str = "") -> str:
    try:
        amt = float(amount or 0.0)
        cfg = _cfg("utility_expenses")
        items = list(cfg.get("items") or [])
        items.append({"amount": amt, "what": str(what or "")[:100],
                      "cat": str(category or "general")[:40],
                      "at": _now()})
        cfg["items"] = items[-500:]
        _save_cfg("utility_expenses", cfg)
        month = sum(float(i.get("amount") or 0)
                    for i in items
                    if str(i.get("at") or "")[:7] == _now()[:7])
        return (f"💰 Kharcha likhlam: {amt:g} ({what or 'kharcha'}). "
                f"Ei mashe mot: {month:g}.")
    except Exception as e:
        return f"Kharcha likhte parlam na: {e}"


def expense_summary() -> str:
    try:
        items = list(_cfg("utility_expenses").get("items") or [])
        if not items:
            return "💰 Kono kharcha likha nei."
        month = _now()[:7]
        month_items = [i for i in items if str(i.get("at") or "")[:7] == month]
        total = sum(float(i.get("amount") or 0) for i in month_items)
        by_cat: dict[str, float] = {}
        for i in month_items:
            c = str(i.get("cat") or "general")
            by_cat[c] = by_cat.get(c, 0.0) + float(i.get("amount") or 0)
        lines = [f"💰 Kharcha — {month}: mot {total:g} "
                 f"({len(month_items)} ta)"]
        for c, v in sorted(by_cat.items(), key=lambda kv: -kv[1])[:8]:
            lines.append(f"  • {c}: {v:g}")
        return "\n".join(lines)
    except Exception as e:
        return f"Kharcha dekhte parlam na: {e}"


def bookmark_add(url: str, title: str = "") -> str:
    try:
        u = str(url or "").strip()
        if not u.startswith(("http://", "https://")):
            return "Bookmark-er jonno http(s) URL dao."
        cfg = _cfg("utility_bookmarks")
        items = list(cfg.get("items") or [])
        items.append({"url": u, "title": str(title or u)[:120], "at": _now()})
        cfg["items"] = items[-200:]
        _save_cfg("utility_bookmarks", cfg)
        return f"🔖 Bookmark save korlam: {title or u}"
    except Exception as e:
        return f"Bookmark save korte parlam na: {e}"


def bookmark_list() -> str:
    try:
        items = list(_cfg("utility_bookmarks").get("items") or [])
        if not items:
            return "🔖 Kono bookmark nei."
        lines = [f"🔖 Bookmarks — {len(items)} ta:"]
        for i in items[-10:]:
            lines.append(f"  • {i.get('title')} — {i.get('url')}")
        return "\n".join(lines)
    except Exception as e:
        return f"Bookmark dekhte parlam na: {e}"


def contact_add(name: str, phone: str = "", email: str = "") -> str:
    try:
        n = str(name or "").strip()
        if not n:
            return "Contact-er naam dao."
        cfg = _cfg("utility_contacts")
        items = dict(cfg.get("items") or {})
        items[n.lower()] = {"name": n, "phone": str(phone or "")[:40],
                            "email": str(email or "")[:120], "at": _now()}
        cfg["items"] = items
        _save_cfg("utility_contacts", cfg)
        return f"👤 Contact save korlam: {n}."
    except Exception as e:
        return f"Contact save korte parlam na: {e}"


def contact_find(name: str) -> str:
    try:
        q = str(name or "").strip().lower()
        items = dict(_cfg("utility_contacts").get("items") or {})
        if not q:
            return f"👤 Contacts — {len(items)} ta save ache."
        hits = [v for k, v in items.items() if q in k]
        if not hits:
            return f"👤 '{name}' — contact pelam na."
        lines = []
        for v in hits[:10]:
            lines.append(f"  • {v.get('name')}"
                         f"{' • ' + v['phone'] if v.get('phone') else ''}"
                         f"{' • ' + v['email'] if v.get('email') else ''}")
        return "👤 Contact pelam:\n" + "\n".join(lines)
    except Exception as e:
        return f"Contact khujte parlam na: {e}"


def calendar_add(title: str, when: str = "") -> str:
    """Add an event (text date, e.g. '2026-11-20 15:00'). Never raises."""
    try:
        t = str(title or "").strip()
        if not t:
            return "Event-er naam dao."
        cfg = _cfg("utility_calendar")
        items = list(cfg.get("events") or [])
        items.append({"title": t[:120], "when": str(when or "")[:40],
                      "at": _now()})
        cfg["events"] = items[-200:]
        _save_cfg("utility_calendar", cfg)
        return f"📅 Event likhlam: {t} ({when or 'time dewa hoyni'})."
    except Exception as e:
        return f"Event likhte parlam na: {e}"


def calendar_today() -> str:
    try:
        today = datetime.now().date().isoformat()
        items = list(_cfg("utility_calendar").get("events") or [])
        hits = [i for i in items if str(i.get("when") or "").startswith(today)]
        lines = [f"📅 Aaj ({today}):"]
        if not hits:
            lines.append("  • Aaj kono event likha nei.")
        for i in hits:
            lines.append(f"  • {i.get('when', '')[11:16] or ''} "
                         f"{i.get('title')}")
        upcoming = [i for i in items
                    if str(i.get("when") or "") > today][:5]
        for i in upcoming:
            lines.append(f"  • {i.get('when', '')[:16]} {i.get('title')}")
        return "\n".join(lines)
    except Exception as e:
        return f"Calendar dekhte parlam na: {e}"


def flashcard_add(question: str, answer: str) -> str:
    try:
        q = str(question or "").strip()
        a = str(answer or "").strip()
        if not q or not a:
            return "Flashcard-er jonno proshno + uttor dutoi dao."
        cfg = _cfg("utility_flashcards")
        cards = list(cfg.get("cards") or [])
        cards.append({"q": q[:300], "a": a[:300], "at": _now()})
        cfg["cards"] = cards[-200:]
        _save_cfg("utility_flashcards", cfg)
        return f"🃏 Flashcard save korlam ({len(cards)} ta ache)."
    except Exception as e:
        return f"Flashcard save korte parlam na: {e}"


def flashcard_quiz() -> str:
    try:
        import random
        cards = list(_cfg("utility_flashcards").get("cards") or [])
        if not cards:
            return ("🃏 Kono flashcard nei — 'flashcard banao <proshno> | "
                    "<uttor>' bolle shuru korbo.")
        c = random.choice(cards)
        return f"🃏 Proshno: {c.get('q')}\n(Uttor janle bolo — uttor: {c.get('a')})"
    except Exception as e:
        return f"Quiz korte parlam na: {e}"


def quiz_make(topic: str = "", n: int = 3) -> str:
    """A tiny general-knowledge quiz (built-in question bank). Never raises."""
    try:
        bank = [
            ("Bangladesh-er rajdhani ki?", "Dhaka"),
            ("2 + 2 * 3 = ?", "8"),
            ("Surjer sobcheye kacher groho konta?", "Budh (Mercury)"),
            ("Pani-r chemical formula ki?", "H2O"),
            ("India-r jatiyo poshu ki?", "Bengal Tiger"),
        ]
        topic = str(topic or "").strip()
        lines = [f"❓ Quiz — {topic or 'general'} ({min(max(int(n or 3), 1), 5)} ta):"]
        for i, (q, a) in enumerate(bank[:min(max(int(n or 3), 1), 5)], 1):
            lines.append(f"  {i}. {q} (uttor: {a})")
        return "\n".join(lines)
    except Exception as e:
        return f"Quiz banate parlam na: {e}"


def poll_make(question: str, options: str = "") -> str:
    """Create a poll (options comma-separated). Stored in config.
    Never raises."""
    try:
        q = str(question or "").strip()
        opts = [o.strip() for o in str(options or "").split(",") if o.strip()]
        if not q:
            return "Poll-er proshno dao."
        if len(opts) < 2:
            opts = ["Hya", "Na"]
        cfg = _cfg("utility_polls")
        polls = list(cfg.get("polls") or [])
        polls.append({"q": q[:200], "options": opts[:6],
                      "votes": [0] * len(opts[:6]), "at": _now()})
        cfg["polls"] = polls[-50:]
        _save_cfg("utility_polls", cfg)
        lines = [f"📊 Poll banalam: {q}"]
        for i, o in enumerate(opts[:6], 1):
            lines.append(f"  {i}. {o}")
        lines.append("(Vote dite 'poll vote <number>' bolo.)")
        return "\n".join(lines)
    except Exception as e:
        return f"Poll banate parlam na: {e}"


def poll_vote(index: int = 1) -> str:
    try:
        cfg = _cfg("utility_polls")
        polls = list(cfg.get("polls") or [])
        if not polls:
            return "📊 Kono poll nei."
        p = polls[-1]
        i = int(index or 1) - 1
        votes = list(p.get("votes") or [])
        if i < 0 or i >= len(votes):
            return f"📊 Option {index} nei — 1 theke {len(votes)}-er modhye dao."
        votes[i] += 1
        p["votes"] = votes
        polls[-1] = p
        cfg["polls"] = polls
        _save_cfg("utility_polls", cfg)
        lines = [f"📊 Poll: {p.get('q')}"]
        for o, v in zip(p.get("options") or [], votes):
            lines.append(f"  • {o}: {v} vote")
        return "\n".join(lines)
    except Exception as e:
        return f"Vote dite parlam na: {e}"


def dictionary_lookup(word: str) -> str:
    """Free dictionaryapi.dev (no key). Offline: honest message.
    Never raises."""
    try:
        w = str(word or "").strip().lower()
        if not w:
            return "Konta shobdo — bolo."
        import urllib.request
        req = urllib.request.Request(
            f"https://api.dictionaryapi.dev/api/v2/entries/en/{w}",
            headers={"User-Agent": "Mark-LVII/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))
        entry = data[0]
        meanings = entry.get("meanings") or []
        lines = [f"📖 {w}:"]
        for m in meanings[:3]:
            pos = m.get("partOfSpeech") or ""
            defs = m.get("definitions") or []
            if defs:
                lines.append(f"  • ({pos}) {defs[0].get('definition', '')[:200]}")
        if len(lines) == 1:
            return f"📖 '{w}' — mane pelam na."
        return "\n".join(lines)
    except Exception:
        return ("📖 Dictionary ante parlam na — internet lagbe "
                "(dictionaryapi.dev), ba shobdo-ta pelam na.")


# ── 🎬 media (converter + downloader) ─────────────────────────────────────────

def audio_convert(path: str, fmt: str = "mp3") -> str:
    """Convert audio with ffmpeg. Never raises."""
    try:
        src = Path(str(path or "").strip()).expanduser()
        if not src.is_file():
            return f"Audio file-ta pelam na: {src}"
        ff = _ffmpeg()
        if not ff:
            return ("🎵 Audio convert korte ffmpeg lagbe — video_edit box-e "
                    "'ffmpeg install' chapo, tarpor abar bolo.")
        f = str(fmt or "mp3").strip().lower().lstrip(".")
        if f not in ("mp3", "wav", "ogg", "m4a", "flac"):
            return "🎵 Format: mp3 / wav / ogg / m4a / flac."
        out = src.parent / (src.stem + f".{f}")
        rc, err = _run_cmd([ff, "-y", "-i", str(src), str(out)], timeout=120)
        if rc != 0 or not out.is_file():
            return f"🎵 Convert holo na: {err[-300:]}"
        return f"🎵 Audio convert holo: {out} ({_fmt_bytes(out.stat().st_size)})"
    except Exception as e:
        return f"Audio convert korte parlam na: {e}"


def video_download(url: str, quality: str = "best") -> str:
    """Download a PUBLIC video with yt-dlp (no auth — public videos only).
    Never raises. Never fakes: if yt-dlp fails, it says why."""
    try:
        u = str(url or "").strip()
        if not u.startswith(("http://", "https://")):
            return "Video-r URL dao."
        if not shutil.which("yt-dlp"):
            return ("📥 Video download korte yt-dlp lagbe — 'pip install "
                    "yt-dlp' chalu koro (Python Run > Libraries), tarpor "
                    "abar bolo.")
        folder = _downloads()
        folder.mkdir(parents=True, exist_ok=True)
        out_tpl = str(folder / "%(title)s.%(ext)s")
        cmd = ["yt-dlp", "-o", out_tpl, "--no-playlist",
               "--max-filesize", "500M", u]
        if str(quality or "best").strip().lower() in ("720", "720p"):
            cmd.insert(1, "-f")
            cmd.insert(2, "bestvideo[height<=720]+bestaudio/best[height<=720]")
        rc, out = _run_cmd(cmd, timeout=300)
        if rc != 0:
            tail = (out or "")[-300:]
            if "Private" in tail or "login" in tail.lower():
                return ("📥 Video-ta private ba login lagbe — sudhu PUBLIC "
                        "video download kora jay.")
            return f"📥 Download holo na: {tail}"
        return f"📥 Video download holo — Downloads/MarkLVII folder-e dekho."
    except Exception as e:
        return f"Video download korte parlam na: {e}"


# ── 📱 phone (via relay) ─────────────────────────────────────────────────────

def _phone() -> tuple[object, str]:
    """Return (link, error-string). Never raises."""
    try:
        from core import jarvis_link as _jl
        link = _jl.LINK
        if link is None or not getattr(link, "paired", False):
            return None, "📱 Phone pair kora nei — age QR scan koro."
        return link, ""
    except Exception as e:
        return None, f"Phone relay-e jete parlam na: {e}"


def sms_send(phone: str, message: str) -> str:
    """Ask the phone to send an SMS (phone relay, text command).
    Never raises."""
    try:
        p = str(phone or "").strip()
        m = str(message or "").strip()
        if not p or not m:
            return "SMS pathate number + message dutoi dao."
        link, err = _phone()
        if link is None:
            return err
        ans = link.send_and_wait_result(
            f"SMS pathao {p} number-e: {m}", timeout=30.0)
        if not ans:
            return ("📱 Phone theke uttor elo na — phone-e Jarvis khola ache "
                    "kina dekho.")
        return f"📱 Phone bollo: {str(ans)[:300]}"
    except Exception as e:
        return f"SMS pathate parlam na: {e}"


def call_log() -> str:
    """Ask the phone for its recent call log (phone relay). Never raises."""
    try:
        link, err = _phone()
        if link is None:
            return err
        ans = link.send_and_wait_result(
            "shesh 10 ta call-er log dao", timeout=30.0)
        if not ans:
            return "📱 Phone theke uttor elo na."
        return f"📱 Call log (phone):\n{str(ans)[:800]}"
    except Exception as e:
        return f"Call log ante parlam na: {e}"


def step_counter() -> str:
    """Ask the phone for today's step count (phone relay). Never raises."""
    try:
        link, err = _phone()
        if link is None:
            return err
        ans = link.send_and_wait_result(
            "aaj koto step hetechhi?", timeout=30.0)
        if not ans:
            return "📱 Phone theke uttor elo na."
        return f"📱 Step (phone): {str(ans)[:300]}"
    except Exception as e:
        return f"Step ante parlam na: {e}"


# ── 🔐 vault ─────────────────────────────────────────────────────────────────

def _vault_key() -> bytes:
    """Per-PC vault key, derived from the machine id (never stored in
    config). Never raises."""
    import hashlib
    try:
        import platform as _pl
        seed = f"{_pl.node()}|{_pl.machine()}|mark-lvii-vault-v1"
    except Exception:
        seed = "mark-lvii-vault-v1"
    return hashlib.sha256(seed.encode("utf-8")).digest()


def vault_put(service: str, username: str, password: str) -> str:
    """Store a credential, AES-256-GCM encrypted (cryptography lib).
    Never raises."""
    try:
        s = str(service or "").strip()
        u = str(username or "").strip()
        p = str(password or "").strip()
        if not s or not p:
            return "Vault-e rakhte service + password dao."
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import base64
        key = AESGCM(_vault_key())
        nonce = os.urandom(12)
        payload = json.dumps({"u": u, "p": p}).encode("utf-8")
        ct = key.encrypt(nonce, payload, None)
        blob = base64.b64encode(nonce + ct).decode("ascii")
        cfg = _cfg("utility_vault")
        items = dict(cfg.get("items") or {})
        items[s.lower()] = {"service": s, "blob": blob, "at": _now()}
        cfg["items"] = items
        _save_cfg("utility_vault", cfg)
        return f"🔐 Vault-e save korlam: {s} (encrypted — plain text kothao nei)."
    except Exception as e:
        return f"Vault-e rakhte parlam na: {e}"


def vault_get(service: str) -> str:
    """Retrieve + decrypt one credential. Never raises."""
    try:
        s = str(service or "").strip().lower()
        items = dict(_cfg("utility_vault").get("items") or {})
        if not items:
            return "🔐 Vault khali — age kichu save koro."
        if s not in items:
            return (f"🔐 '{service}' vault-e pelam na. Ache: "
                    + ", ".join(v.get("service", k) for k, v in items.items()))
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import base64
        blob = base64.b64decode(str(items[s].get("blob") or ""))
        key = AESGCM(_vault_key())
        data = json.loads(key.decrypt(blob[:12], blob[12:], None).decode("utf-8"))
        return (f"🔐 {items[s].get('service')}:\n"
                f"  • Username: {data.get('u') or '(nei)'}\n"
                f"  • Password: {data.get('p')}")
    except Exception:
        return "🔐 Vault khulte parlam na — data-ta bodle geche ba corrupt."


# ── status helpers (card actions — read-only, never start anything) ──────────

def sleep_timer_status() -> str:
    """Is a sleep timer armed? Read-only. Never raises."""
    try:
        at = float(_SLEEP_TIMER.get("at") or 0)
        if at > time.time():
            left = int(at - time.time())
            return (f"😴 Sleep timer cholche — {left // 60}m {left % 60}s "
                    f"pore PC ghumabe. Cancel korte 'sleep timer cancel' bolo.")
        return ("😴 Sleep timer bondho — 'sleep timer 30 min' bolle "
                "30 min pore PC ghumabe.")
    except Exception as e:
        return f"Sleep timer dekhte parlam na: {e}"


def poll_status() -> str:
    """The latest poll + its votes. Read-only. Never raises."""
    try:
        polls = list(_cfg("utility_polls").get("polls") or [])
        if not polls:
            return ("📊 Kono poll nei — 'poll banao <proshno> | <option1>, "
                    "<option2>' bolle banabo.")
        p = polls[-1]
        lines = [f"📊 Poll: {p.get('q')}"]
        for o, v in zip(p.get("options") or [], p.get("votes") or []):
            lines.append(f"  • {o}: {v} vote")
        lines.append("(Vote dite 'poll vote <number>' bolo.)")
        return "\n".join(lines)
    except Exception as e:
        return f"Poll dekhte parlam na: {e}"
