"""core/live_screen.py — 📱 Live Screen: the phone's screen, live on the
master screen.

Two modes, best first:
  * "stream" — the phone (JARVIS v1.9.7+) pushes live frames to the
    backend's frame-stream endpoint and this streamer pulls them down as
    fast as they arrive. A stream frame is a JPEG; the streamer hands each
    one to `on_frame(jpeg_bytes)` on its own thread — the HUD routes it to
    the Qt thread through a pyqtSignal (never touch a widget here).
  * "poll" / "stills" — no stream endpoint (older phone build, or the
    phone only sends on request): poll GET /api/phone/screen fast
    (~6 fps) and show a frame whenever the backend's `at` timestamp
    changes. When the timestamp stops changing, ask the phone for a fresh
    shot (link.fetch_phone_screen) and keep polling — that is the old
    periodic-stills behaviour, kept as the fallback so the viewer works
    regardless of the phone version.

Honest limit: a fast frame stream is NOT true video — it is JPEG frames
as fast as the phone can push them (adaptive 10–20 fps poll; the viewer
shows the real measured fps, never a claimed number). When the phone
only sends stills, the viewer says so plainly ("stills mode") instead
of pretending the picture is live.

ADAPTIVE FPS (agents round): the poll loop starts at 15 fps and adapts
between 10 and 20 fps — frames arriving fast speed the poll up, stale polls
slow it down. measured_fps is the real frame rate over the last 2 seconds
(frames the viewer actually showed, never a claimed number).

No Qt anywhere in this module. Never raises.
"""
from __future__ import annotations

import base64
import threading
import time

_POLL_INTERVAL = 1.0 / 15.0    # start at 15 fps, adapt 10–20 fps
_FPS_MIN, _FPS_MAX = 10.0, 20.0
_STALE_AFTER_S = 2.0            # no new frame for this long -> ask for a fresh shot
_STREAM_PATH = "/api/phone/screen-stream"


def adapt_interval(current: float, got_new: bool) -> float:
    """Next poll interval after one poll: a fresh frame speeds the poll
    up (toward 20 fps), a stale poll slows it down (toward 10 fps).
    Pure — the adaptive-fps rule, tested directly. Never raises."""
    try:
        cur = max(1.0 / _FPS_MAX, min(1.0 / _FPS_MIN, float(current or 0)))
        if got_new:
            return max(1.0 / _FPS_MAX, cur * 0.9)
        return min(1.0 / _FPS_MIN, cur * 1.15)
    except Exception:
        return 1.0 / 15.0


