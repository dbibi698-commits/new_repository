"""core/photo_editor.py — 🖼️ PHOTO EDITOR, Photoshop-style (real PIL work).

What it does:
  * Edits — crop, resize, rotate, brightness/contrast, filters
    (grayscale, sepia, sharpen, blur), border/frame (colour + width).
  * Background remove (REAL): `rembg` first (pip install rembg +
    onnxruntime on demand; the u2net model ~170 MB downloads on first
    use — needs internet then; the UI says so honestly), OpenCV GrabCut
    fallback (opencv is already in requirements.txt), and an honest
    "none" when neither is available. The reply ALWAYS says plainly
    which method ran.
  * 6-COPY A4 SHEET (one shot): photo -> background remove -> border ->
    an A4 sheet at 300 DPI (2480x3508 px) with the user's text on the TOP
    line (centred, bold, a real font) and 6 copies in a grid below.
    Output is a print-ready PNG, saved + opened automatically. NO PDF
    output — ever (the user's standing no-PDF rule).
  * Voice/text command "ei photo-ta 6 copy A4 kore dao" (and variants)
    runs the whole pipeline in one go. The phone's photo_edit relay
    requests (photo + spec) are handled the same way.

EXACT SHEET SPEC (user, 2026-11-18):
    each copy = 1.2 inch x 1.4 inch at 300 DPI = 360 x 420 px (DEFAULT);
    A4 sheet = 300 DPI = 2480 x 3508 px. A size picker offers other
    sizes later (2x2 inch passport, 35x45 mm) — the default stays
    1.2x1.4 inch, 300 DPI.

PIL is in requirements.txt. rembg/cv2 are imported lazily and guarded —
importing this module never requires them. Every public function returns
a plain value and never raises.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DPI = 300
SHEET_W, SHEET_H = 2480, 3508  # A4 at 300 DPI

# size id -> label + size in inches (mm sizes are converted below).
PHOTO_SIZES = {
    "1.2x1.4": {"label": "1.2 x 1.4 inch (default)", "inches": (1.2, 1.4)},
    "2x2": {"label": "2 x 2 inch passport", "inches": (2.0, 2.0)},
    "35x45mm": {"label": "35 x 45 mm", "mm": (35, 45)},
}
DEFAULT_SIZE = "1.2x1.4"
DEFAULT_BORDER = 8
DEFAULT_BORDER_COLOR = "black"

_FONT_CANDIDATES = [
    # Windows (the real PC)
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\Arialbd.ttf",
    # Linux (this VM + Render)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def size_px(size_id: str = DEFAULT_SIZE) -> tuple[int, int]:
    """(width, height) in pixels at 300 DPI for a size id.
    1.2x1.4 inch -> exactly (360, 420). Never raises."""
    try:
        spec = PHOTO_SIZES.get(str(size_id or "").strip(), PHOTO_SIZES[DEFAULT_SIZE])
        if "inches" in spec:
            w_in, h_in = spec["inches"]
        else:
            w_mm, h_mm = spec["mm"]
            w_in, h_in = w_mm / 25.4, h_mm / 25.4
        return (round(w_in * DPI), round(h_in * DPI))
    except Exception:
        return (360, 420)


def sheet_grid(copy_w: int = 360, copy_h: int = 420, border: int = 8,
               cols: int = 3, rows: int = 2, top_band: int = 260,
               gap: int = 60) -> list[tuple[int, int, int, int]]:
    """[(x, y, w, h)] for each bordered copy on the A4 sheet — 6 rects,
    3 cols x 2 rows, centred below the top text band. Pure, never raises."""
    try:
        cell_w, cell_h = int(copy_w) + 2 * int(border), int(copy_h) + 2 * int(border)
        grid_w = cols * cell_w + (cols - 1) * gap
        grid_h = rows * cell_h + (rows - 1) * gap
        x0 = (SHEET_W - grid_w) // 2
        y0 = int(top_band) + (SHEET_H - int(top_band) - grid_h) // 2
        return [(x0 + c * (cell_w + gap), y0 + r * (cell_h + gap),
                 cell_w, cell_h)
                for r in range(rows) for c in range(cols)]
    except Exception:
        return []


def _bold_font(size: int):
    """A real bold TrueType font; falls back to PIL's default bitmap font."""
    try:
        from PIL import ImageFont
        for path in _FONT_CANDIDATES:
            try:
                if os.path.isfile(path):
                    return ImageFont.truetype(path, size)
            except Exception:
                continue
        try:
            return ImageFont.load_default(size=size)
        except Exception:
            return ImageFont.load_default()
    except Exception:
        return None


