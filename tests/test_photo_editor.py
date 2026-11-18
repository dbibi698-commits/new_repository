"""tests/test_photo_editor.py — 🖼️ Photo Editor: exact sheet spec + fallbacks.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib + PIL only. No rembg / cv2 in this VM — the background-remove
fallback selection is tested with injected fake modules, and the real
sheet test runs with method "none" (honest: neither library is here).
No network, no Qt, no real phone. Output PNGs go to temp dirs.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image, ImageDraw  # noqa: E402

from core import photo_editor as pe  # noqa: E402


def _test_photo(path: Path, w: int = 800, h: int = 1000) -> Path:
    """Blue background + red circle in the middle — the sheet tests can
    tell the copy (red centre) from the border (black) apart."""
    img = Image.new("RGB", (w, h), (30, 80, 200))
    d = ImageDraw.Draw(img)
    d.ellipse([w // 2 - 180, h // 2 - 180, w // 2 + 180, h // 2 + 180],
              fill=(220, 40, 40))
    img.save(path, "PNG")
    return path


class TestSizes(unittest.TestCase):
    def test_default_is_exactly_360x420(self):
        self.assertEqual(pe.size_px("1.2x1.4"), (360, 420))
        self.assertEqual(pe.size_px(), (360, 420))
        self.assertEqual(pe.size_px("nonsense"), (360, 420))

    def test_other_sizes(self):
        self.assertEqual(pe.size_px("2x2"), (600, 600))
        # 35x45 mm at 300 DPI: 35/25.4*300 = 413.4, 45/25.4*300 = 531.5
        self.assertEqual(pe.size_px("35x45mm"), (413, 531))

    def test_sheet_is_a4_300dpi(self):
        self.assertEqual((pe.SHEET_W, pe.SHEET_H), (2480, 3508))
        self.assertEqual(pe.DPI, 300)


class TestGrid(unittest.TestCase):
    def test_six_rects_default(self):
        rects = pe.sheet_grid()
        self.assertEqual(len(rects), 6)
        for (x, y, w, h) in rects:
            # 360x420 copy + 8 px border on each side.
            self.assertEqual((w, h), (376, 436))
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 260)  # below the top text band
            self.assertLessEqual(x + w, 2480)
            self.assertLessEqual(y + h, 3508)

    def test_rects_do_not_overlap(self):
        rects = pe.sheet_grid()
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                overlap_x = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
                overlap_y = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
                self.assertEqual(overlap_x * overlap_y, 0)

    def test_three_cols_two_rows(self):
        rects = pe.sheet_grid()
        xs = sorted({r[0] for r in rects})
        ys = sorted({r[1] for r in rects})
        self.assertEqual(len(xs), 3)
        self.assertEqual(len(ys), 2)


class TestSheetReal(unittest.TestCase):
    def test_full_sheet_layout_and_pixels(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo = _test_photo(Path(tmp) / "photo.png")
            out = str(Path(tmp) / "sheet.png")
            res = pe.make_a4_sheet(photo, out=out, top_text="AMAR PHOTO",
                                   bg_remove=False)
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["copies"], 6)
            self.assertEqual(res["copy_px"], (360, 420))
            self.assertEqual(res["sheet_px"], (2480, 3508))
            sheet = Image.open(out)
            self.assertEqual(sheet.size, (2480, 3508))
            dpi = tuple(round(v) for v in sheet.info.get("dpi", (0, 0)))
            self.assertEqual(dpi, (300, 300))
            px = sheet.convert("RGB")
            rects = pe.sheet_grid()
            for (x, y, w, h) in rects:
                # Copy centre = the red circle from the test photo.
                cx, cy = x + w // 2, y + h // 2
                r, g, b = px.getpixel((cx, cy))
                self.assertGreater(r, 150, (cx, cy))
                self.assertLess(b, 120, (cx, cy))
                # Border edge = black (8 px border around each copy).
                br, bg, bb = px.getpixel((x + 4, y + h // 2))
                self.assertLess(br + bg + bb, 60, (x, y))
            # Top-line text: some dark pixel in the text band.
            dark = 0
            for yy in range(70, 200, 4):
                for xx in range(400, 2080, 8):
                    r, g, b = px.getpixel((xx, yy))
                    if r + g + b < 300:
                        dark += 1
            self.assertGreater(dark, 0)

    def test_sheet_without_top_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo = _test_photo(Path(tmp) / "photo.png")
            res = pe.make_a4_sheet(photo, out=str(Path(tmp) / "s.png"),
                                   bg_remove=False)
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["top_text"], "")

    def test_missing_photo_is_honest(self):
        res = pe.make_a4_sheet("/no/such/photo.png")
        self.assertFalse(res["ok"])
        self.assertIn("pelam na", res["error"])

    def test_no_pdf_anywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo = _test_photo(Path(tmp) / "photo.png")
            res = pe.make_a4_sheet(photo, out=str(Path(tmp) / "s.png"),
                                   bg_remove=False)
            self.assertTrue(res["path"].endswith(".png"))
            self.assertFalse(Path(tmp, "s.pdf").exists())


class TestBackgroundRemove(unittest.TestCase):
    def test_rembg_used_when_available(self):
        import types
        fake = types.ModuleType("rembg")

        def _remove(img):
            out = img.convert("RGBA")
            out.putalpha(0)
            return out
        fake.remove = _remove
        img = Image.new("RGB", (40, 40), (10, 20, 30))
        with mock.patch.dict(sys.modules, {"rembg": fake}):
            out, method, _note = pe.remove_background(img)
        self.assertEqual(method, "rembg")
        self.assertEqual(out.getpixel((5, 5))[3], 0)

    def test_grabcut_fallback_when_no_rembg(self):
        import types
        import numpy as np
        fake = types.ModuleType("cv2")
        fake.GC_BGD, fake.GC_FGD = 0, 1
        fake.GC_PR_BGD, fake.GC_PR_FGD = 2, 3
        fake.GC_INIT_WITH_RECT = 0

        def _grabcut(arr, mask, rect, bgd, fgd, iters, mode):
            x, y, w, h = rect
            mask[y:y + h, x:x + w] = fake.GC_FGD
        fake.grabCut = _grabcut
        img = Image.new("RGB", (100, 80), (200, 30, 30))
        with mock.patch.dict(sys.modules, {"cv2": fake}):
            out, method, note = pe.remove_background(img)
        self.assertEqual(method, "grabcut")
        self.assertIn("GrabCut", note)
        # Centre kept, corner transparent.
        self.assertEqual(out.getpixel((50, 40))[3], 255)
        self.assertEqual(out.getpixel((2, 2))[3], 0)

    def test_neither_library_is_honest_none(self):
        img = Image.new("RGB", (40, 40), (10, 20, 30))
        with mock.patch.dict(sys.modules, {"rembg": None, "cv2": None}):
            # A None entry makes the import fail inside the helpers.
            out, method, note = pe.remove_background(img)
        self.assertEqual(method, "none")
        self.assertIn("hoy ni", note)

    def test_sheet_reports_method_plainly(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo = _test_photo(Path(tmp) / "photo.png")
            res = pe.make_a4_sheet(photo, out=str(Path(tmp) / "s.png"),
                                   bg_remove=True)
            self.assertTrue(res["ok"], res)
            # This VM has neither rembg nor cv2 — the honest answer.
            self.assertEqual(res["method"], "none")
            self.assertIn("hoy ni", res["method_note"])


class TestEdits(unittest.TestCase):
    def test_grayscale_rotate_border(self):
        img = Image.new("RGB", (100, 60), (200, 30, 30))
        g = pe.apply_edits(img, {"filter": "grayscale"})
        r, gg, b, _a = g.convert("RGBA").getpixel((5, 5))
        self.assertEqual(r, gg)
        self.assertEqual(r, b)
        rot = pe.apply_edits(img, {"rotate": 90})
        self.assertEqual(rot.size, (60, 100))
        bord = pe.apply_edits(img, {"border": 10, "border_color": "black"})
        self.assertEqual(bord.size, (120, 80))
        self.assertEqual(bord.convert("RGB").getpixel((2, 2)), (0, 0, 0))

    def test_brightness_and_filters_never_raise(self):
        img = Image.new("RGB", (20, 20), (100, 100, 100))
        for ops in ({"brightness": 1.5}, {"contrast": 0.5},
                    {"filter": "sepia"}, {"filter": "sharpen"},
                    {"filter": "blur"}, {"resize": [10, 10]},
                    {"crop": [0, 0, 10, 10]}, {"nonsense": True},
                    {"filter": "nonsense"}):
            out = pe.apply_edits(img, ops)
            self.assertIsNotNone(out)

    def test_edit_photo_saves_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo = _test_photo(Path(tmp) / "photo.png")
            res = pe.edit_photo(photo, {"filter": "sepia"},
                                out=str(Path(tmp) / "edited.png"))
            self.assertTrue(res["ok"], res)
            self.assertTrue(Path(res["path"]).is_file())


class TestParseCommand(unittest.TestCase):
    def test_variants(self):
        for text in ("ei photo-ta 6 copy A4 kore dao",
                     "ei chobi-ta 6 copy A4 kore dao",
                     "6 copy A4 sheet banao",
                     "photo-ta 6-copy A4 kore dao"):
            parsed = pe.parse_sheet_command(text)
            self.assertIsNotNone(parsed, text)
            self.assertEqual(parsed["copies"], 6)
            self.assertEqual(parsed["size_id"], "1.2x1.4")

    def test_size_in_command(self):
        parsed = pe.parse_sheet_command("ei photo-ta 6 copy 2x2 A4 kore dao")
        self.assertEqual(parsed["size_id"], "2x2")
        parsed = pe.parse_sheet_command("6 copy 35x45 A4 banao")
        self.assertEqual(parsed["size_id"], "35x45mm")

    def test_not_a_sheet_command(self):
        self.assertIsNone(pe.parse_sheet_command("weather kemon"))
        self.assertIsNone(pe.parse_sheet_command("photo-ta edit koro"))
        self.assertIsNone(pe.parse_sheet_command(""))


class TestPhoneRelay(unittest.TestCase):
    def test_json_request_builds_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo = _test_photo(Path(tmp) / "photo.png")
            out = str(Path(tmp) / "sheet.png")
            payload = json.dumps({"photo": str(photo), "top_text": "HELLO",
                                  "out": out})
            with mock.patch.object(pe, "make_a4_sheet_text",
                                   wraps=pe.make_a4_sheet_text) as _m:
                res = pe.handle_phone_request("PHOTO_EDIT::" + payload)
            self.assertIn("6-copy A4 sheet ready", res)
            self.assertIn("HELLO", res)
            self.assertTrue(Path(out).is_file())

    def test_plain_path_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo = _test_photo(Path(tmp) / "photo.png")
            with mock.patch.object(pe, "_out_path",
                                   return_value=Path(tmp) / "s.png"):
                res = pe.handle_phone_request(f"PHOTO_EDIT::{photo}")
            self.assertIn("6-copy A4 sheet ready", res)

    def test_missing_photo_is_honest(self):
        self.assertIn("pelam na", pe.handle_phone_request("PHOTO_EDIT::{}"))

    def test_edit_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo = _test_photo(Path(tmp) / "photo.png")
            payload = json.dumps({"photo": str(photo), "action": "edit",
                                  "ops": {"filter": "grayscale"},
                                  "out": str(Path(tmp) / "e.png")})
            res = pe.handle_phone_request("PHOTO_EDIT::" + payload)
            self.assertIn("Photo edit holo", res)


class TestCommanderDispatch(unittest.TestCase):
    def test_commander_photo_edit(self):
        store: dict = {}
        with mock.patch("memory.config_manager.get_plugin_config",
                        side_effect=lambda ns: dict(store.get(ns, {}))), \
             mock.patch("memory.config_manager.save_plugin_config",
                        side_effect=lambda ns, values: store.setdefault(
                            ns, {}).update(values)):
            from core import commander as _cmd
            with tempfile.TemporaryDirectory() as tmp:
                photo = _test_photo(Path(tmp) / "photo.png")
                with mock.patch.object(pe, "_out_path",
                                       return_value=Path(tmp) / "s.png"):
                    res = _cmd.issue_order(
                        str(photo), intent="photo_edit",
                        payload={"photo": str(photo), "top_text": "X"})
            self.assertTrue(res["ok"], res)
            self.assertIn("6-copy A4 sheet ready", res["result_text"])

    def test_relay_kind_photo_edit(self):
        from core import jarvis_link as jl
        store: dict = {}
        link = jl.JarvisLink.__new__(jl.JarvisLink)
        link.e2e_on = False
        link.log = lambda _t: None
        link.on_text = lambda _t: "on_text reply"
        link.sent = []
        link.send_result = lambda text: link.sent.append(text)
        with tempfile.TemporaryDirectory() as tmp:
            photo = _test_photo(Path(tmp) / "photo.png")
            payload = json.dumps({"photo": str(photo), "top_text": "HI"})
            with mock.patch("memory.config_manager.get_plugin_config",
                            side_effect=lambda ns: dict(store.get(ns, {}))), \
                 mock.patch("memory.config_manager.save_plugin_config",
                            side_effect=lambda ns, values: store.setdefault(
                                ns, {}).update(values)), \
                 mock.patch.object(pe, "_out_path",
                                   return_value=Path(tmp) / "s.png"):
                link._handle_message({"kind": "photo_edit", "text": payload})
        self.assertEqual(len(link.sent), 1)
        self.assertIn("6-copy A4 sheet ready", link.sent[0])


class TestPluginContract(unittest.TestCase):
    def test_plugin_never_raises(self):
        from plugins import photo_editor as plugin
        self.assertEqual(plugin.PLUGIN["name"], "photo_editor")
        self.assertEqual(plugin.PLUGIN_SETTINGS["widget"], "photo_editor")
        self.assertIn("path dao", plugin.run({}))
        with tempfile.TemporaryDirectory() as tmp:
            photo = _test_photo(Path(tmp) / "photo.png")
            with mock.patch.object(pe, "_out_path",
                                   return_value=Path(tmp) / "s.png"):
                out = plugin.run({"photo": str(photo),
                                  "top_text": "AMAR PHOTO"})
                self.assertIn("6-copy A4 sheet ready", out)
                self.assertIn("AMAR PHOTO", out)
                out = plugin.run({"photo": str(photo), "action": "edit",
                                  "ops": '{"filter": "grayscale"}'})
                self.assertIn("Photo edit holo", out)


if __name__ == "__main__":
    unittest.main()
