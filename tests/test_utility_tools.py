"""tests/test_utility_tools.py — 🧰 50 UTILITY TOOLS: every function in
core/utility_tools.py does its real job (or says plainly why it cannot).
Network, ffmpeg, yt-dlp, clipboard and the phone relay are mocked;
filesystem work uses tmp dirs; config is monkeypatched.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import utility_tools as u  # noqa: E402

try:
    import cryptography  # noqa: F401
    _HAS_CRYPTO = True
except Exception:
    _HAS_CRYPTO = False


def _cfg_mock(store):
    return (
        mock.patch("memory.config_manager.get_plugin_config",
                   lambda ns: dict(store.get(ns) or {})),
        mock.patch("memory.config_manager.save_plugin_config",
                   lambda ns, v: store.__setitem__(ns, dict(v))),
    )


class TestTime(unittest.TestCase):
    def test_timer_status_empty(self):
        # Timers live in the module-level _TIMERS dict (in-memory), so
        # clear it first — another test's timer would otherwise show up.
        with u._TIMERS_LOCK:
            u._TIMERS.clear()
        store = {}
        p1, p2 = _cfg_mock(store)
        with p1, p2:
            self.assertIn("Kono timer", u.timer_status())

    def test_timer_start_and_status(self):
        store = {}
        p1, p2 = _cfg_mock(store)
        with p1, p2:
            out = u.start_timer(60, label="TestTimer")
            self.assertIn("Timer cholche", out)
            self.assertIn("TestTimer", u.timer_status())

    def test_stopwatch_flow(self):
        store = {}
        p1, p2 = _cfg_mock(store)
        with p1, p2:
            self.assertIn("chalu", u.stopwatch("start"))
            self.assertIn("cholche", u.stopwatch("status"))
            self.assertIn("Lap 1", u.stopwatch("lap"))
            self.assertIn("thamlo", u.stopwatch("stop"))

    def test_pomodoro_flow(self):
        store = {}
        p1, p2 = _cfg_mock(store)
        with p1, p2:
            self.assertIn("25 min", u.pomodoro("start"))
            self.assertIn("work-e", u.pomodoro("status"))
            self.assertIn("break", u.pomodoro("break"))
            self.assertIn("thamlo", u.pomodoro("stop"))

    def test_world_clock(self):
        out = u.world_clock("kolkata, london")
        self.assertIn("Kolkata", out)
        self.assertIn("London", out)

    def test_sleep_timer_status(self):
        self.assertIn("bondho", u.sleep_timer_status())
        out = u.sleep_timer(30)
        self.assertIn("Sleep timer", out)
        self.assertIn("cholche", u.sleep_timer_status())
        self.assertIn("cancel", u.sleep_timer(0, cancel=True))

    def test_focus_mode_off(self):
        self.assertIn("OFF", u.focus_mode(False))


class TestConvert(unittest.TestCase):
    def test_unit_length(self):
        self.assertIn("1.609", u.unit_convert(1, "mile", "km"))
        self.assertIn("= 1000", u.unit_convert(1, "km", "m"))

    def test_unit_temp(self):
        self.assertIn("32", u.unit_convert(0, "C", "F"))
        self.assertIn("100", u.unit_convert(212, "F", "C"))

    def test_unit_unknown(self):
        self.assertIn("bujhlam na", u.unit_convert(1, "parsec", "m"))

    def test_currency_same(self):
        self.assertIn("= 5", u.currency_convert(5, "USD", "USD"))

    def test_currency_offline_honest(self):
        u._CURRENCY_CACHE["rates"] = {}
        u._CURRENCY_CACHE["at"] = 0.0
        with mock.patch("urllib.request.urlopen",
                        side_effect=Exception("no net")):
            self.assertIn("internet lagbe", u.currency_convert(1, "USD", "INR"))

    def test_currency_cached_rate(self):
        u._CURRENCY_CACHE["rates"] = {"USD": 1.0, "INR": 83.0}
        u._CURRENCY_CACHE["at"] = 9999999999.0
        out = u.currency_convert(2, "USD", "INR")
        self.assertIn("166", out)
        u._CURRENCY_CACHE["rates"] = {}
        u._CURRENCY_CACHE["at"] = 0.0

    def test_code_format_python(self):
        out = u.code_format("x=1", "python")
        self.assertIn("x = 1", out)

    def test_code_format_json(self):
        out = u.code_format('{"a": 1}', "json")
        self.assertIn('"a": 1', out)

    def test_json_view_ok_and_bad(self):
        self.assertIn("thik ache", u.json_view('{"a": [1, 2]}'))
        self.assertIn("thik noy", u.json_view('{bad'))

    def test_regex(self):
        out = u.regex_test(r"\d+", "abc 123 def 45")
        self.assertIn("2 ta", out)
        self.assertIn("123", out)
        self.assertIn("vul", u.regex_test(r"[", "x"))


class TestFiles(unittest.TestCase):
    def test_file_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "my-report.txt").write_text("x")
            (Path(tmp) / "other.log").write_text("x")
            out = u.file_search("report", tmp)
            self.assertIn("my-report.txt", out)
            self.assertNotIn("other.log", out)
            self.assertIn("pelam na", u.file_search("zzz-nope", tmp))

    def test_zip_create_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "folder"
            src.mkdir()
            (src / "a.txt").write_text("hello")
            out = u.zip_tool("create", str(src))
            self.assertIn("Zip banalam", out)
            zpath = Path(tmp) / "folder.zip"
            self.assertTrue(zpath.is_file())
            out2 = u.zip_tool("extract", str(zpath),
                              str(Path(tmp) / "out"))
            self.assertIn("Zip khullam", out2)
            self.assertTrue((Path(tmp) / "out" / "a.txt").is_file())

    def test_storage_analyzer(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "big").mkdir()
            (Path(tmp) / "big" / "f.bin").write_bytes(b"x" * 1000)
            out = u.storage_analyzer(tmp)
            self.assertIn("Storage", out)
            self.assertIn("big", out)

    def test_disk_cleanup_dry_run(self):
        out = u.disk_cleanup(dry_run=True)
        self.assertIn("Disk Cleanup", out)
        self.assertIn("preview", out)

    def test_download_file_mocked(self):
        class Resp:
            headers = {"Content-Length": "5"}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                return b"hello"

        with mock.patch("urllib.request.urlopen", return_value=Resp()), \
                mock.patch.object(u, "_downloads",
                                  return_value=Path(tempfile.gettempdir()) / "mark-dl-test"):
            out = u.download_file("https://example.com/f.txt", "f.txt")
            self.assertIn("Download holo", out)

    def test_image_resize(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "pic.png"
            Image.new("RGB", (100, 50), (10, 20, 30)).save(src)
            out = u.image_resize(str(src), 50)
            self.assertIn("50x25", out)
            self.assertTrue((Path(tmp) / "pic-50x25.png").is_file())

    def test_clipboard_mocked(self):
        fake = mock.Mock()
        fake.copy = mock.Mock()
        fake.paste = mock.Mock(return_value="hi")
        with mock.patch.dict(sys.modules, {"pyperclip": fake}):
            self.assertIn("bosalam", u.clipboard("set", "hi"))
            fake.copy.assert_called_once_with("hi")
            self.assertIn("hi", u.clipboard("get"))


class TestSystem(unittest.TestCase):
    def test_system_info(self):
        out = u.system_info()
        self.assertIn("System", out)
        self.assertIn("Python", out)

    def test_process_list(self):
        out = u.process_list(3)
        self.assertIn("Process", out)

    def test_process_kill_needs_confirm(self):
        self.assertIn("Confirm", u.process_kill(12345, confirmed=False))

    def test_startup_list(self):
        out = u.startup_list()
        self.assertIn("Startup", out)

    def test_network_speed_mocked(self):
        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                return b"x" * 1000000

        with mock.patch("urllib.request.urlopen", return_value=Resp()):
            out = u.network_speed_test()
            self.assertIn("Mbps", out)

    def test_network_speed_offline(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=Exception("no net")):
            self.assertIn("holo na", u.network_speed_test())

    def test_wifi_bluetooth_vpn(self):
        for fn in (u.wifi_networks, u.bluetooth_devices, u.vpn_status):
            out = fn()
            self.assertIsInstance(out, str)
            self.assertTrue(len(out) > 5)

    def test_battery_monitor(self):
        out = u.battery_monitor()
        self.assertIn("Battery", out)

    def test_screen_record_status(self):
        self.assertIn("bondho", u.screen_record("status"))


class TestCreate(unittest.TestCase):
    def test_qr_generate(self):
        import types

        class _FakeImg:
            def save(self, path):
                Path(path).write_bytes(b"PNG")

        fake = types.SimpleNamespace(make=lambda t: _FakeImg())
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(u, "_downloads", return_value=Path(tmp)), \
                    mock.patch.dict(sys.modules, {"qrcode": fake}):
                out = u.qr_generate("https://example.com", "test-qr")
                self.assertIn("QR banalam", out)
                self.assertTrue((Path(tmp) / "test-qr.png").is_file())

    def test_password_generate(self):
        out = u.password_generate(16)
        self.assertIn("Password banalam", out)
        pw = out.split(":")[1].strip().split("\n")[0]
        self.assertEqual(len(pw), 16)

    def test_meme_make(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "img.png"
            Image.new("RGB", (400, 300), (10, 20, 30)).save(src)
            out = u.meme_make(str(src), "TOP", "BOTTOM")
            self.assertIn("Meme banalam", out)
            self.assertTrue((Path(tmp) / "img-meme.png").is_file())

    def test_subtitle_make(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(u, "_downloads", return_value=Path(tmp)):
                out = u.subtitle_make("", "Hello\nWorld")
                self.assertIn("Subtitle file", out)
                self.assertIn("2 ta caption", out)

    def test_invoice_make(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(u, "_downloads", return_value=Path(tmp)):
                out = u.invoice_make("Acme", 1500, "Design\nHosting")
                self.assertIn("INV-", out)
                self.assertIn("Acme", out)

    def test_resume_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(u, "_downloads", return_value=Path(tmp)):
                out = u.resume_build("Test User", "Developer", "Python, SQL")
                self.assertIn("Resume banalam", out)
                self.assertIn("Test User", out)


class TestLife(unittest.TestCase):
    def setUp(self):
        self.store = {}
        self.p1, self.p2 = _cfg_mock(self.store)
        self.p1.start()
        self.p2.start()

    def tearDown(self):
        self.p1.stop()
        self.p2.stop()

    def test_notes(self):
        self.assertIn("save korlam", u.note_add("buy milk"))
        self.assertIn("buy milk", u.note_list())

    def test_habits(self):
        self.assertIn("banalam", u.habit_add("Morning walk"))
        out = u.habit_tick("Morning walk")
        self.assertIn("done", out)
        self.assertIn("Streak: 1", out)
        self.assertIn("aaj done", u.habit_status())
        self.assertIn("pelam na", u.habit_tick("nope"))

    def test_expenses(self):
        self.assertIn("likhlam", u.expense_add(250, "lunch", "food"))
        u.expense_add(100, "bus", "travel")
        out = u.expense_summary()
        self.assertIn("350", out)
        self.assertIn("food", out)

    def test_bookmarks(self):
        self.assertIn("save korlam",
                      u.bookmark_add("https://example.com", "Example"))
        self.assertIn("example.com", u.bookmark_list())
        self.assertIn("http(s)", u.bookmark_add("not-a-url"))

    def test_contacts(self):
        self.assertIn("save korlam",
                      u.contact_add("Rahim", "01700000000", "r@x.com"))
        out = u.contact_find("rahim")
        self.assertIn("Rahim", out)
        self.assertIn("01700000000", out)
        self.assertIn("pelam na", u.contact_find("nobody"))

    def test_calendar(self):
        self.assertIn("likhlam", u.calendar_add("Meeting", "2026-11-20 15:00"))
        out = u.calendar_today()
        self.assertIn("Aaj", out)

    def test_flashcards(self):
        self.assertIn("save korlam",
                      u.flashcard_add("Capital of France?", "Paris"))
        out = u.flashcard_quiz()
        self.assertIn("Capital of France?", out)
        self.assertIn("Paris", out)

    def test_quiz(self):
        out = u.quiz_make("", 2)
        self.assertIn("Quiz", out)
        self.assertIn("Dhaka", out)

    def test_poll(self):
        out = u.poll_make("Tea or coffee?", "Tea, Coffee")
        self.assertIn("Poll banalam", out)
        out = u.poll_vote(1)
        self.assertIn("Tea: 1 vote", out)
        self.assertIn("Tea", u.poll_status())

    def test_dictionary_offline(self):
        with mock.patch("urllib.request.urlopen",
                        side_effect=Exception("no net")):
            self.assertIn("internet lagbe", u.dictionary_lookup("hello"))

    def test_dictionary_mocked(self):
        payload = json.dumps([{"meanings": [{"partOfSpeech": "noun",
                                             "definitions": [{"definition":
                                                              "a greeting"}]}]}])
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = payload.encode()
        resp.__exit__.return_value = False
        with mock.patch("urllib.request.urlopen", return_value=resp):
            out = u.dictionary_lookup("hello")
        self.assertIn("greeting", out)


class TestMediaPhoneVault(unittest.TestCase):
    def test_audio_convert_needs_ffmpeg(self):
        with mock.patch.object(u, "_ffmpeg", return_value=""):
            with tempfile.NamedTemporaryFile(suffix=".wav") as f:
                out = u.audio_convert(f.name, "mp3")
                self.assertIn("ffmpeg lagbe", out)

    def test_video_download_needs_ytdlp(self):
        with mock.patch("shutil.which", return_value=None):
            out = u.video_download("https://youtu.be/dQw4w9WgXcQ")
            self.assertIn("yt-dlp lagbe", out)

    def test_sms_needs_phone(self):
        with mock.patch("core.jarvis_link.LINK", None):
            out = u.sms_send("01700000000", "hi")
            self.assertIn("pair kora nei", out)

    def test_call_log_needs_phone(self):
        with mock.patch("core.jarvis_link.LINK", None):
            self.assertIn("pair kora nei", u.call_log())

    def test_step_counter_needs_phone(self):
        with mock.patch("core.jarvis_link.LINK", None):
            self.assertIn("pair kora nei", u.step_counter())

    @unittest.skipUnless(_HAS_CRYPTO, "cryptography not installed in this VM")
    def test_vault_round_trip(self):
        store = {}
        p1, p2 = _cfg_mock(store)
        with p1, p2:
            self.assertIn("save korlam",
                          u.vault_put("gmail", "me@example.com", "s3cret!"))
            out = u.vault_get("gmail")
            self.assertIn("me@example.com", out)
            self.assertIn("s3cret!", out)
            self.assertIn("pelam na", u.vault_get("nope"))

    @unittest.skipIf(_HAS_CRYPTO, "cryptography is installed here")
    def test_vault_without_crypto_is_honest(self):
        store = {}
        p1, p2 = _cfg_mock(store)
        with p1, p2:
            out = u.vault_put("gmail", "me@example.com", "s3cret!")
            self.assertIn("parlam na", out)
            self.assertIn("cryptography", out)

    def test_vault_empty(self):
        store = {}
        p1, p2 = _cfg_mock(store)
        with p1, p2:
            self.assertIn("khali", u.vault_get("gmail"))


if __name__ == "__main__":
    unittest.main()