def _load_image(photo) -> "object | None":
    """Path / bytes / PIL Image -> PIL Image (RGB/RGBA) or None."""
    try:
        from PIL import Image
        if photo is None:
            return None
        if isinstance(photo, (str, os.PathLike)):
            p = Path(str(photo)).expanduser()
            if not p.is_file():
                return None
            return Image.open(p).convert("RGBA")
        if isinstance(photo, (bytes, bytearray)):
            import io
            return Image.open(io.BytesIO(bytes(photo))).convert("RGBA")
        if hasattr(photo, "convert"):  # already a PIL image
            return photo.convert("RGBA")
        return None
    except Exception:
        return None


# ── edits ────────────────────────────────────────────────────────────────────

def apply_edits(image, ops: dict | None = None):
    """Crop / resize / rotate / brightness / contrast / filters / border.
    Returns a new PIL image (or the input unchanged on bad ops). Never raises."""
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
        img = image
        if img is None:
            return None
        ops = ops or {}
        if isinstance(ops, str):
            try:
                ops = json.loads(ops)
            except Exception:
                ops = {}
        if not isinstance(ops, dict):
            return img
        crop = ops.get("crop")
        if isinstance(crop, (list, tuple)) and len(crop) == 4:
            try:
                img = img.crop(tuple(int(v) for v in crop))
            except Exception:
                pass
        resize = ops.get("resize")
        if isinstance(resize, (list, tuple)) and len(resize) == 2:
            try:
                img = img.resize((max(1, int(resize[0])), max(1, int(resize[1]))),
                                 Image.LANCZOS)
            except Exception:
                pass
        rotate = ops.get("rotate")
        if rotate:
            try:
                img = img.rotate(float(rotate), expand=True)
            except Exception:
                pass
        brightness = ops.get("brightness")
        if brightness:
            try:
                img = ImageEnhance.Brightness(img.convert("RGB")).enhance(
                    float(brightness)).convert("RGBA")
            except Exception:
                pass
        contrast = ops.get("contrast")
        if contrast:
            try:
                img = ImageEnhance.Contrast(img.convert("RGB")).enhance(
                    float(contrast)).convert("RGBA")
            except Exception:
                pass
        filt = str(ops.get("filter") or "").strip().lower()
        if filt == "grayscale":
            img = ImageOps.grayscale(img).convert("RGBA")
        elif filt == "sepia":
            g = ImageOps.grayscale(img)
            img = ImageOps.colorize(g, black="#3a2a18", white="#fff2d8").convert("RGBA")
        elif filt == "sharpen":
            img = img.filter(ImageFilter.SHARPEN)
        elif filt == "blur":
            img = img.filter(ImageFilter.GaussianBlur(3))
        border = ops.get("border")
        if border:
            try:
                w = int(border)
                color = str(ops.get("border_color") or "black")
                if w > 0:
                    img = ImageOps.expand(img, border=w, fill=color)
            except Exception:
                pass
        return img
    except Exception:
        return image


def edit_photo(photo, ops: dict | None = None, out: str = "") -> dict:
    """Edit one photo and save it (PNG). Returns a dict, never raises."""
    try:
        img = _load_image(photo)
        if img is None:
            return {"ok": False, "error": f"Photo-ta pelam na: {photo}"}
        out_img = apply_edits(img, ops)
        if out_img is None:
            return {"ok": False, "error": "Edit korte parlam na."}
        out_path = _out_path(out, "photo-edit")
        out_img.convert("RGBA").save(out_path, "PNG")
        return {"ok": True, "path": str(out_path),
                "size": out_img.size, "ops": ops or {}}
    except Exception as e:
        return {"ok": False, "error": f"Photo edit korte parlam na: {e}"}


