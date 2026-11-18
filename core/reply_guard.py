"""core/reply_guard.py — 🛡️ Reply-pipeline stall guard (thinking-hang fix).

THE BUG (found by auditing main.py, 2026-11-18):
------------------------------------------------
The user reports Mark goes into "thinking" and then NEVER answers — total
silence for 1-2 min (sometimes 5-10 min), then it just stops. The 15 s
stall watchdog from the agents round does NOT cover this case, because:

1. PRIMARY — tool-call stall disarms the watchdog. ``_receive_audio``
   calls ``self._clear_stall()`` on EVERY response frame, including the
   frame that carries a ``tool_call``. Then it does
   ``fr = await self._execute_tool(fc)`` with NO timeout. If the tool
   hangs (a long build, a browser flow, a network call without a
   timeout), ``_receive_audio`` blocks at that await forever. No new
   ``_rx_deadline`` is ever armed (arming only happens on SEND), so
   ``_watch_stall`` has nothing to watch — infinite THINKING silence.
   The tool eventually finishes/errors minutes later, which is exactly
   the "1-2 min, sometimes 5-10 min, then it stops" the user sees.

2. The fallback itself can hang silently. ``_speak_local`` speaks the
   fallback line through EdgeTTS, whose ``_synth`` streams with NO
   timeout — on a dead/slow network the speak blocks forever on its
   daemon thread and the user hears nothing even though the watchdog
   "fired".

3. The connect can hang. ``client.aio.live.connect(...)`` in
   ``_open_session`` has no timeout — a hung connect leaves the retry
   loop at THINKING forever with no session, no tasks, no watchdog.

4. The watchdog lives ON the event loop (an asyncio task). If the loop
   thread itself is blocked, the watchdog cannot fire at all.

THE FIX (this module + small main.py wiring):
--------------------------------------------
* ``TOOL_TIMEOUTS`` + ``tool_timeout(name)`` — hard per-tool budgets
  (default 120 s; long tools like builds 600 s). ``_receive_audio``
  awaits tools through ``asyncio.wait_for``; on timeout it sends a
  timeout FunctionResponse to the server so the conversation continues
  instead of hanging forever.
* The stall deadline is ALSO armed when a tool call starts, so the
  loop-bound watchdog covers tool hangs too.
* ``speak_with_timeout`` — the fallback line is spoken through a fresh
  TTS player in a thread joined with a hard timeout; if EdgeTTS does
  not finish in time it falls back to the local system TTS, and if
  that fails too it returns False (logged, never silent-by-accident).
* ``ReplyMonitor`` — a REAL daemon THREAD (not an asyncio task) that
  watches two things every 2 s: (a) a pending-reply/tool deadline —
  on expiry it speaks the fallback, shows "thinking too long" in the
  HUD live label and asks for a reconnect; (b) the event-loop
  heartbeat — if the loop stops beating for 30 s it speaks the
  fallback too, so the user is never left with silence even when the
  loop itself is blocked.
* ``_open_session``'s connect is wrapped in ``asyncio.wait_for(60)``.

Everything here is pure/testable: the monitor takes injectable
``now``/``speak``/``reconnect``/``show`` callbacks, and the tests fake
a hung tool, a stuck TTS player, a dead Live session and a blocked
loop. No Qt anywhere — runs on worker threads.
"""
from __future__ import annotations

import threading
import time

# ── tool timeouts ────────────────────────────────────────────────────────────
# Default budget for one tool call. Long tools (builds, deploys, video
# work) get a bigger budget — but they still get one: nothing may hang
# the reply pipeline forever.
DEFAULT_TOOL_TIMEOUT_S = 120.0
LONG_TOOL_TIMEOUT_S = 600.0
LONG_TOOLS = frozenset({
    "build_exe", "build_apk", "apk_build_selfheal", "software_builder",
    "render_deploy", "render_deploy_browser", "github_browser",
    "video_edit", "mouse_video_edit", "gradle_build", "automation",
    "agents_automation", "apk_build", "hosting_deploy",
})