class LiveScreenStreamer:
    """Pull live phone-screen frames on a worker thread.

    `link` is the core.jarvis_link LINK object (or a test fake with the
    same `_get(path, timeout)` / `fetch_phone_screen()` / `paired` /
    `mark_id` / `pc_token` surface). `on_frame(jpeg_bytes)` and
    `on_status(text)` are called on the streamer thread — a UI listener
    must route through a pyqtSignal.
    """

    def __init__(self, link=None, fps: float = 15.0,
                 on_frame=None, on_status=None):
        self._link = link
        self._fps = max(1.0, min(float(fps or 15.0), 20.0))
        self._on_frame = on_frame
        self._on_status = on_status
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.mode = "off"          # off | stream | poll | stills
        self.frames = 0
        self._last_at = ""
        self._interval = 1.0 / self._fps
        self._frame_times: list[float] = []  # monotonic times of shown frames
        self._last_new_at = 0.0        # monotonic time of the last NEW frame

    @property
    def measured_fps(self) -> float:
        """Real frame rate over the last 2 seconds (0 when idle).
        Never raises."""
        try:
            now = time.monotonic()
            self._frame_times = [t for t in self._frame_times
                                 if now - t <= 2.0]
            return len(self._frame_times) / 2.0
        except Exception:
            return 0.0

    def _record_frame(self, now: float | None = None) -> None:
        """Note one shown frame (testable with a fake clock). Never raises."""
        try:
            self._frame_times.append(now if now is not None
                                     else time.monotonic())
            self._frame_times = self._frame_times[-40:]
        except Exception:
            pass

    # ── status ───────────────────────────────────────────────────────────────
    def _say(self, text: str) -> None:
        try:
            if callable(self._on_status):
                self._on_status(str(text))
        except Exception:
            pass

    def _emit(self, data: bytes) -> None:
        try:
            if callable(self._on_frame) and data:
                self._on_frame(bytes(data))
                self.frames += 1
                self._record_frame()
        except Exception:
            pass

    def _screen_path(self) -> str:
        try:
            link = self._link
            import urllib.parse as _up
            return ("/api/phone/screen?pc_id="
                    + _up.quote(str(getattr(link, "mark_id", "") or ""))
                    + "&token="
                    + _up.quote(str(getattr(link, "pc_token", "") or "")))
        except Exception:
            return ""

    def _get(self, path: str, timeout: float = 5.0):
        try:
            link = self._link
            if link is None:
                return None
            return link._get(path, timeout=timeout)
        except Exception:
            return None

    # ── control ──────────────────────────────────────────────────────────────
    def start(self) -> tuple[bool, str]:
        """Start streaming. Returns (ok, message). Never raises."""
        try:
            if self._thread is not None and self._thread.is_alive():
                return True, "Live screen already cholche."
            link = self._link
            if link is None or not getattr(link, "paired", False):
                return (False,
                        "📱 Phone pair kora nei — age jarvis_link_qr diye QR scan koro.")
            self._stop.clear()
            self.mode = "poll"
            self.frames = 0
            self._last_at = ""
            self._thread = threading.Thread(target=self._loop, daemon=True,
                                            name="live-screen-stream")
            self._thread.start()
            return True, "▶️ Live screen shuru holo — phone-er screen asche…"
        except Exception as e:
            return False, f"Live screen shuru korte parlam na: {e}"

    def stop(self) -> None:
        """Stop streaming. Never raises."""
        try:
            self._stop.set()
            self.mode = "off"
        except Exception:
            pass

    @property
    def running(self) -> bool:
        try:
            return self._thread is not None and self._thread.is_alive()
        except Exception:
            return False

    # ── the loop ─────────────────────────────────────────────────────────────
    def _loop(self) -> None:
        try:
            # 1. Stream endpoint — one probe. The phone v1.9.7+ pushes
            #    frames here; older builds answer nothing and we fall through.
            got = self._get(_STREAM_PATH + "?pc_id=" +
                            (self._link.mark_id if self._link else ""),
                            timeout=3.0)
            if isinstance(got, dict) and got.get("image"):
                self.mode = "stream"
                self._say("📱 Live stream mode — phone theke frame asche.")
                self._handle_frame(got)
            elif isinstance(got, (bytes, bytearray)) and got:
                self.mode = "stream"
                self._say("📱 Live stream mode — phone theke frame asche.")
                self._emit(bytes(got))
            else:
                self._say("Stream endpoint nei — rapid poll mode-e jachhi.")
            interval = 1.0 / self._fps
            self._interval = interval
            self._last_new_at = time.monotonic()
            while not self._stop.is_set():
                shot = self._get(self._screen_path(), timeout=5.0)
                got_new = False
                if isinstance(shot, dict) and shot.get("image"):
                    at = str(shot.get("at", "") or "")
                    if at and at != self._last_at:
                        self._last_at = at
                        self._last_new_at = time.monotonic()
                        got_new = True
                        if self.mode != "stream":
                            self.mode = "poll"
                        self._handle_frame(shot)
                    elif self.mode != "stream" and \
                            time.monotonic() - self._last_new_at >= _STALE_AFTER_S:
                        # Phone not pushing new frames — ask for a fresh
                        # shot, then keep polling (the old stills
                        # behaviour). Time-based, NOT poll-count-based, so
                        # the adaptive interval cannot delay the fallback.
                        if self.mode != "stills":
                            self.mode = "stills"
                            self._say("Stills mode — phone proti frame "
                                      "pathachhe na, 2 s-e notun shot chaichi.")
                        try:
                            self._link.fetch_phone_screen(timeout=15.0)
                        except Exception:
                            pass
                        self._last_new_at = time.monotonic()
                # Adaptive fps: fresh frames speed the poll up (toward
                # 20 fps), stale polls slow it down (toward 10 fps).
                self._interval = adapt_interval(self._interval, got_new)
                time.sleep(self._interval)
        except Exception as e:
            self._say(f"Live screen thamlo: {e}")
        finally:
            self.mode = "off"

    def _handle_frame(self, shot: dict) -> None:
        try:
            data = base64.b64decode(str(shot.get("image", "") or ""))
            self._emit(data)
        except Exception:
            pass


def live_status(link=None) -> str:
    """One-shot live-screen check: paired? latest frame? which mode?
    Used by the Live Screen agent card. Never raises."""
    try:
        if link is None:
            try:
                from core import jarvis_link as _jl
                link = _jl.LINK
            except Exception:
                link = None
        if link is None or not getattr(link, "paired", False):
            return ("📱 Phone pair kora nei — age jarvis_link_qr diye QR scan "
                    "koro, tarpor live screen dekha jabe.")
        shot = None
        try:
            import urllib.parse as _up
            shot = link._get(
                "/api/phone/screen?pc_id=" + _up.quote(str(link.mark_id or ""))
                + "&token=" + _up.quote(str(link.pc_token or "")), timeout=10)
        except Exception:
            shot = None
        if isinstance(shot, dict) and shot.get("image"):
            at = str(shot.get("at", "") or "")
            try:
                size = len(base64.b64decode(str(shot["image"])))
            except Exception:
                size = 0
            return (f"📱 Phone-er screen pelam"
                    + (f" (frame {at})" if at else "")
                    + (f" — {size // 1024} KB" if size else "")
                    + ". Live stream chalu korle master screen-e frame asbe "
                      "(adaptive 10–20 fps poll); nahole 4 s-e stills "
                      "refresh hobe.")
        return ("📱 Phone pair kora ache, kintu backend-e kono screen frame "
                "pelam na — phone-e Jarvis khola ache kina dekho, tarpor "
                "'Refresh phone screen' chapo.")
    except Exception as e:
        return f"Live screen-er status dekhte parlam na: {e}"
