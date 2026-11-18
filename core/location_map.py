"""core/location_map.py — 🗺️ PHONE LOCATION MAP (OpenStreetMap tiles).

The phone sends its GPS fix over the relay (kind="location_update", or
the LOCATION_UPDATE:: text prefix — see core/jarvis_link.py); the fixes
live in core/phone_location.py (last 50). This module turns the newest
fix into a REAL map picture: it downloads the OpenStreetMap tiles around
the fix, stitches them with PIL and draws a red marker on the phone's
exact spot. No map library, no browser, no fake coordinates — when
there is no fix, or no internet for tiles, it says so plainly and
returns "" instead of a picture of nowhere.

Tiles: https://tile.openstreetmap.org/{z}/{x}/{y}.png (free, no key).
Cache: memory/location_map.jpg, refreshed only when the fix moves.
Nothing here imports Qt; nothing here ever raises.
"""
from __future__ import annotations

import io
import math
import os
import threading
import time
import urllib.request
from pathlib import Path

_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
_ZOOM = 15
_TILE = 256
_COLS, _ROWS = 3, 2
_TIMEOUT = 5.0
_LOCK = threading.Lock()
_LAST_KEY = {"key": None, "path": ""}


def _base_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def latlon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    """(lat, lon) -> OSM tile (x, y) at zoom. Pure maths, testable."""
    lat = max(-85.05112878, min(85.05112878, float(lat)))
    lon = float(lon)
    n = 2.0 ** int(zoom)
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad))
             / math.pi) / 2.0 * n)
    return max(0, min(int(n) - 1, x)), max(0, min(int(n) - 1, y))


def tile_url(lat: float, lon: float, zoom: int = _ZOOM) -> str:
    """The OSM tile URL covering a fix. Pure, no network."""
    x, y = latlon_to_tile(lat, lon, zoom)
    return _TILE_URL.format(z=int(zoom), x=x, y=y)


def maps_link(lat: float, lon: float) -> str:
    """Google Maps link for a fix (opens in any browser)."""
    return f"https://www.google.com/maps?q={float(lat)},{float(lon)}"


def _fetch_tile(x: int, y: int, zoom: int) -> bytes | None:
    try:
        url = _TILE_URL.format(z=int(zoom), x=int(x), y=int(y))
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mark-LVII/1.0 (phone location map)"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            data = r.read()
        return data if data else None
    except Exception:
        return None


def map_image_path(lat: float | None = None, lon: float | None = None,
                   zoom: int = _ZOOM, cache: str = "") -> str:
    """Build (or reuse the cached) map picture for the newest fix.

    Returns the saved JPEG path, or "" when there is no fix or the
    tiles could not be fetched. Never raises."""
    try:
        if lat is None or lon is None:
            try:
                from core import phone_location as _pl
                fix = _pl.last_fix()
                if not fix:
                    return ""
                lat, lon = float(fix["lat"]), float(fix["lon"])
            except Exception:
                return ""
        lat, lon = float(lat), float(lon)
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return ""
        key = (round(lat, 4), round(lon, 4), int(zoom))
        with _LOCK:
            if _LAST_KEY.get("key") == key and _LAST_KEY.get("path"):
                p = Path(str(_LAST_KEY["path"]))
                if p.is_file():
                    return str(p)
        try:
            from PIL import Image, ImageDraw
        except Exception:
            return ""
        cx, cy = latlon_to_tile(lat, lon, zoom)
        # Centre the phone in the middle of a 3x2 tile grid.
        x0, y0 = cx - 1, cy - 1
        canvas = Image.new("RGB", (_COLS * _TILE, _ROWS * _TILE),
                           (220, 225, 230))
        got_any = False
        for dx in range(_COLS):
            for dy in range(_ROWS):
                data = _fetch_tile(x0 + dx, y0 + dy, zoom)
                if not data:
                    continue
                try:
                    tile = Image.open(io.BytesIO(data)).convert("RGB")
                    canvas.paste(tile, (dx * _TILE, dy * _TILE))
                    got_any = True
                except Exception:
                    continue
        if not got_any:
            return ""
        # Marker: red pin at the exact centre + a soft ring.
        mx, my = _COLS * _TILE // 2, _ROWS * _TILE // 2
        draw = ImageDraw.Draw(canvas)
        draw.ellipse([mx - 26, my - 26, mx + 26, my + 26],
                     outline=(220, 38, 38), width=3)
        draw.ellipse([mx - 10, my - 10, mx + 10, my + 10],
                     fill=(220, 38, 38), outline=(255, 255, 255), width=2)
        draw.polygon([(mx, my + 22), (mx - 7, my + 8), (mx + 7, my + 8)],
                     fill=(220, 38, 38))
        out = Path(str(cache or "")).expanduser() if cache else \
            _base_dir() / "memory" / "location_map.jpg"
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            canvas.save(str(out), format="JPEG", quality=82)
        except Exception:
            return ""
        with _LOCK:
            _LAST_KEY["key"] = key
            _LAST_KEY["path"] = str(out)
        return str(out)
    except Exception:
        return ""


def location_summary() -> str:
    """One plain-words block for the master screen / dashboard:
    last fix + history count + map link. Never raises."""
    try:
        from core import phone_location as _pl
        fix = _pl.last_fix()
        hist = _pl.history()
        if not fix:
            return ("📍 Phone-er location jani na ekhono — 'Find phone' chapo; "
                    "phone-e GPS + Location permission ON ar Owner monitoring "
                    "ON thakte hobe.")
        lines = [f"📍 Phone: Lat {fix.get('lat')}, Lng {fix.get('lon')} "
                 f"({fix.get('at') or ''})",
                 f"   {maps_link(float(fix['lat']), float(fix['lon']))}",
                 f"   History: {len(hist)} ta point (shesh 50 rakha hoy)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Location dekhte parlam na: {e}"


def history_points() -> list[dict]:
    """Last 50 fixes as {lat, lon, at, accuracy}. Never raises."""
    try:
        from core import phone_location as _pl
        return _pl.history()
    except Exception:
        return []
