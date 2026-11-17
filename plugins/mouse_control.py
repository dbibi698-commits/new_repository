"""plugins/mouse_control.py — move/click/type with the mouse like a human.

One tool, one `action` argument, so Gemini picks the verb and the plugin
dispatches to core/mouse_control.py (pyautogui). Runs on a worker thread —
never touches Qt (see AGENTS.md). Returns a short string, never raises.

Actions: move, click, double_click, right_click, type, scroll, screenshot,
position. Say "mouse_control" when the user asks Mark to move the mouse,
click something, type into the focused window, scroll, or take a screenshot —
NOT browser_control (that drives Chrome through the extension).
"""
from __future__ import annotations

PLUGIN = {
    "name": "mouse_control",
    "description": (
        "Move the mouse, click, double-click, right-click, type text, scroll, "
        "take a screenshot, or ask where the mouse is — like a human using "
        "the mouse. Call when the user asks: mouse-ta sorau / ekhane click "
        "koro / double-click koro / right-click koro / type koro / scroll "
        "koro / screenshot nao / mouse kothay. This drives the real desktop "
        "mouse (pyautogui), NOT the browser — browser clicks go through "
        "browser_control instead."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "What to do: move, click, double_click, "
                                      "right_click, type, scroll, screenshot, "
                                      "or position."},
            "x": {"type": "INTEGER",
                  "description": "Screen x coordinate (0 = left edge). "
                                 "Needed for move/click/double_click/right_click."},
            "y": {"type": "INTEGER",
                  "description": "Screen y coordinate (0 = top edge). "
                                 "Needed for move/click/double_click/right_click."},
            "text": {"type": "STRING",
                     "description": "Text to type (action=type), or the file "
                                    "path to save a screenshot to "
                                    "(action=screenshot, optional)."},
            "button": {"type": "STRING",
                       "description": "Mouse button for click: left (default), "
                                      "right, or middle."},
            "amount": {"type": "INTEGER",
                       "description": "Scroll amount for action=scroll: "
                                      "positive = up, negative = down (e.g. 3, -3)."},
        },
        "required": ["action"],
    },
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Dispatch `action` to core/mouse_control.py. Short string, never raises."""
    try:
        from core import mouse_control as _mc
    except Exception as e:
        return f"Mouse control load holo na: {e}"
    try:
        params = parameters or {}
        action = str(params.get("action") or "").strip().lower()
        x = params.get("x")
        y = params.get("y")
        text = params.get("text") or ""
        button = params.get("button") or "left"
        amount = params.get("amount")

        if action == "move":
            ok, msg = _mc.move(x, y)
        elif action == "click":
            ok, msg = _mc.click(x, y, button)
        elif action == "double_click":
            ok, msg = _mc.double_click(x, y)
        elif action == "right_click":
            ok, msg = _mc.right_click(x, y)
        elif action == "type":
            ok, msg = _mc.type_text(text)
        elif action == "scroll":
            ok, msg = _mc.scroll(amount)
        elif action == "screenshot":
            ok, msg = _mc.screenshot(text or None)
        elif action == "position":
            ok, msg = _mc.position()
        elif not action:
            ok, msg = False, ("Ki korbo — action dao: move, click, "
                              "double_click, right_click, type, scroll, "
                              "screenshot, ba position.")
        else:
            ok, msg = False, (f"'{action}' bujhlam na — action move, click, "
                              "double_click, right_click, type, scroll, "
                              "screenshot, ba position-er ekta hobe.")
    except Exception as e:
        ok, msg = False, f"Mouse control failed: {e}"
    if player:
        try:
            player.write_log(f"JARVIS: {msg}")
        except Exception:
            pass
    return msg