# Stall: no output at all while a reply/tool is pending.
STALL_LIMIT_S = 15.0
# Event-loop heartbeat: no beat for this long means the loop is blocked.
LOOP_DEAD_S = 30.0
# Fallback TTS: give EdgeTTS this long, then try system TTS.
TTS_TIMEOUT_S = 20.0

STALL_LINE = "Net slow lagche — abar connect korchi…"
THINKING_TOO_LONG = ("⏳ Beshi somoy lagche… uttor asche na. "
                     "Cancel korte chaile 'stop' bolo.")
TOOL_TIMEOUT_LINE = ("Tool-ta beshi somoy nicche — timeout dilam, "
                     "abar bolle abar try korbo.")
TOOL_WORKING_LINE = "Tool-ta cholche — ektu somoy lagche, uttor aslei bolchi."


def tool_timeout(name: str) -> float:
    """Hard budget (seconds) for one call of tool ``name``."""
    return LONG_TOOL_TIMEOUT_S if (name or "") in LONG_TOOLS \
        else DEFAULT_TOOL_TIMEOUT_S


# ── stall detector (pure) ────────────────────────────────────────────────────

class StallDetector:
    """Deadline-based stall detection. Thread-safe; time injectable."""

    def __init__(self, limit_s: float = STALL_LIMIT_S,
                 now_fn=None):
        self.limit_s = float(limit_s)
        self._now = now_fn or time.monotonic
        self._deadline: float | None = None
        self._lock = threading.Lock()

    def arm(self) -> None:
        """A reply/tool is now pending — start the clock (once)."""
        with self._lock:
            if self._deadline is None:
                self._deadline = self._now() + self.limit_s

    def clear(self) -> None:
        with self._lock:
            self._deadline = None

    def pending(self) -> bool:
        with self._lock:
            return self._deadline is not None

    def stalled(self) -> bool:
        with self._lock:
            return (self._deadline is not None
                    and self._now() >= self._deadline)

    def overdue_s(self) -> float:
        with self._lock:
            if self._deadline is None:
                return 0.0
            return max(0.0, self._now() - self._deadline)


# ── TTS with a hard timeout ──────────────────────────────────────────────────

def speak_with_timeout(text: str, timeout_s: float = TTS_TIMEOUT_S,
                       speak_fn=None, fallback_fn=None) -> bool:
    """Speak ``text`` through ``speak_fn`` with a hard timeout.

    ``speak_fn(text)`` is the engine call (blocking). If it does not
    return within ``timeout_s``, ``fallback_fn(text)`` (system TTS) is
    tried once with the same timeout. Returns True when SOMETHING was
    spoken (or at least started), False when nothing could speak.
    Never raises, never blocks longer than ~2 * timeout_s.
    """
    text = (text or "").strip()
    if not text:
        return False
    if speak_fn is None:
        speak_fn = _default_speak
    if _run_with_timeout(speak_fn, text, timeout_s):
        return True
    if fallback_fn is not None and _run_with_timeout(fallback_fn, text,
                                                     timeout_s):
        return True
    return False


def _run_with_timeout(fn, arg, timeout_s: float) -> bool:
    """Run ``fn(arg)`` in a thread, join with timeout. True if it returned."""
    done = threading.Event()
    error: list = []

    def _work():
        try:
            fn(arg)
        except Exception as e:  # noqa: BLE001 - a stuck engine must not escape
            error.append(e)
        finally:
            done.set()

    t = threading.Thread(target=_work, daemon=True, name="reply-guard-tts")
    t.start()
    finished = done.wait(timeout=float(timeout_s))
    return bool(finished) and not error


def _default_speak(text: str) -> None:
    """The normal fallback path: a fresh EdgeTTS player, one utterance."""
    from core import tts as _tts
    player = _tts.create_tts_player({"tts_engine": "edgetts"})
    player.speak(text[:300])


