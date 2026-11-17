"""tests/test_mouse_video.py — core/mouse_control.py, core/video_edit.py,
plugins/mouse_control.py, plugins/video_edit.py.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only. pyautogui and ffmpeg are BOTH mocked — no real mouse moves,
no real ffmpeg calls, no network. The one network check (gyan.dev URL
reachability) runs only when MARK_TEST_NETWORK=1, otherwise it skips.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── fake pyautogui (installed into sys.modules BEFORE core.mouse_control
# is imported, so its lazy import picks up the fake) ────────────────────────

class _FakeImage:
    size = (1920, 1080)

    def save(self, path):
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\nFAKE")


class _FakePyAutoGUI:
    FAILSAFE = False

    def __init__(self):
        self.calls = []

    def size(self):
        return (1920, 1080)

    def position(self):
        return (100, 200)

    def moveTo(self, x, y, duration=0):
        self.calls.append(("moveTo", x, y))

    def click(self, x, y, button="left"):
        self.calls.append(("click", x, y, button))

    def doubleClick(self, x, y):
        self.calls.append(("doubleClick", x, y))

    def rightClick(self, x, y):
        self.calls.append(("rightClick", x, y))

    def typewrite(self, text, interval=0):
        self.calls.append(("typewrite", text))

    def scroll(self, amount):
        self.calls.append(("scroll", amount))

    def screenshot(self):
        return _FakeImage()


_FAKE_PG = _FakePyAutoGUI()
sys.modules.setdefault("pyautogui", _FAKE_PG)

from core import mouse_control as mc  # noqa: E402
from core import video_edit as ve  # noqa: E402
from plugins import mouse_control as mouse_plugin  # noqa: E402
from plugins import video_edit as video_plugin  # noqa: E402


# ── mouse_control ────────────────────────────────────────────────────────────

class TestMouseControl(unittest.TestCase):
    def setUp(self):
        _FAKE_PG.calls.clear()
        mc._pyautogui = _FAKE_PG
        mc._pyautogui_failed = False

    def test_move_ok(self):
        ok, msg = mc.move(500, 300)
        self.assertTrue(ok, msg)
        self.assertEqual(_FAKE_PG.calls, [("moveTo", 500, 300)])

    def test_click_ok_and_button(self):
        ok, msg = mc.click(10, 20, "right")
        self.assertTrue(ok, msg)
        self.assertEqual(_FAKE_PG.calls, [("click", 10, 20, "right")])

    def test_double_and_right_click(self):
        self.assertTrue(mc.double_click(1, 1)[0])
        self.assertTrue(mc.right_click(2, 2)[0])
        self.assertEqual([c[0] for c in _FAKE_PG.calls],
                         ["doubleClick", "rightClick"])

    def test_out_of_bounds_refused(self):
        for x, y in [(1920, 100), (100, 1080), (-1, 5), (5, -10),
                     (99999, 99999)]:
            ok, msg = mc.move(x, y)
            self.assertFalse(ok, f"({x}, {y}) should be refused")
            self.assertIn("baire", msg)
            ok, msg = mc.click(x, y)
            self.assertFalse(ok)
            ok, msg = mc.double_click(x, y)
            self.assertFalse(ok)
            ok, msg = mc.right_click(x, y)
            self.assertFalse(ok)
        self.assertEqual(_FAKE_PG.calls, [])  # nothing ever moved

    def test_edge_coordinates_allowed(self):
        self.assertTrue(mc.move(0, 0)[0])
        self.assertTrue(mc.move(1919, 1079)[0])

    def test_non_numeric_coordinates_refused(self):
        ok, msg = mc.move("left", "top")
        self.assertFalse(ok)
        self.assertEqual(_FAKE_PG.calls, [])

    def test_bad_button_refused(self):
        ok, msg = mc.click(10, 10, "sideways")
        self.assertFalse(ok)
        self.assertIn("button", msg)

    def test_type_text(self):
        ok, msg = mc.type_text("hello jan")
        self.assertTrue(ok, msg)
        self.assertEqual(_FAKE_PG.calls, [("typewrite", "hello jan")])
        self.assertIn("hello jan", msg)

    def test_type_empty_refused(self):
        ok, msg = mc.type_text("")
        self.assertFalse(ok)
        self.assertEqual(_FAKE_PG.calls, [])

    def test_scroll(self):
        self.assertTrue(mc.scroll(3)[0])
        self.assertTrue(mc.scroll(-5)[0])
        self.assertEqual(_FAKE_PG.calls, [("scroll", 3), ("scroll", -5)])
        ok, msg = mc.scroll(0)
        self.assertFalse(ok)
        ok, msg = mc.scroll("up")
        self.assertFalse(ok)

    def test_position(self):
        ok, msg = mc.position()
        self.assertTrue(ok, msg)
        self.assertIn("(100, 200)", msg)

    def test_screenshot_saves_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "shot.png")
            ok, msg = mc.screenshot(path)
            self.assertTrue(ok, msg)
            self.assertTrue(os.path.isfile(path))
            self.assertIn(path, msg)
            self.assertIn("1920x1080", msg)

    def test_screenshot_default_path(self):
        ok, msg = mc.screenshot()
        self.assertTrue(ok, msg)
        self.assertIn("mark_screenshot_", msg)
        # Clean up the temp file the default path created.
        path = msg.split("Screenshot nilam: ", 1)[1].split(" (")[0]
        try:
            os.remove(path)
        except OSError:
            pass

    def test_missing_pyautogui_never_raises(self):
        mc._pyautogui = None
        mc._pyautogui_failed = True
        try:
            for fn in (lambda: mc.move(1, 1), lambda: mc.click(1, 1),
                       lambda: mc.type_text("x"), lambda: mc.scroll(1),
                       lambda: mc.screenshot(), lambda: mc.position()):
                ok, msg = fn()
                self.assertFalse(ok)
                self.assertIn("pyautogui", msg)
        finally:
            mc._pyautogui_failed = False
            mc._pyautogui = _FAKE_PG

    def test_pyautogui_error_never_raises(self):
        def boom(*a, **k):
            raise RuntimeError("mouse jammed")
        with mock.patch.object(_FAKE_PG, "moveTo", boom):
            ok, msg = mc.move(10, 10)
            self.assertFalse(ok)
            self.assertIn("jammed", msg)


class TestMousePlugin(unittest.TestCase):
    def setUp(self):
        _FAKE_PG.calls.clear()
        mc._pyautogui = _FAKE_PG
        mc._pyautogui_failed = False

    def test_dispatch_move_and_type(self):
        self.assertIn("✅", mouse_plugin.run({"action": "move", "x": 5, "y": 6}))
        self.assertIn("hello", mouse_plugin.run({"action": "type",
                                                 "text": "hello"}))

    def test_dispatch_out_of_bounds(self):
        res = mouse_plugin.run({"action": "click", "x": 5000, "y": 5})
        self.assertIn("baire", res)

    def test_unknown_and_missing_action_never_raise(self):
        self.assertIsInstance(mouse_plugin.run({"action": "teleport"}), str)
        self.assertIsInstance(mouse_plugin.run({}), str)
        self.assertIsInstance(mouse_plugin.run(None), str)

    def test_plugin_contract(self):
        self.assertEqual(mouse_plugin.PLUGIN["name"], "mouse_control")
        self.assertIn("action", mouse_plugin.PLUGIN["parameters"]["properties"])


# ── video_edit ───────────────────────────────────────────────────────────────

class _VideoBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.in1 = os.path.join(self.tmp.name, "a.mp4")
        self.in2 = os.path.join(self.tmp.name, "b.mp4")
        for p in (self.in1, self.in2):
            with open(p, "wb") as f:
                f.write(b"FAKEVIDEO" * 100)
        self.out = os.path.join(self.tmp.name, "out.mp4")
        self.runs = []  # captured ffmpeg argv lists

    def _fake_run(self, returncode=0, stdout="", stderr=""):
        def _run(argv, **kwargs):
            self.runs.append(list(argv))
            m = mock.Mock()
            m.returncode = returncode
            m.stdout = stdout
            m.stderr = stderr
            return m
        return _run

    def _patch_ffmpeg(self, run=None):
        # ffmpeg "found" on PATH and runs fine; subprocess.run is faked.
        p1 = mock.patch.object(ve.shutil, "which", return_value="/usr/bin/ffmpeg")
        p2 = mock.patch.object(ve, "_runs_ok", return_value=True)
        p3 = mock.patch.object(ve.subprocess, "run",
                               side_effect=run or self._fake_run())
        p1.start(); p2.start(); p3.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop); self.addCleanup(p3.stop)


class TestVideoOps(_VideoBase):
    def test_trim_argv(self):
        self._patch_ffmpeg()
        ok, msg = ve.trim(self.in1, 10, 20, self.out)
        self.assertTrue(ok, msg)
        self.assertEqual(len(self.runs), 1)
        argv = self.runs[0]
        self.assertEqual(argv[0], "/usr/bin/ffmpeg")
        self.assertIn("-ss", argv)
        self.assertEqual(argv[argv.index("-ss") + 1], "10.000")
        self.assertEqual(argv[argv.index("-to") + 1], "20.000")
        self.assertIn("-c", argv)
        self.assertEqual(argv[argv.index("-c") + 1], "copy")
        self.assertEqual(argv[-1], self.out)

    def test_trim_hhmmss_and_bad_range(self):
        self._patch_ffmpeg()
        ok, _ = ve.trim(self.in1, "00:01:00", "00:01:30", self.out)
        self.assertTrue(ok)
        self.assertEqual(self.runs[0][self.runs[0].index("-ss") + 1], "60.000")
        ok, msg = ve.trim(self.in1, 20, 10, self.out)
        self.assertFalse(ok)
        self.assertIn("pore", msg)

    def test_trim_missing_input(self):
        self._patch_ffmpeg()
        ok, msg = ve.trim(os.path.join(self.tmp.name, "nope.mp4"), 0, 5, self.out)
        self.assertFalse(ok)
        self.assertEqual(self.runs, [])  # ffmpeg never called

    def test_cut_argv_has_filter_complex(self):
        self._patch_ffmpeg()
        # probe() is called inside cut() — fake ffprobe as no-audio.
        with mock.patch.object(ve, "probe", return_value=(True, "10s, h264")):
            ok, msg = ve.cut(self.in1, [(0, 10), (20, 30)], self.out)
        self.assertTrue(ok, msg)
        argv = self.runs[0]
        self.assertIn("-filter_complex", argv)
        filt = argv[argv.index("-filter_complex") + 1]
        self.assertIn("trim=start=0.000:end=10.000", filt)
        self.assertIn("trim=start=20.000:end=30.000", filt)
        self.assertIn("concat=n=2:v=1:a=0", filt)

    def test_cut_empty_segments_refused(self):
        self._patch_ffmpeg()
        ok, msg = ve.cut(self.in1, [], self.out)
        self.assertFalse(ok)
        self.assertEqual(self.runs, [])

    def test_merge_argv_and_list_file(self):
        self._patch_ffmpeg()
        ok, msg = ve.merge([self.in1, self.in2], self.out)
        self.assertTrue(ok, msg)
        argv = self.runs[0]
        self.assertIn("-f", argv)
        self.assertEqual(argv[argv.index("-f") + 1], "concat")
        self.assertIn("-c", argv)
        # The temp concat list is cleaned up after the run.
        self.assertFalse(os.path.exists(
            os.path.join(tempfile.gettempdir(), "mark_merge_list.txt")))

    def test_merge_needs_two_files(self):
        self._patch_ffmpeg()
        ok, msg = ve.merge([self.in1], self.out)
        self.assertFalse(ok)
        self.assertEqual(self.runs, [])

    def test_add_text_argv(self):
        self._patch_ffmpeg()
        ok, msg = ve.add_text(self.in1, "Sheru bhai", self.out)
        self.assertTrue(ok, msg)
        argv = self.runs[0]
        self.assertIn("-vf", argv)
        filt = argv[argv.index("-vf") + 1]
        self.assertIn("drawtext", filt)
        self.assertIn("Sheru bhai", filt)

    def test_thumbnail_argv(self):
        self._patch_ffmpeg()
        out_png = os.path.join(self.tmp.name, "thumb.png")
        ok, msg = ve.thumbnail(self.in1, 5, out_png)
        self.assertTrue(ok, msg)
        argv = self.runs[0]
        self.assertIn("-vframes", argv)
        self.assertEqual(argv[argv.index("-vframes") + 1], "1")
        self.assertEqual(argv[-1], out_png)

    def test_ffmpeg_failure_returns_message_never_raises(self):
        self._patch_ffmpeg(run=self._fake_run(
            returncode=1, stderr="ffmpeg version x\n[error] boom happened"))
        ok, msg = ve.trim(self.in1, 0, 5, self.out)
        self.assertFalse(ok)
        self.assertIn("boom happened", msg)

    def test_probe_parses_ffprobe_json(self):
        fake_json = json.dumps({
            "format": {"duration": "42.500"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264",
                 "width": 1920, "height": 1080},
                {"codec_type": "audio", "codec_name": "aac"},
            ]})
        with mock.patch.object(ve, "_ffprobe_exe",
                               return_value="/usr/bin/ffprobe"):
            with mock.patch.object(ve.subprocess, "run") as fake:
                m = mock.Mock()
                m.returncode = 0
                m.stdout = fake_json
                fake.return_value = m
                ok, msg = ve.probe(self.in1)
        self.assertTrue(ok, msg)
        self.assertIn("42.500", msg)
        self.assertIn("1920x1080", msg)
        self.assertIn("h264", msg)
        self.assertIn("aac", msg)

    def test_probe_missing_file(self):
        ok, msg = ve.probe(os.path.join(self.tmp.name, "nope.mp4"))
        self.assertFalse(ok)


class TestEnsureFfmpeg(_VideoBase):
    def test_path_first(self):
        with mock.patch.object(ve.shutil, "which",
                               return_value="/usr/bin/ffmpeg") as which:
            with mock.patch.object(ve, "_runs_ok", return_value=True):
                ok, path = ve.ensure_ffmpeg()
        self.assertTrue(ok)
        self.assertEqual(path, "/usr/bin/ffmpeg")
        which.assert_called_with("ffmpeg")

    def test_bundled_folder_second(self):
        with mock.patch.object(ve.shutil, "which", return_value=None):
            with mock.patch.object(ve, "_mark_ffmpeg_exe",
                                   return_value="/fake/mark/ffmpeg/ffmpeg"):
                with mock.patch.object(os.path, "isfile", return_value=True):
                    with mock.patch.object(ve, "_runs_ok", return_value=True):
                        ok, path = ve.ensure_ffmpeg()
        self.assertTrue(ok)
        self.assertEqual(path, "/fake/mark/ffmpeg/ffmpeg")

    def test_nothing_found_on_linux_returns_message_no_download(self):
        # On this Linux VM ensure_ffmpeg must NOT try the Windows download.
        with mock.patch.object(ve.shutil, "which", return_value=None):
            with mock.patch.object(os.path, "isfile", return_value=False):
                ok, msg = ve.ensure_ffmpeg()
        self.assertFalse(ok)
        self.assertIsInstance(msg, str)
        self.assertTrue(len(msg) > 10)

    def test_ops_without_ffmpeg_never_raise(self):
        with mock.patch.object(ve, "ensure_ffmpeg",
                               return_value=(False, "ffmpeg pelam na")):
            for fn in (lambda: ve.trim(self.in1, 0, 5, self.out),
                       lambda: ve.cut(self.in1, [(0, 5)], self.out),
                       lambda: ve.merge([self.in1, self.in2], self.out),
                       lambda: ve.add_text(self.in1, "x", self.out),
                       lambda: ve.thumbnail(self.in1, 1, self.out)):
                ok, msg = fn()
                self.assertFalse(ok)
                self.assertIn("ffmpeg", msg)


class TestVideoPlugin(_VideoBase):
    def test_dispatch_probe_and_status(self):
        with mock.patch.object(ve, "probe", return_value=(True, "10s, h264")):
            res = video_plugin.run({"action": "probe", "input": self.in1})
        self.assertIn("h264", res)

    def test_dispatch_cut_bad_json_never_raises(self):
        res = video_plugin.run({"action": "cut", "input": self.in1,
                                "segments": "not json [[", "output": self.out})
        self.assertIsInstance(res, str)
        self.assertIn("JSON", res)

    def test_unknown_and_missing_action_never_raise(self):
        self.assertIsInstance(video_plugin.run({"action": "explode"}), str)
        self.assertIsInstance(video_plugin.run({}), str)
        self.assertIsInstance(video_plugin.run(None), str)

    def test_plugin_contract(self):
        self.assertEqual(video_plugin.PLUGIN["name"], "video_edit")
        props = video_plugin.PLUGIN["parameters"]["properties"]
        for key in ("action", "input", "output", "start", "end",
                    "segments", "text", "at"):
            self.assertIn(key, props)


class TestGyanUrlReachable(unittest.TestCase):
    """Live HEAD check — runs ONLY with MARK_TEST_NETWORK=1."""

    @unittest.skipUnless(os.environ.get("MARK_TEST_NETWORK") == "1",
                         "network check is opt-in (MARK_TEST_NETWORK=1)")
    def test_gyan_dev_head(self):
        import urllib.request
        req = urllib.request.Request(ve._FFMPEG_URL, method="HEAD",
                                     headers={"User-Agent": "Mark-LVII-test"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            self.assertIn(resp.status, (200, 301, 302, 303))


if __name__ == "__main__":
    unittest.main(verbosity=2)
