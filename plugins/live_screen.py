"""plugins/live_screen.py — 📱 Live Screen: the phone's screen, live.

Starts the live-screen streamer (core/live_screen.py): the phone
(JARVIS v1.9.7+) pushes live frames to the backend and this PC pulls them
down as fast as they arrive (~5-10 fps) and shows them on the master
screen. When the phone only sends stills, the viewer says so plainly and
keeps the old 4-second stills refresh instead of pretending the picture
is live. The stream runs on a worker thread; the HUD shows frames through
a pyqtSignal. Stop with action=stop.
"""
from __future__ import annotations

PLUGIN = {
    "name": "live_screen",
    "description": (
        "Show the phone's LIVE screen on this PC's master screen: start the "
        "live-screen streamer (phone pushes frames, PC shows them as fast "
        "as they arrive). When the phone only sends stills, it says so "
        "plainly and keeps the 4-second stills refresh. Call when the user "
        "says: phone-er live screen dekhao, live screen chalu koro, phone "
        "screen live dekhao. Stop with action=stop. Needs the phone paired "
        "(Jarvis Link) and the phone's live stream (v1.9.7+)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING",
                       "description": "start (default) | stop | status."},
        },
        "required": [],
    },
}

_STREAMER = {"obj": None}


def _streamer():
    """The one shared streamer (created lazily). Never raises."""
    try:
        if _STREAMER["obj"] is None:
            from core import live_screen as _ls
            from core import jarvis_link as _jl
            _STREAMER["obj"] = _ls.LiveScreenStreamer(link=_jl.LINK)
        return _STREAMER["obj"]
    except Exception:
        return None


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Start/stop/status the live screen. Never raises."""
    try:
        params = parameters if isinstance(parameters, dict) else {}
        action = str(params.get("action") or "start").strip().lower()
        st = _streamer()
        if st is None:
            return "Live screen shuru korte parlam na — link module pelam na."
        if action == "stop":
            st.stop()
            return "⏹️ Live screen bondho korlam."
        if action == "status":
            return (f"Live screen: {'cholche' if st.running else 'bondho'} "
                    f"• mode: {st.mode} • frames: {st.frames}")
        ok, msg = st.start()
        return msg
    except Exception:
        return "Live screen korte parlam na — kichu ekta gondogol holo."