# ── background remove ────────────────────────────────────────────────────────

def ensure_rembg() -> tuple[bool, str]:
    """Is rembg importable? If not, try ONE pip install (rembg +
    onnxruntime). Returns (ok, message). Never raises."""
    try:
        import rembg  # noqa: F401
        return True, "rembg already ache."
    except Exception:
        pass
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet",
             "rembg", "onnxruntime"],
            capture_output=True, text=True, timeout=600)
        try:
            import rembg  # noqa: F401
            return True, "rembg install holo."
        except Exception:
            tail = ((r.stderr or "") + (r.stdout or ""))[-200:]
            return False, f"rembg install holo na: {tail.strip() or 'pip fail'}"
    except Exception as e:
        return False, f"rembg install korte parlam na: {e}"


def _remove_bg_rembg(image):
    try:
        from rembg import remove
        out = remove(image)
        return out.convert("RGBA")
    except Exception:
        return None


def _remove_bg_grabcut(image):
    """OpenCV GrabCut fallback: centre rect = foreground. Returns an RGBA
    image with the background transparent, or None. Never raises."""
    try:
        import cv2
        import numpy as np
        img = image.convert("RGB")
        arr = np.array(img)
        h, w = arr.shape[:2]
        mask = np.zeros((h, w), np.uint8)
        bgd = np.zeros((1, 65), np.float64)
        fgd = np.zeros((1, 65), np.float64)
        rect = (max(1, w // 20), max(1, h // 20),
                max(1, w - 2 * (w // 20)), max(1, h - 2 * (h // 20)))
        cv2.grabCut(arr, mask, rect, bgd, fgd, 5,
                    cv2.GC_INIT_WITH_RECT)
        alpha = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD),
                         255, 0).astype("uint8")
        from PIL import Image
        out = img.convert("RGBA")
        out.putalpha(Image.fromarray(alpha))
        return out
    except Exception:
        return None


def remove_background(image, method: str = "auto",
                      install_rembg: bool = False) -> tuple[object, str, str]:
    """(image_rgba, method_used, note). method_used is one of
    "rembg" | "grabcut" | "none". Never raises."""
    try:
        img = image
        if img is None:
            return None, "none", "Photo-ta pelam na."
        want = str(method or "auto").strip().lower()
        if want in ("auto", "rembg"):
            if install_rembg:
                ok, _msg = ensure_rembg()
                if not ok:
                    pass
            out = _remove_bg_rembg(img)
            if out is not None:
                return out, "rembg", "Background remove holo — rembg diye."
            if want == "rembg":
                return img, "none", ("rembg chol lo na — background remove "
                                     "hoy ni, photo-ta as-is thakbe.")
        out = _remove_bg_grabcut(img)
        if out is not None:
            return out, "grabcut", ("Background remove holo — OpenCV GrabCut "
                                    "diye (rembg nei, tai fallback).")
        return img, "none", ("Background remove hoy ni — rembg-o nei, "
                             "OpenCV-o nei. Photo-ta as-is use hobe.")
    except Exception as e:
        return image, "none", f"Background remove korte parlam na: {e}"


# ── 6-copy A4 sheet ──────────────────────────────────────────────────────────

def _out_path(out: str, prefix: str) -> Path:
    if out:
        return Path(str(out)).expanduser()
    folder = Path.home() / "Pictures" / "MarkLVII"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except Exception:
        folder = Path(tempfile.gettempdir())
    return folder / f"{prefix}-{int(time.time())}.png"


def _fit_copy(img, copy_w: int, copy_h: int):
    """Crop-to-fill then resize to the EXACT copy size (360x420 default)."""
    try:
        from PIL import ImageOps
        return ImageOps.fit(img, (int(copy_w), int(copy_h)))
    except Exception:
        try:
            return img.resize((int(copy_w), int(copy_h)))
        except Exception:
            return img


def make_a4_sheet(photo, out: str = "", top_text: str = "",
                  size_id: str = DEFAULT_SIZE, border: int = DEFAULT_BORDER,
                  border_color: str = DEFAULT_BORDER_COLOR,
                  bg_remove: bool = True, method: str = "auto",
                  install_rembg: bool = False,
                  ops: dict | None = None) -> dict:
    """The one-shot pipeline. Returns a dict (never raises):
    {ok, path, copies, copy_px, sheet_px, size_id, method, top_text}."""
    try:
        from PIL import Image, ImageDraw, ImageOps
        img = _load_image(photo)
        if img is None:
            return {"ok": False, "error": f"Photo-ta pelam na: {photo}"}
        if ops:
            img = apply_edits(img, ops) or img
        method_used, bg_note = "none", ""
        if bg_remove:
            img, method_used, bg_note = remove_background(
                img, method=method, install_rembg=install_rembg)
        copy_w, copy_h = size_px(size_id)
        copy_img = _fit_copy(img.convert("RGBA"), copy_w, copy_h)
        bordered = ImageOps.expand(copy_img, border=int(border),
                                   fill=str(border_color or "black"))
        sheet = Image.new("RGBA", (SHEET_W, SHEET_H), (255, 255, 255, 255))
        draw = ImageDraw.Draw(sheet)
        text = str(top_text or "").strip()
        if text:
            font = _bold_font(110)
            if font is not None:
                try:
                    bbox = draw.textbbox((0, 0), text, font=font)
                    tw = bbox[2] - bbox[0]
                    draw.text(((SHEET_W - tw) // 2, 70), text,
                              fill=(20, 20, 20, 255), font=font)
                except Exception:
                    pass
        rects = sheet_grid(copy_w, copy_h, border=int(border))
        for (x, y, _w, _h) in rects:
            sheet.paste(bordered, (x, y), bordered)
        out_path = _out_path(out, "photo-sheet-6copy-a4")
        sheet.convert("RGB").save(out_path, "PNG", dpi=(DPI, DPI))
        return {"ok": True, "path": str(out_path), "copies": len(rects),
                "copy_px": (copy_w, copy_h), "sheet_px": (SHEET_W, SHEET_H),
                "size_id": size_id, "border": int(border),
                "border_color": str(border_color or "black"),
                "method": method_used, "method_note": bg_note,
                "top_text": text}
    except Exception as e:
        return {"ok": False, "error": f"A4 sheet banate parlam na: {e}"}


def make_a4_sheet_text(photo, out: str = "", top_text: str = "",
                       size_id: str = DEFAULT_SIZE,
                       border: int = DEFAULT_BORDER,
                       border_color: str = DEFAULT_BORDER_COLOR,
                       bg_remove: bool = True, method: str = "auto",
                       install_rembg: bool = False,
                       ops: dict | None = None,
                       open_after: bool = True) -> str:
    """Same pipeline, one plain-words string for chat / relay / cards."""
    try:
        res = make_a4_sheet(photo, out=out, top_text=top_text,
                            size_id=size_id, border=border,
                            border_color=border_color, bg_remove=bg_remove,
                            method=method, install_rembg=install_rembg,
                            ops=ops)
        if not res.get("ok"):
            return f"⚠️ {res.get('error', '')}"
        cw, ch = res["copy_px"]
        lines = [f"✅ 6-copy A4 sheet ready — proti copy {cw}x{ch} px "
                 f"({res['size_id']}, 300 DPI), sheet 2480x3508 px."]
        if res.get("top_text"):
            lines.append(f"📝 Uporer line: {res['top_text']!r}")
        lines.append(f"🖼️ Background remove: {res.get('method_note', '')}")
        lines.append(f"💾 Save holo: {res['path']}")
        lines.append("🖨️ PNG — print-ready (PDF noy).")
        if open_after:
            try:
                if os.name == "nt":
                    os.startfile(res["path"])  # noqa: S606
                elif sys.platform == "darwin":
                    subprocess.run(["open", res["path"]], timeout=10)
                else:
                    subprocess.run(["xdg-open", res["path"]], timeout=10,
                                   capture_output=True)
            except Exception:
                pass
        return "\n".join(lines)
    except Exception as e:
        return f"A4 sheet banate parlam na: {e}"


# ── voice/text command parsing ───────────────────────────────────────────────

_SHEET_RE = re.compile(
    r"(6\s*(ta\s*)?copy|6-copy|choy\s*copy|ছয়\s*কপি|6\s*কপি)", re.I)
_A4_RE = re.compile(r"\b(a4|এ4)\b", re.I)
_SIZE_RE = re.compile(r"(2\s*x\s*2|35\s*x\s*45|1\.2\s*x\s*1\.4)", re.I)


def parse_sheet_command(text: str) -> dict | None:
    """'ei photo-ta 6 copy A4 kore dao' (and variants) -> {copies, size_id}
    or None when it is not a sheet command. Never raises."""
    try:
        t = str(text or "")
        if not (_SHEET_RE.search(t) or ("copy" in t.lower() and _A4_RE.search(t))):
            return None
        size_id = DEFAULT_SIZE
        m = _SIZE_RE.search(t)
        if m:
            hit = re.sub(r"\s+", "", m.group(1)).lower()
            if hit.startswith("2x2"):
                size_id = "2x2"
            elif hit.startswith("35x45"):
                size_id = "35x45mm"
            elif hit.startswith("1.2x1.4"):
                size_id = "1.2x1.4"
        return {"copies": 6, "size_id": size_id, "a4": True}
    except Exception:
        return None


# ── phone relay ──────────────────────────────────────────────────────────────

def is_phone_request(text: str) -> bool:
    return str(text or "").strip().startswith("PHOTO_EDIT::")


def handle_phone_request(text: str, payload: dict | None = None) -> str:
    """PHOTO_EDIT::{json} or a photo path + payload {photo, top_text,
    size, ops, action}. Builds the 6-copy A4 sheet on this PC and returns
    the status + the saved PNG path (the phone fetches the file with a
    file-transfer request — the relay file channel caps at 2 MB and a
    300-DPI A4 PNG is bigger). Never raises."""
    try:
        raw = str(text or "").strip()
        if raw.startswith("PHOTO_EDIT::"):
            raw = raw[len("PHOTO_EDIT::"):]
        data: dict = {}
        if isinstance(payload, dict):
            data = dict(payload)
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    data.update(parsed)
                else:
                    data.setdefault("photo", raw)
            except Exception:
                data.setdefault("photo", raw)
        photo = data.get("photo") or data.get("path") or ""
        if not photo:
            return ("Photo-ta pelam na — age photo-ta pathao (file hisebe), "
                    "tarpor '6 copy A4 kore dao' bolo.")
        action = str(data.get("action") or "sheet").strip().lower()
        if action == "edit":
            res = edit_photo(photo, ops=data.get("ops") or {},
                             out=str(data.get("out") or ""))
            if not res.get("ok"):
                return f"⚠️ {res.get('error', '')}"
            return f"✅ Photo edit holo — save: {res['path']}"
        top_text = str(data.get("top_text") or data.get("text") or "")
        if not top_text and data.get("ask_text"):
            return "Uporer line-e ki likhbo — text-ta dao."
        return make_a4_sheet_text(
            photo, out=str(data.get("out") or ""), top_text=top_text,
            size_id=str(data.get("size") or data.get("size_id") or DEFAULT_SIZE),
            border=int(data.get("border", DEFAULT_BORDER)),
            border_color=str(data.get("border_color") or DEFAULT_BORDER_COLOR),
            bg_remove=bool(data.get("bg_remove", True)),
            method=str(data.get("method") or "auto"),
            install_rembg=bool(data.get("install_rembg", False)),
            ops=data.get("ops") or None, open_after=True)
    except Exception as e:
        return f"Phone-er photo edit korte parlam na: {e}"
