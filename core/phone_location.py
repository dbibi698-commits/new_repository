"""core/phone_location.py — last-known phone location store (+ PC location).

WHAT EXISTS ON THE PHONE (checked 2026-11-17, read-only greps):
    * The phone app HAS get_location / find_phone tools (ToolExecutor.kt)
      and sends its location in the backend heartbeat — but ONLY when the
      user turned ON location tracking in Owner monitoring (server.js).
    * The phone relay (PcRelay.kt) handles kinds text / voice / tts /
      screen_req / result / clip / file — there is NO "location_req" kind,
      and the backend relay allowlist (server.js) also rejects it (400).
    * So there is NO dedicated Mark->phone location request path today.
      core/jarvis_link.py request_phone_location() sends kind="location_req"
      (for a future phone update) and falls back to the real existing path
      — a text command the phone's own AI answers with its get_location
      tool — then parses Lat/Lng out of the reply. When neither yields
      coordinates, the store stays empty and every caller reports the
      honest "location unavailable" string. Coordinates are NEVER faked.

Persistence: plugin_config["location"] through memory/config_manager.py
(never config/api_keys.json directly), capped at 50 fixes. Nothing here
imports Qt; nothing here ever raises.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from datetime import datetime

_NAMESPACE = "location"
_CAP = 50

_LATLNG_RE = re.compile(
    r"Lat\s*[:=]?\s*(-?\d+(?:\.\d+)?)[,\s]+Lng\s*[:=]?\s*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE)
_LATLNG_RE2 = re.compile(
    r"(-?\d{1,3}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)")

_LOCK = threading.Lock()
_PC_CACHE = {"at": 0.0, "value": None}


def _now_iso() -> str:
    try:
        return datetime.now().isoformat(timespec="seconds")
    except Exception:
        return ""


def parse_location_text(text: str) -> dict | None:
    """Pull {lat, lon} out of a phone reply like
    "📍 Tomar location: ... Lat 22.57, Lng 88.36". None when no
    plausible coordinates are in the text. Never raises."""
    try:
        s = str(text or "")
        m = _LATLNG_RE.search(s) or _LATLNG_RE2.search(s)
        if not m:
            return None
        lat, lon = float(m.group(1)), float(m.group(2))
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return None
        if lat == 0.0 and lon == 0.0:
            return None
        return {"lat": lat, "lon": lon}
    except Exception:
        return None


def record_fix(lat: float, lon: float, accuracy=None) -> dict | None:
    """Store one fix (lat, lon, accuracy metres, at). Returns the fix,
    or None when the coordinates are unusable. Never raises."""
    try:
        lat, lon = float(lat), float(lon)
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return None
        if lat == 0.0 and lon == 0.0:
            return None
        fix = {
            "lat": lat, "lon": lon,
            "accuracy": (float(accuracy) if accuracy is not None else None),
            "at": _now_iso(),
        }
        from memory.config_manager import get_plugin_config, save_plugin_config
        data = get_plugin_config(_NAMESPACE) or {}
        hist = list(data.get("history") or [])
        hist.append(fix)
        hist = hist[-_CAP:]
        save_plugin_config(_NAMESPACE, {"history": hist, "last": fix})
        return fix
    except Exception:
        return None


def last_fix() -> dict | None:
    """The newest stored fix, or None. Never raises."""
    try:
        from memory.config_manager import get_plugin_config
        data = get_plugin_config(_NAMESPACE) or {}
        last = data.get("last")
        if isinstance(last, dict) and "lat" in last and "lon" in last:
            return dict(last)
        hist = list(data.get("history") or [])
        return dict(hist[-1]) if hist else None
    except Exception:
        return None


def history() -> list[dict]:
    """Last 50 fixes, oldest first. Never raises."""
    try:
        from memory.config_manager import get_plugin_config
        data = get_plugin_config(_NAMESPACE) or {}
        return [dict(h) for h in (data.get("history") or [])][- _CAP:]
    except Exception:
        return []


def reverse_geocode(lat: float, lon: float, timeout: float = 3.0) -> str | None:
    """Nominatim reverse-geocode (display name), or None on any failure.
    Only called when a real fix exists. Never raises."""
    try:
        url = ("https://nominatim.openstreetmap.org/reverse?format=json"
               f"&lat={float(lat)}&lon={float(lon)}&zoom=14")
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mark-LVII/1.0 (phone location)"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        name = str((data or {}).get("display_name") or "").strip()
        return name or None
    except Exception:
        return None


def pc_location() -> dict:
    """This PC's approximate location from its public IP (ip-api.com,
    no key, cached 1 h). {"city": ..., "approximate": True} or
    {"city": "unknown", "approximate": True}. Never raises."""
    try:
        now = time.monotonic()
        with _LOCK:
            if _PC_CACHE["value"] is not None and (now - _PC_CACHE["at"]) < 3600:
                return dict(_PC_CACHE["value"])
        city = "unknown"
        try:
            req = urllib.request.Request(
                "http://ip-api.com/json/?fields=status,city,country",
                headers={"User-Agent": "Mark-LVII/1.0"})
            with urllib.request.urlopen(req, timeout=3) as r:
                data = json.loads(r.read().decode("utf-8"))
            if (data or {}).get("status") == "success":
                parts = [str(data.get("city") or "").strip(),
                         str(data.get("country") or "").strip()]
                city = ", ".join(p for p in parts if p) or "unknown"
        except Exception:
            city = "unknown"
        value = {"city": city, "approximate": True}
        with _LOCK:
            _PC_CACHE["at"] = now
            _PC_CACHE["value"] = dict(value)
        return value
    except Exception:
        return {"city": "unknown", "approximate": True}
