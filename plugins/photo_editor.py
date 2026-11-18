"""plugins/photo_editor.py — 🖼️ PHOTO EDITOR: Photoshop-style, real PIL work.

Crop, resize, rotate, brightness/contrast, filters (grayscale, sepia,
sharpen, blur), border/frame — plus REAL background remove (rembg first,
OpenCV GrabCut fallback — the reply always says which method ran) and
the one-shot 6-copy A4 sheet: 6 copies of 360x420 px (1.2x1.4 inch at
300 DPI, the default size) on a 2480x3508 px A4 sheet, the user's text
on the top line, print-ready PNG (never a PDF).

The Plugin Settings overlay builds the "Photo Editor" box for this
plugin (widget "photo_editor"): photo picker + size picker + top-line
text + "6-copy A4 sheet banao" button.

Runs on a worker thread (callers run plugin.run off the Qt thread).
Returns a short string, never raises.
"""
from __future__ import annotations

PLUGIN = {
    "name": "photo_editor",
    "description": (
        "Edit photos for real — crop, resize, rotate, brightness/contrast, "
        "filters (grayscale, sepia, sharpen, blur), border/frame, background "
        "remove (rembg first, OpenCV GrabCut fallback), and the one-shot "
        "6-copy A4 sheet: 6 copies of 360x420 px (1.2x1.4 inch, 300 DPI) "
        "on a 2480x3508 px A4 sheet with your text on the top line, "
        "print-ready PNG. Call when the user asks: photo edit koro, "
        "background remove koro, 'ei photo-ta 6 copy A4 kore dao', "
        "passport photo sheet banao."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "photo": {"type": "STRING",
                      "description": "Photo file path on this PC."},
            "action": {"type": "STRING",
                       "description": "'sheet' (default: 6-copy A4) or 'edit' (single-photo edits)."},
            "top_text": {"type": "STRING",
                         "description": "Text for the top line of the A4 sheet."},
            "size": {"type": "STRING",
                     "description": "Copy size: '1.2x1.4' (default), '2x2', '35x45mm'."},
            "border": {"type": "NUMBER",
                       "description": "Border width in px around each copy (default 8)."},
            "border_color": {"type": "STRING",
                             "description": "Border colour (default black)."},
            "bg_remove": {"type": "BOOLEAN",
                          "description": "True = remove the background first (default)."},
            "ops": {"type": "STRING",
                    "description": "JSON edit ops for 'edit' action, e.g. "
                                   "{\"filter\": \"sepia\", \"rotate\": 90}."},
        },
        "required": ["photo"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "photo_editor",
    "title": "🖼️ PHOTO EDITOR — 6-copy A4 sheet + Photoshop-style edit",
    "widget": "photo_editor",
    "fields": [],
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Edit a photo or build the 6-copy A4 sheet. Short string, never raises."""
    try:
        params = parameters or {}
        photo = str(params.get("photo") or "").strip()
        if not photo:
            return "Photo-r path dao — kon photo edit korbo?"
        from core import photo_editor as _pe
        action = str(params.get("action") or "sheet").strip().lower()
        if action == "edit":
            import json as _json
            ops = params.get("ops") or {}
            if isinstance(ops, str):
                try:
                    ops = _json.loads(ops)
                except Exception:
                    ops = {}
            res = _pe.edit_photo(photo, ops=ops if isinstance(ops, dict) else {})
            if not res.get("ok"):
                return f"⚠️ {res.get('error', '')}"
            return f"✅ Photo edit holo — save: {res['path']}"
        # Sheet (default) — also handles the one-shot voice command.
        top_text = str(params.get("top_text") or "")
        if not top_text:
            parsed = _pe.parse_sheet_command(str(params.get("command") or ""))
            if parsed is not None:
                top_text = str(params.get("top_text") or "")
        return _pe.make_a4_sheet_text(
            photo, top_text=top_text,
            size_id=str(params.get("size") or _pe.DEFAULT_SIZE),
            border=int(params.get("border", _pe.DEFAULT_BORDER)),
            border_color=str(params.get("border_color") or _pe.DEFAULT_BORDER_COLOR),
            bg_remove=bool(params.get("bg_remove", True)))
    except Exception as e:
        return f"Photo edit korte parlam na: {e}"
