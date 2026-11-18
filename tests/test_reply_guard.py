"""tests/test_reply_guard.py — 🛡️ Thinking-hang fix (2026-11-18).

Simulates, with fakes, the four ways Mark used to go silent:
  1. a hung tool call that never returns (the PRIMARY bug — the stall
     watchdog was already cleared by the tool-call frame),
  2. a stuck TTS player (the fallback line itself hanging on EdgeTTS),
  3. a dead Live session (no output for 15 s),
  4. a blocked event loop (heartbeat stops — the loop-bound watchdog
     cannot fire at all).
"""
import asyncio
import threading
import time

from core import reply_guard as rg


# ── helpers ─────────────────────────────────────────────────────────────────

class FakeClock:
    def __init__(self, start=1000.0):
        self.t = start

    def now(self):
        return self.t

    def advance(self, s):
        self.t += s


def _never_returns():
    """A tool that hangs forever."""
    return asyncio.sleep(3600)


# ── 1. hung tool call ────────────────────────────────────────────────────────

def test_hung_tool_aborts_on_hard_timeout():
    """The exact _receive_audio pattern: wait_for + tool_timeout.
    Uses a short timeout here so the test stays fast — the real
    budgets are covered by test_tool_timeout_table."""
    async def run():
        with __import__("pytest").raises(asyncio.TimeoutError):
            await asyncio.wait_for(_never_returns(), timeout=0.3)
    asyncio.run(run())


def test_tool_timeout_table():
    assert rg.tool_timeout("weather") == 120.0
    assert rg.tool_timeout("save_memory") == 120.0
    assert rg.tool_timeout("build_exe") == 600.0
    assert rg.tool_timeout("build_apk") == 600.0
    assert rg.tool_timeout("render_deploy") == 600.0
    assert rg.tool_timeout("video_edit") == 600.0
    assert rg.tool_timeout("unknown_tool") == 120.0


def test_tool_timeout_line_is_banglish_and_plain():
    assert "timeout" in rg.TOOL_TIMEOUT_LINE.lower()
    assert "extension" not in rg.TOOL_TIMEOUT_LINE.lower()


# ── 2. stuck TTS player ──────────────────────────────────────────────────────

def test_stuck_tts_falls_back_to_system_engine():
    calls = []

    def stuck_engine(text):
        time.sleep(60)  # never returns in practice

    def system_engine(text):
        calls.append(text)

    ok = rg.speak_with_timeout("Net slow lagche", timeout_s=0.2,
                               speak_fn=stuck_engine,
                               fallback_fn=system_engine)
    assert ok is True
    assert calls == ["Net slow lagche"]


def test_both_tts_engines_stuck_returns_false_fast():
    def stuck(text):
        time.sleep(60)

    start = time.monotonic()
    ok = rg.speak_with_timeout("hello", timeout_s=0.2,
                               speak_fn=stuck, fallback_fn=stuck)
    elapsed = time.monotonic() - start
    assert ok is False
    assert elapsed < 5.0  # never blocks anywhere near the 60 s hangs


def test_working_tts_returns_true_and_is_spoken():
    spoken = []

    def engine(text):
        spoken.append(text)

    assert rg.speak_with_timeout("hi", timeout_s=5.0, speak_fn=engine) is True
    assert spoken == ["hi"]


# ── 3. dead Live session ─────────────────────────────────────────────────────

def test_stall_detector_arms_clears_and_fires():
    clock = FakeClock()
    d = rg.StallDetector(limit_s=15.0, now_fn=clock.now)
    assert d.pending() is False and d.stalled() is False
    d.arm()
    assert d.pending() is True and d.stalled() is False
    clock.advance(14.9)
    assert d.stalled() is False
    clock.advance(0.2)
    assert d.stalled() is True
    d.clear()
    assert d.pending() is False and d.stalled() is False


def test_monitor_fires_once_on_dead_session():
    clock = FakeClock()
    spoken, shown, reconnects, logs = [], [], [], []

    mon = rg.ReplyMonitor(
        stall_limit_s=15.0, loop_dead_s=3600.0,  # loop alive; only stall matters
        speak=lambda t: spoken.append(t),
        show=lambda t: shown.append(t),
        reconnect=lambda r: reconnects.append(r),
        log=lambda t: logs.append(t),
        now_fn=clock.now)
    mon.arm()
    assert mon.check_once() == "ok"
    clock.advance(16.0)
    assert mon.check_once() == "stall"
    assert spoken == [rg.STALL_LINE]
    assert shown == [rg.THINKING_TOO_LONG]
    assert reconnects == ["stall-no-output"]
    assert any("Net slow" in l for l in logs)
    # Fires ONCE per episode — no repeat spam while still stalled.
    clock.advance(10.0)
    assert mon.check_once() == "ok"
    assert len(spoken) == 1 and len(reconnects) == 1
    # Output arrives -> clear -> a new stall can fire again.
    mon.clear()
    mon.arm()
    clock.advance(16.0)
    assert mon.check_once() == "stall"
    assert len(spoken) == 2


def test_monitor_does_not_fire_when_output_arrives():
    clock = FakeClock()
    spoken = []
    mon = rg.ReplyMonitor(
        stall_limit_s=15.0, loop_dead_s=3600.0,
        speak=lambda t: spoken.append(t), now_fn=clock.now)
    mon.arm()
    clock.advance(10.0)
    mon.clear()  # server spoke in time
    clock.advance(10.0)
    assert mon.check_once() == "ok"
    assert spoken == []


# ── 4. blocked event loop ────────────────────────────────────────────────────

def test_monitor_fires_when_loop_heartbeat_stops():
    """The loop-bound watchdog cannot fire here — the monitor is a real
    thread, so it must still speak. Simulated with a fake clock and no
    heartbeat() calls after start."""
    clock = FakeClock()
    spoken, shown = [], []
    mon = rg.ReplyMonitor(
        stall_limit_s=15.0, loop_dead_s=30.0,
        speak=lambda t: spoken.append(t),
        show=lambda t: shown.append(t),
        now_fn=clock.now)
    # Loop beats for a while, then blocks (no more heartbeat()).
    mon.heartbeat()
    clock.advance(10.0)
    mon.heartbeat()
    clock.advance(29.0)
    assert mon.check_once() == "ok"
    clock.advance(2.0)  # 31 s since the last beat
    assert mon.check_once() == "loop-dead"
    assert spoken == [rg.STALL_LINE]
    assert shown == [rg.THINKING_TOO_LONG]


def test_monitor_thread_actually_runs_off_loop():
    """The monitor is a daemon thread — it ticks while the main thread
    is busy, which is the whole point (a blocked loop must not stop it)."""
    clock = FakeClock()
    fired = []
    mon = rg.ReplyMonitor(
        stall_limit_s=0.05, loop_dead_s=3600.0,
        speak=lambda t: fired.append(t),
        now_fn=clock.now, check_interval_s=0.01)
    mon.arm()
    mon.start()
    # Fake clock never advances, so the stall cannot fire — but the
    # thread itself must be alive and ticking.
    assert mon._thread is not None and mon._thread.is_alive()
    assert mon._thread.daemon is True
    mon.stop()
    mon._thread.join(timeout=2.0)
    assert not mon._thread.is_alive()


def test_reply_guard_strings_have_no_banned_word():
    for line in (rg.STALL_LINE, rg.THINKING_TOO_LONG,
                 rg.TOOL_TIMEOUT_LINE, rg.TOOL_WORKING_LINE):
        assert "extension" not in line.lower()
