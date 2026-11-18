"""tests/test_mouse_video_edit.py — mouse-driven video editing + App Editor.

Stdlib only. No real editor app, no real mouse, no ffmpeg run — the mouse
and the screenshots are faked; ffmpeg/edit flows are tested through their
routing + failure paths, and the edit→upload chain through mocks.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import mouse_video_edit as mve  # noqa: E402


class FakeMouse:
    """mouse_fn callable: records (x, y) clicks / (text,) types / (key,)."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return True, "ok"


class ShotCycler:
    """shot_fn returning a different frame each call."""

    def __init__(self):
        self.n = 0

    def __call__(self):
        self.n += 1
        return f"frame-{self.n}"


class MouseVideoEditTest(unittest.TestCase):
    def setUp(self):
        fd, self.exe = tempfile.mkstemp(suffix=".exe")
        os.close(fd)
        fd, self.video = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)

    def tearDown(self):
        for p in (self.exe, self.video):
            try:
                os.unlink(p)
            except OSError:
                pass

    # ── editor detection ─────────────────────────────────────────────────
    def test_detect_editor_prefers_first_match(self):
        name, path = mve.detect_editor(
            [("CapCut", [self.exe]), ("Premiere Pro", [self.exe])])
        self.assertEqual(name, "CapCut")
        self.assertEqual(path, self.exe)

    def test_detect_editor_skips_missing(self):
        name, path = mve.detect_editor(
            [("CapCut", ["/tmp/no-such-editor.exe"]),
             ("Premiere Pro", [self.exe])])
        self.assertEqual(name, "Premiere Pro")

    def test_detect_editor_none_installed(self):
        name, path = mve.detect_editor(
            [("CapCut", ["/tmp/no-such-editor.exe"]),
             ("Premiere Pro", ["/tmp/no-such-editor-2.exe"])])
        self.assertEqual((name, path), ("", ""))

    def test_editor_status_text_none(self):
        with mock.patch.object(mve, "detect_editor", return_value=("", "")):
            text = mve.editor_status_text()
        self.assertIn("install nei", text)
        self.assertIn("ffmpeg", text)

    # ── routing: ffmpeg vs mouse ─────────────────────────────────────────
    def test_route_small_job_ffmpeg(self):
        for op in ("trim", "cut", "text", "thumbnail"):
            path, reason = mve.route_job([op])
            self.assertEqual(path, "ffmpeg", op)
            self.assertIn("ffmpeg", reason)

    def test_route_creative_job_mouse(self):
        path, _ = mve.route_job(["split", "text", "export"])
        self.assertEqual(path, "mouse")
        path, _ = mve.route_job(["transition"])
        self.assertEqual(path, "mouse")

    def test_route_empty_job(self):
        path, _ = mve.route_job([])
        self.assertEqual(path, "ffmpeg")

    # ── screen verification ──────────────────────────────────────────────
    def test_screen_changed(self):
        self.assertTrue(mve.screen_changed("abc", "def"))
        self.assertFalse(mve.screen_changed("abc", "abc"))
        self.assertFalse(mve.screen_changed("", "abc"))
        self.assertFalse(mve.screen_changed("abc", ""))

    def test_verified_steps_pass(self):
        mouse = FakeMouse()
        ok, msg = mve.run_verified_steps(
            [{"label": "Timeline click", "kind": "click", "x": 960, "y": 918},
             {"label": "Text likhlam", "kind": "type", "text": "hello"}],
            mouse_fn=mouse, shot_fn=ShotCycler())
        self.assertTrue(ok, msg)
        self.assertEqual(len(mouse.calls), 2)
        self.assertEqual(mouse.calls[0], (960, 918))
        self.assertEqual(mouse.calls[1], ("hello",))

    def test_verified_steps_stop_when_screen_unchanged(self):
        mouse = FakeMouse()
        ok, msg = mve.run_verified_steps(
            [{"label": "Timeline click", "kind": "click", "x": 960, "y": 918},
             {"label": "Text likhlam", "kind": "type", "text": "hello"}],
            mouse_fn=mouse, shot_fn=lambda: "same-frame")
        self.assertFalse(ok)
        self.assertIn("Timeline click", msg)
        self.assertIn("bodlalo na", msg)
        self.assertEqual(len(mouse.calls), 1)  # stopped after step 1

    def test_verified_steps_unknown_kind(self):
        ok, msg = mve.run_verified_steps(
            [{"label": "Weird", "kind": "teleport"}],
            mouse_fn=FakeMouse(), shot_fn=ShotCycler())
        self.assertFalse(ok)
        self.assertIn("unknown step kind", msg)

    def test_verified_steps_wait_needs_no_screen_change(self):
        ok, msg = mve.run_verified_steps(
            [{"label": "Ektu daralam", "kind": "wait", "wait_s": 0.01,
              "verify": "none"}],
            mouse_fn=FakeMouse(), shot_fn=lambda: "same-frame")
        self.assertTrue(ok, msg)

    # ── step lists ───────────────────────────────────────────────────────
    def test_mouse_edit_steps_capcut(self):
        steps = mve.mouse_edit_steps("CapCut", self.video,
                                     ["split", "text", "export"], "hello")
        kinds = [s["kind"] for s in steps]
        self.assertEqual(kinds[0], "wait")
        self.assertEqual(kinds[-1], "key")  # export confirm
        text_steps = [s for s in steps if s.get("text") == "hello"]
        self.assertTrue(text_steps)
        split = [s for s in steps if "split" in s["label"].lower()]
        self.assertTrue(split)
        timeline = [s for s in steps if s["kind"] == "click"
                    and s.get("x") == 960 and s.get("y") == 918]
        self.assertTrue(timeline)

    def test_mouse_edit_steps_unknown_editor_falls_back_to_capcut(self):
        steps = mve.mouse_edit_steps("NoSuchEditor", self.video, ["split"])
        self.assertTrue(any("split" in s["label"].lower() for s in steps))

    # ── ffmpeg path + chain ──────────────────────────────────────────────
    def test_ffmpeg_edit_missing_file(self):
        ok, msg = mve.ffmpeg_edit("/tmp/no-such-video.mp4", "trim")
        self.assertFalse(ok)
        self.assertIn("pelam na", msg)

    def test_ffmpeg_edit_unknown_op(self):
        ok, msg = mve.ffmpeg_edit(self.video, "rotate360")
        self.assertFalse(ok)
        self.assertIn("nei", msg)

    def test_edit_video_missing_file(self):
        ok, msg = mve.edit_video("/tmp/no-such-video.mp4", ["trim"])
        self.assertFalse(ok)
        self.assertIn("pelam na", msg)

    def test_edit_then_upload_chain(self):
        exported = os.path.join(tempfile.gettempdir(), "mve_chain_test.mp4")
        with open(exported, "wb") as f:
            f.write(b"fake")
        try:
            with mock.patch.object(
                    mve, "edit_video",
                    return_value=(True, f"✅ ffmpeg diye holo: {exported}")), \
                 mock.patch("core.video_upload.upload_video",
                            return_value=(True, "✅ YouTube-e upload holo")):
                ok, msg = mve.edit_then_upload(
                    self.video, ["trim"], "youtube", caption="test")
            self.assertTrue(ok, msg)
            self.assertIn("upload holo", msg)
        finally:
            try:
                os.unlink(exported)
            except OSError:
                pass

    def test_edit_then_upload_edit_fails(self):
        ok, msg = mve.edit_then_upload("/tmp/no-such-video.mp4", ["trim"],
                                       "youtube")
        self.assertFalse(ok)

    # ── App Editor ───────────────────────────────────────────────────────
    def test_find_app(self):
        self.assertEqual(mve.find_app(""), "")
        self.assertEqual(mve.find_app("definitely-not-an-app-xyz"), "")

    def test_app_editor_missing_app(self):
        ok, msg = mve.app_editor("definitely-not-an-app-xyz", [])
        self.assertFalse(ok)
        self.assertTrue(msg)

    def test_app_editor_bad_actions_fail_honestly(self):
        # An existing binary (python itself) opens, but the bogus step
        # must fail with the step named — never click blindly.
        python_exe = sys.executable
        with mock.patch.object(mve, "find_app", return_value=python_exe), \
             mock.patch.object(mve, "_launch_app",
                               return_value=(True, "khullam")):
            ok, msg = mve.app_editor(
                "python", [{"label": "Weird", "kind": "teleport"}],
                shot_fn=ShotCycler())
        self.assertFalse(ok)
        self.assertIn("Weird", msg)


if __name__ == "__main__":
    unittest.main()