def system_speak(text: str) -> None:
    """Local system TTS (no network) — the fallback when EdgeTTS stalls."""
    from core import tts as _tts
    try:
        player = _tts.create_tts_player({"tts_engine": "system"})
        player.speak(text[:300])
    except Exception:
        # Last resort: pyttsx3 directly, if the factory does not know it.
        import pyttsx3
        engine = pyttsx3.init()
        engine.say(text[:300])
        engine.runAndWait()


# ── thread-based reply monitor ───────────────────────────────────────────────

class ReplyMonitor:
    """Watches a pending reply/tool + the event-loop heartbeat from a REAL
    thread, so a blocked loop cannot silence it.

    Callbacks (all optional, all must never raise):
      * ``speak(text)`` — say the fallback line aloud (reply_guard's
        ``speak_with_timeout`` is the default).
      * ``show(text)`` — put the "thinking too long" line in the HUD.
      * ``reconnect(reason)`` — ask the run loop to rebuild the session.
      * ``log(text)`` — write one line to the activity log.
    ``arm()`` is called when a reply/tool becomes pending, ``clear()``
    when output arrives. ``heartbeat()`` is called by a loop task every
    couple of seconds. The monitor fires at most once per stall episode
    (``clear()`` re-arms it).
    """

    def __init__(self, stall_limit_s: float = STALL_LIMIT_S,
                 loop_dead_s: float = LOOP_DEAD_S,
                 speak=None, show=None, reconnect=None, log=None,
                 now_fn=None, check_interval_s: float = 2.0):
        self._detector = StallDetector(stall_limit_s, now_fn=now_fn)
        self._loop_dead_s = float(loop_dead_s)
        self._now = now_fn or time.monotonic
        self._speak = speak or (lambda t: speak_with_timeout(
            t, fallback_fn=system_speak))
        self._show = show or (lambda t: None)
        self._reconnect = reconnect or (lambda reason: None)
        self._log = log or (lambda t: None)
        self._check_interval_s = float(check_interval_s)
        self._last_heartbeat = self._now()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fired_stall = False
        self._fired_loop_dead = False

    # -- called from the event loop -----------------------------------------
    def arm(self) -> None:
        self._detector.arm()

    def clear(self) -> None:
        self._detector.clear()
        self._fired_stall = False
        self._fired_loop_dead = False

    def heartbeat(self) -> None:
        self._last_heartbeat = self._now()

    def pending(self) -> bool:
        return self._detector.pending()

    # -- the monitor thread ---------------------------------------------------
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="reply-monitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _fire_stall(self) -> None:
        """A pending reply produced no output for the whole limit."""
        self._fired_stall = True
        try:
            self._show(THINKING_TOO_LONG)
        except Exception:
            pass
        try:
            self._log("SYS: " + STALL_LINE)
        except Exception:
            pass
        try:
            self._speak(STALL_LINE)
        except Exception:
            pass
        try:
            self._reconnect("stall-no-output")
        except Exception:
            pass

    def _fire_loop_dead(self) -> None:
        """The event loop itself stopped beating — speak anyway."""
        self._fired_loop_dead = True
        try:
            self._show(THINKING_TOO_LONG)
        except Exception:
            pass
        try:
            self._log("SYS: Reply pipeline theme geche — abar chalu korchi.")
        except Exception:
            pass
        try:
            self._speak(STALL_LINE)
        except Exception:
            pass

    def check_once(self) -> str:
        """One check pass. Returns 'stall' | 'loop-dead' | 'ok' (testable)."""
        if self._detector.pending() and self._detector.stalled() \
                and not self._fired_stall:
            self._fire_stall()
            return "stall"
        if self._now() - self._last_heartbeat >= self._loop_dead_s \
                and not self._fired_loop_dead:
            self._fire_loop_dead()
            return "loop-dead"
        return "ok"

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception:
                pass
            self._stop.wait(timeout=self._check_interval_s)
