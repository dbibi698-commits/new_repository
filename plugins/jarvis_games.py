"""plugins/jarvis_games.py — 🎮 GAMES & PLAY: play a game on the phone or PC.

Phone: the game opens by DISPLAY NAME through the relay — the phone Jarvis
has its own open_app tool that resolves names (PUBG, Free Fire, WhatsApp...)
with no package name needed, so this PC never needs one either.
PC: a small Steam-ID map + steam:// URIs / .exe paths, best-effort.
Never raises; a game it cannot launch says exactly what to set instead.
"""
from __future__ import annotations

import os
import platform
import subprocess

PLUGIN = {
    "name": "play_game",
    "description": (
        "Play a game on the phone or the PC. Call when the user says: game "
        "khelo, PUBG kholo, Free Fire chalao, PC-te Dota khelo. Phone: the "
        "game opens by NAME on the phone (no package name needed). PC: Steam "
        "games launch by their Steam id, or a steam:// URI / .exe path. "
        "Device defaults to the one in Plugin Settings > GAMES & PLAY."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING", "description": "Game name, e.g. PUBG Mobile, Free Fire, Dota 2. Empty = the saved default game for the device."},
            "device": {"type": "STRING", "description": "phone or pc (optional — the saved default is used if empty)."},
        },
        "required": [],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "jarvis_games",
    "title": "🎮 GAMES & PLAY",
    "fields": [
        {"key": "default_device", "type": "choice",
         "label": "Default device", "options": ["phone", "pc"], "default": "phone"},
        {"key": "phone_game", "type": "text",
         "label": "Phone default game", "default": "PUBG Mobile"},
        {"key": "pc_game", "type": "text",
         "label": "PC default game (steam URI / exe path)",
         "placeholder": "e.g. steam://run/570"},
    ],
}

# Steam app ids for the games the user is likeliest to name. Anything else
# needs a steam://run/<id> URI or an .exe path in the pc_game setting.
_STEAM_IDS = {
    "dota 2": 570, "dota": 570,
    "counter-strike 2": 730, "cs2": 730, "cs:go": 730, "counter strike 2": 730,
    "pubg": 578080, "pubg battlegrounds": 578080,
    "apex legends": 1172470, "apex": 1172470,
    "gta v": 271590, "gta 5": 271590, "grand theft auto v": 271590,
    "team fortress 2": 440, "tf2": 440,
    "rocket league": 252950,
    "elden ring": 1245620,
}


def _settings() -> dict:
    try:
        from memory.config_manager import get_plugin_config
        return get_plugin_config("jarvis_games")
    except Exception:
        return {}


def _launch(uri_or_path: str) -> str:
    """Open a steam:// URI or an .exe/.lnk path. Returns a spoken string."""
    target = uri_or_path.strip()
    try:
        if platform.system() == "Windows":
            os.startfile(target)  # noqa: S606 - user-chosen game / URI
        else:
            import webbrowser
            webbrowser.open(target)
        return f"🎮 PC-te khule dilam: {target}"
    except Exception as e:
        return f"PC-te '{target}' khulte parlam na: {e}"


def _play_on_pc(name: str) -> str:
    low = name.strip().lower()
    if low.startswith("steam://"):
        return _launch(name.strip())
    if low in _STEAM_IDS:
        return _launch(f"steam://run/{_STEAM_IDS[low]}")
    if low.endswith((".exe", ".lnk")) and os.path.isfile(os.path.expanduser(name.strip())):
        return _launch(os.path.expanduser(name.strip()))
    return (f"PC-te '{name}'-er launch command jani na — Plugin Settings > "
            "🎮 GAMES & PLAY-e pc_game-e steam://run/<id> ba .exe path dao, "
            "ba Steam-er game-er nam bolo (Dota 2, CS2, PUBG, Apex, GTA V).")


def run(parameters: dict, player=None, session_memory=None) -> str:
    cfg = _settings()
    device = (parameters.get("device") or "").strip().lower()
    if device not in ("phone", "pc"):
        device = str(cfg.get("default_device") or "phone").lower()
        if device not in ("phone", "pc"):
            device = "phone"
    name = (parameters.get("name") or "").strip()
    if not name:
        name = str(cfg.get("phone_game" if device == "phone" else "pc_game") or "").strip()
    if not name:
        return "Kon game khelbe — nam-ta bolo."
    if device == "pc":
        return _play_on_pc(name)
    # Phone: open by display name — the phone Jarvis resolves it, no package name needed.
    try:
        from core.jarvis_link import LINK
    except Exception:
        return "Jarvis Link chalu hoy ni — restart koro."
    if LINK is None or not LINK.paired:
        return ("Phone pair kora nei — phone-e Jarvis khule Settings > PC Pairing > "
                "Scan PC QR diye Mark-er QR scan koro, tarpor abar bolo.")
    try:
        reply = LINK.send_and_wait_result(f"Phone-e '{name}' game-ta kholo.", timeout=90.0)
    except Exception as e:
        return f"Phone-e pathate parlam na: {e}"
    if not reply:
        return (f"Phone-e '{name}' khulte bollam, kintu 90 second-e kono uttor "
                "elo na — phone-er Jarvis khola ache kina dekho.")
    return reply[:500]
