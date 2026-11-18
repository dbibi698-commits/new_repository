"""tests/test_location_map.py — 📍 LOCATION: OSM tile math, map image
(stitching with real PIL tiles, network mocked), history cap 50,
location_summary, and the relay location_update handling in
jarvis_link (mocked link, no network).

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only (+ PIL, already in requirements). Network + config mocked.
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import location_map as lm  # noqa: E402
from core import phone_location as pl  # noqa: E402


def _png_bytes() -> bytes:
    from PIL import Image
    img = Image.new("RGB", (256, 256), (200, 210, 220))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestTileMath(unittest.TestCase):
    def test_latlon_to_tile_known(self):
        # Dhaka ~23.81, 90.41 at zoom 15.
        x, y = lm.latlon_to_tile(23.8103, 90.4125, 15)
        self.assertTrue(24000 < x < 25000)
        self.assertTrue(14000 < y < 14300)

    def test_tile_url_format(self):
        url = lm.tile_url(23.8103, 90.4125, 15)
        self.assertTrue(url.startswith("https://tile.openstreetmap.org/15/"))
        self.assertTrue(url.endswith(".png"))

    def test_maps_link(self):
        link = lm.maps_link(23.5, 90.5)
        self.assertIn("google.com/maps?q=23.5,90.5", link)


class TestMapImage(unittest.TestCase):
    def setUp(self):
        lm._LAST_KEY["key"] = None
        lm._LAST_KEY["path"] = ""

    def test_no_fix_returns_empty(self):
        with mock.patch("core.phone_location.last_fix", return_value=None):
            self.assertEqual(lm.map_image_path(), "")

    def test_stitches_tiles_and_draws_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "map.jpg"
            with mock.patch("core.location_map._fetch_tile",
                            return_value=_png_bytes()):
                path = lm.map_image_path(23.8103, 90.4125, zoom=15,
                                         cache=str(out))
            self.assertEqual(path, str(out))
            self.assertTrue(out.is_file())
            self.assertGreater(out.stat().st_size, 1000)
            from PIL import Image
            img = Image.open(out)
            self.assertEqual(img.size, (768, 512))  # 3x2 tiles

    def test_tile_failure_returns_empty(self):
        with mock.patch("core.location_map._fetch_tile",
                        return_value=None):
            self.assertEqual(lm.map_image_path(23.8, 90.4), "")

    def test_cached_path_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "map.jpg"
            with mock.patch("core.location_map._fetch_tile",
                            return_value=_png_bytes()):
                p1 = lm.map_image_path(23.81, 90.41, cache=str(out))
            with mock.patch("core.location_map._fetch_tile",
                            side_effect=AssertionError("must not fetch")):
                p2 = lm.map_image_path(23.81, 90.41, cache=str(out))
            self.assertEqual(p1, p2)


class TestHistoryCap(unittest.TestCase):
    def test_cap_is_50(self):
        self.assertEqual(pl._CAP, 50)

    def test_record_and_history(self):
        store = {}
        with mock.patch("memory.config_manager.get_plugin_config",
                        lambda ns: dict(store.get(ns) or {})), \
                mock.patch("memory.config_manager.save_plugin_config",
                           lambda ns, v: store.__setitem__(ns, dict(v))):
            for i in range(55):
                pl.record_fix(23.0 + i * 0.01, 90.0)
            hist = pl.history()
            self.assertEqual(len(hist), 50)
            self.assertAlmostEqual(hist[0]["lat"], 23.0 + 5 * 0.01)

    def test_invalid_fix_rejected(self):
        self.assertIsNone(pl.record_fix(0.0, 0.0))
        self.assertIsNone(pl.record_fix(200.0, 90.0))

    def test_location_summary(self):
        with mock.patch("core.phone_location.last_fix",
                        return_value={"lat": 23.8, "lon": 90.4,
                                      "at": "2026-11-18T10:00:00"}), \
                mock.patch("core.phone_location.history",
                           return_value=[{"lat": 23.8, "lon": 90.4}] * 3):
            s = lm.location_summary()
        self.assertIn("23.8", s)
        self.assertIn("3 ta point", s)

    def test_location_summary_no_fix(self):
        with mock.patch("core.phone_location.last_fix",
                        return_value=None), \
                mock.patch("core.phone_location.history",
                           return_value=[]):
            s = lm.location_summary()
        self.assertIn("jani na", s)


class TestRelayLocationUpdate(unittest.TestCase):
    def _link(self):
        from core import jarvis_link as jl
        link = jl.JarvisLink.__new__(jl.JarvisLink)
        link.log = lambda *a: None
        link.last_phone_seen = ""
        return link

    def test_location_update_kind_records_fix(self):
        store = {}
        with mock.patch("memory.config_manager.get_plugin_config",
                        lambda ns: dict(store.get(ns) or {})), \
                mock.patch("memory.config_manager.save_plugin_config",
                           lambda ns, v: store.__setitem__(ns, dict(v))):
            link = self._link()
            link._handle_message({"kind": "location_update",
                                  "text": '{"lat": 23.81, "lng": 90.41}'})
            self.assertTrue(link.last_phone_seen)
            hist = pl.history()
            self.assertTrue(any(abs(h["lat"] - 23.81) < 1e-6 for h in hist))

    def test_location_update_text_prefix(self):
        store = {}
        with mock.patch("memory.config_manager.get_plugin_config",
                        lambda ns: dict(store.get(ns) or {})), \
                mock.patch("memory.config_manager.save_plugin_config",
                           lambda ns, v: store.__setitem__(ns, dict(v))):
            link = self._link()
            link._e2e_decrypt = lambda s: s
            link._handle_message(
                {"kind": "text",
                 "text": "LOCATION_UPDATE::Lat: 23.5, Lng: 90.5"})
            hist = pl.history()
            self.assertTrue(any(abs(h["lat"] - 23.5) < 1e-6 for h in hist))


if __name__ == "__main__":
    unittest.main()
