"""tests/test_agent_cards_update.py — the 87 agent cards update:
core/agent_cards.py, core/render_deploy.py, core/browser_control.py,
core/firebase_connect.py, core/hosting_autofix.py, core/live_screen.py,
core/language.py + the new plugins (jarvis_language, jarvis_agent_cards,
firebase_connect, hosting_autofix, live_screen, python_run, system_status,
gradle_build, software_builder, commander, photo_editor) + the Bengali-only prompt hook.

Advanced round adds 4 more cards (data_analyzer, report_writer,
email_sender, file_organizer) and the voice_settings + browser_advanced
plugins — 28 -> 32 cards.

Agents round adds 50 utility cards (Timer … Password Vault, incl. the
YouTube agent) + the utility_* / youtube_play / file_edit / auto_task /
watchdog24 plugins — 32 -> 87 cards.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only. No network, no Qt, no real mouse/Chrome/Render/GitHub calls:
HTTP is mocked, the driver/mouse/link are fakes, config is monkeypatched.
"""
from __future__ import annotations

import base64
import os
import re
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

ROOT = Path(__file__).resolve().parent.parent


def _real_tools() -> set[str]:
    """Every real tool/plugin/connector-function name in this codebase
    (same derivation as tests/test_plugin_catalog.py)."""
    tools: set[str] = set()
    for path in (ROOT / "plugins").glob("*.py"):
        if path.name.startswith("_"):
            continue
        m = re.search(r'"name":\s*"([^"]+)"', path.read_text(errors="ignore"))
        if m:
            tools.add(m.group(1))
    for path in (ROOT / "actions").glob("*.py"):
        m = re.search(r'"name":\s*"([^"]+)"', path.read_text(errors="ignore"))
        if m:
            tools.add(m.group(1))
    tools.update(re.findall(r'"name":\s*"([a-z_0-9]+)"',
                            (ROOT / "main.py").read_text(errors="ignore")))
    conn = (ROOT / "core" / "connectors.py").read_text(errors="ignore")
    for m in re.findall(r"^def ([a-z_0-9]+)\(", conn, re.M):
        if (m.startswith(("github_", "whatsapp_", "youtube_", "facebook_",
                          "instagram_", "drive_"))
                or m == "connectors_status"):
            tools.add(m)
    return tools


# ── agent cards registry ─────────────────────────────────────────────────────

class TestAgentCardsRegistry(unittest.TestCase):
    def test_exactly_87_cards(self):
        from core import agent_cards as ac
        self.assertEqual(ac.count(), 87, ac.count())
        self.assertEqual(len(ac.CARD_DEFS), 87)

    def test_first_card_is_main_agent(self):
        from core import agent_cards as ac
        first = ac.CARD_DEFS[0]
        self.assertEqual(first["id"], "main")
        self.assertEqual(first["name"], "Main Agent")

    def test_unique_ids_and_required_keys(self):
        from core import agent_cards as ac
        ids = [c["id"] for c in ac.CARD_DEFS]
        self.assertEqual(len(ids), len(set(ids)))
        for c in ac.CARD_DEFS:
            for key in ("id", "name", "icon", "job", "tool", "action"):
                self.assertTrue(str(c.get(key) or "").strip(), (c, key))

    def test_every_card_maps_to_a_real_tool(self):
        from core import agent_cards as ac
        tools = _real_tools()
        for c in ac.CARD_DEFS:
            self.assertIn(c["tool"], tools,
                          f"card {c['id']} tool {c['tool']} is not a real tool")

    def test_every_action_exists(self):
        from core import agent_cards as ac
        self.assertEqual(set(ac._ACTIONS),
                         {c["action"] for c in ac.CARD_DEFS})

    def test_cards_live_readiness_never_raises(self):
        from core import agent_cards as ac
        cards = ac.cards()
        self.assertEqual(len(cards), 87)
        for c in cards:
            self.assertIn("ready", c)
            self.assertIn("missing", c)

    def test_run_card_with_injected_actions(self):
        from core import agent_cards as ac
        # Two cards share one action key ("link_status") — fakes are keyed
        # by action, so assert the action key, not the card id.
        fakes = {c["action"]: (lambda a=c["action"]: f"fake ran {a}")
                 for c in ac.CARD_DEFS}
        for c in ac.CARD_DEFS:
            out = ac.run_card(c["id"], actions=fakes)
            self.assertIn(c["action"], out, c["id"])
        self.assertIn("khuje pelam na", ac.run_card("no_such_card"))

    def test_new_plugins_exist(self):
        from plugins import (firebase_connect, hosting_autofix, live_screen,
                             jarvis_agent_cards, jarvis_language,
                             python_run, system_status, gradle_build,
                             software_builder, commander, photo_editor,
                             data_analyzer, report_writer, email_sender,
                             file_organizer, voice_settings,
                             browser_advanced)
        self.assertEqual(data_analyzer.PLUGIN["name"], "data_analyzer")
        self.assertEqual(report_writer.PLUGIN["name"], "report_writer")
        self.assertEqual(email_sender.PLUGIN["name"], "email_sender")
        self.assertEqual(file_organizer.PLUGIN["name"], "file_organizer")
        self.assertEqual(voice_settings.PLUGIN["name"], "voice_settings")
        self.assertEqual(browser_advanced.PLUGIN["name"], "browser_advanced")
        self.assertEqual(voice_settings.PLUGIN_SETTINGS.get("widget"),
                         "voice_settings")
        from plugins import (utility_time, utility_convert, utility_files,
                             utility_system, utility_create, utility_life,
                             utility_media, utility_phone, utility_vault,
                             youtube_agent, file_edit, auto_tasks, watchdog24)
        self.assertEqual(utility_time.PLUGIN["name"], "utility_time")
        self.assertEqual(utility_convert.PLUGIN["name"], "utility_convert")
        self.assertEqual(utility_files.PLUGIN["name"], "utility_files")
        self.assertEqual(utility_system.PLUGIN["name"], "utility_system")
        self.assertEqual(utility_create.PLUGIN["name"], "utility_create")
        self.assertEqual(utility_life.PLUGIN["name"], "utility_life")
        self.assertEqual(utility_media.PLUGIN["name"], "utility_media")
        self.assertEqual(utility_phone.PLUGIN["name"], "utility_phone")
        self.assertEqual(utility_vault.PLUGIN["name"], "utility_vault")
        self.assertEqual(youtube_agent.PLUGIN["name"], "youtube_play")
        self.assertEqual(file_edit.PLUGIN["name"], "file_edit")
        self.assertEqual(auto_tasks.PLUGIN["name"], "auto_task")
        self.assertEqual(watchdog24.PLUGIN["name"], "watchdog24")
        self.assertEqual(youtube_agent.PLUGIN_SETTINGS.get("widget"),
                         "video_panel")
        self.assertEqual(auto_tasks.PLUGIN_SETTINGS.get("widget"),
                         "auto_tasks")
        self.assertEqual(watchdog24.PLUGIN_SETTINGS.get("widget"),
                         "running24")
        self.assertEqual(firebase_connect.PLUGIN["name"], "firebase_connect")
        self.assertEqual(hosting_autofix.PLUGIN["name"], "hosting_autofix")
        self.assertEqual(live_screen.PLUGIN["name"], "live_screen")
        self.assertEqual(jarvis_agent_cards.PLUGIN["name"], "agent_cards")
        self.assertEqual(jarvis_language.PLUGIN["name"], "set_bengali_only")
        self.assertEqual(python_run.PLUGIN["name"], "python_run")
        self.assertEqual(system_status.PLUGIN["name"], "system_status")
        self.assertEqual(gradle_build.PLUGIN["name"], "gradle_build")
        self.assertEqual(software_builder.PLUGIN["name"], "software_builder")
        self.assertEqual(commander.PLUGIN["name"], "commander")
        self.assertEqual(photo_editor.PLUGIN["name"], "photo_editor")
        self.assertEqual(software_builder.PLUGIN_SETTINGS["widget"],
                         "software_builder")
        self.assertEqual(commander.PLUGIN_SETTINGS["widget"], "commander")
        self.assertEqual(photo_editor.PLUGIN_SETTINGS["widget"], "photo_editor")
        self.assertEqual(
            jarvis_agent_cards.PLUGIN_SETTINGS.get("widget"), "agent_cards")
        self.assertEqual(
            python_run.PLUGIN_SETTINGS.get("widget"), "python_run")
        self.assertEqual(
            system_status.PLUGIN_SETTINGS.get("widget"), "system_status")
        self.assertEqual(
            jarvis_language.PLUGIN_SETTINGS.get("namespace"), "language")


# ── Bengali-only ─────────────────────────────────────────────────────────────

class TestBengaliOnly(unittest.TestCase):
    def _patch_config(self, store):
        def _get(ns):
            return dict(store.get(ns, {}))
        def _save(ns, values):
            store.setdefault(ns, {}).update(values)
        p1 = mock.patch("memory.config_manager.get_plugin_config",
                        side_effect=_get)
        p2 = mock.patch("memory.config_manager.save_plugin_config",
                        side_effect=_save)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def test_off_by_default_and_empty_paragraph(self):
        from core import language as lang
        self._patch_config({})
        self.assertFalse(lang.bengali_only())
        self.assertEqual(lang.prompt_paragraph(), "")

    def test_round_trip_and_paragraph(self):
        from core import language as lang
        self._patch_config({})
        self.assertTrue(lang.set_bengali_only(True))
        self.assertTrue(lang.bengali_only())
        para = lang.prompt_paragraph()
        self.assertIn("Bengali", para)
        self.assertIn("ONLY in Bengali", para)
        self.assertTrue(lang.set_bengali_only(False))
        self.assertFalse(lang.bengali_only())
        self.assertEqual(lang.prompt_paragraph(), "")

    def test_language_plugin_run(self):
        from plugins import jarvis_language as jl
        self._patch_config({})
        out = jl.run({"on": True})
        self.assertIn("ON", out)
        out = jl.run({"on": False})
        self.assertIn("OFF", out)
        out = jl.run({})
        self.assertIn("OFF ache", out)


# ── Render deploy (mocked HTTP) ──────────────────────────────────────────────

class _FakeResp:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data
        self.content = b"{}" if data is None else b"x"

    def json(self):
        return self._data


class _FakeRequests:
    def __init__(self, routes):
        # routes: {(method, path-suffix): (status, data)}
        self.routes = routes
        self.calls = []

    def request(self, method, url, headers=None, json=None, timeout=None):
        self.calls.append((method, url, json))
        for (m, suffix), (st, data) in self.routes.items():
            if method == m and url.endswith(suffix):
                return _FakeResp(st, data)
        return _FakeResp(404, {"message": "not found"})


class TestRenderDeploy(unittest.TestCase):
    def _patch(self, routes):
        from core import render_deploy as rd
        fake_conn = mock.Mock()
        fake_conn.get_token.return_value = "rnd_test_key"
        p1 = mock.patch.object(rd, "_conn", fake_conn)
        fake_rq = _FakeRequests(routes)
        p2 = mock.patch.object(rd, "_requests", fake_rq)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        return rd, fake_rq

    def test_list_services(self):
        rd, _ = self._patch({
            ("GET", "/services?limit=20"): (200, [
                {"service": {"id": "srv-1", "name": "mark-lvii-dashboard",
                             "serviceDetails": {"url": "https://x.onrender.com"},
                             "repo": "https://github.com/o/r"}}]),
        })
        services, err = rd.list_services()
        self.assertEqual(err, "")
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0]["name"], "mark-lvii-dashboard")
        self.assertEqual(services[0]["repo"], "https://github.com/o/r")

    def test_find_service_and_trigger_deploy(self):
        rd, rq = self._patch({
            ("GET", "/services?limit=20"): (200, [
                {"service": {"id": "srv-1", "name": "mark-lvii-dashboard",
                             "serviceDetails": {"url": "https://x"}}}]),
            ("POST", "/services/srv-1/deploys"): (201, {"deploy": {"id": "dep-9"}}),
        })
        self.assertEqual(rd.trigger_deploy(), "⏳ Render deploy shuru holo"
                         " (deploy dep-9) — dashboard update hochhe, koyek minute lagbe.")
        self.assertTrue(any(c[0] == "POST" and c[1].endswith("/deploys")
                            for c in rq.calls))

    def test_trigger_deploy_no_key(self):
        from core import render_deploy as rd
        with mock.patch.object(rd, "_conn") as fake_conn:
            fake_conn.get_token.return_value = ""
            self.assertIn("Render API key", rd.trigger_deploy())

    def test_set_env_var_uses_single_key_put(self):
        rd, rq = self._patch({
            ("PUT", "/services/srv-1/env-vars/PORT"): (200, {"envVar": {"key": "PORT"}}),
        })
        out = rd.set_env_var("srv-1", "PORT", "10000")
        self.assertIn("✅", out)
        # The replace-all endpoint (no key) must never be called.
        self.assertFalse(any(c[0] == "PUT" and c[1].endswith("/env-vars")
                             for c in rq.calls))
        self.assertTrue(any(c[1].endswith("/env-vars/PORT") for c in rq.calls))

    def test_deploy_status_and_logs(self):
        rd, _ = self._patch({
            ("GET", "/services?limit=20"): (200, [
                {"service": {"id": "srv-1", "name": "mark-lvii-dashboard"}}]),
            ("GET", "/services/srv-1/deploys?limit=1"): (200, [
                {"deploy": {"id": "dep-1", "status": "live",
                            "commit": {"id": "abcdef12"},
                            "createdAt": "2026-11-17T00:00:00Z"}}]),
            ("GET", "/services/srv-1/deploys/dep-1/logs?limit=200"): (200, {
                "logs": [{"message": "Build succeeded"},
                         {"message": "Deploy live"}]}),
            ("GET", "/services/srv-1/env-vars?limit=100"): (200, [
                {"envVar": {"key": "PORT", "value": "10000"}, "cursor": "c1"},
                {"envVar": {"key": "NODE_ENV", "value": "production"},
                 "cursor": "c2"}]),
        })
        self.assertIn("live", rd.deploy_status())
        logs = rd.deploy_logs("srv-1", "dep-1")
        self.assertIn("Build succeeded", logs)
        keys, err = rd.list_env_var_keys("srv-1")
        self.assertEqual(err, "")
        self.assertEqual(keys, ["PORT", "NODE_ENV"])


# ── Firebase connect ─────────────────────────────────────────────────────────

class TestFirebaseConnect(unittest.TestCase):
    def test_sdkconfig_command(self):
        from core import firebase_connect as fb
        self.assertEqual(fb.sdkconfig_command("my-proj"),
                         "firebase apps:sdkconfig web --project my-proj")
        self.assertEqual(fb.sdkconfig_command("my-proj", "android"),
                         "firebase apps:sdkconfig android --project my-proj")
        self.assertEqual(fb.sdkconfig_command(""), "")

    def test_cli_available(self):
        from core import firebase_connect as fb
        with mock.patch("core.firebase_connect.shutil.which",
                        return_value=""):
            ok, msg = fb.cli_available()
            self.assertFalse(ok)
            self.assertIn("firebase-tools", msg)
        with mock.patch("core.firebase_connect.shutil.which",
                        return_value="/usr/bin/firebase"):
            ok, _ = fb.cli_available()
            self.assertTrue(ok)

    def test_classify_console_state(self):
        from core import firebase_connect as fb
        self.assertEqual(fb.classify_console_state(
            "Sign in with Google to continue"), "login_needed")
        self.assertEqual(fb.classify_console_state(
            "Welcome — Add project to get started"), "create_project")
        self.assertEqual(fb.classify_console_state(
            "Project overview — Project settings"), "project_page")
        self.assertEqual(fb.classify_console_state("Firebase console"),
                         "console")
        self.assertEqual(fb.classify_console_state(""), "unknown")

    def test_connect_flow_login_needed_stops_honestly(self):
        from core import firebase_connect as fb

        class _FakeDriver:
            def navigate(self, url):
                return True, "ok"
            def read_text(self):
                return True, "Sign in with Google to continue"
            def click(self, sel):
                return False, "no"
            def close(self):
                pass

        def _driver_fn():
            return _FakeDriver(), "playwright", "ok"

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ok, msg = fb.connect_flow(tmp, driver_fn=_driver_fn)
        self.assertFalse(ok)
        self.assertIn("Google login", msg)

    def test_connect_flow_clicks_add_project(self):
        from core import firebase_connect as fb

        class _FakeDriver:
            def __init__(self):
                self.clicked = []
            def navigate(self, url):
                return True, "ok"
            def read_text(self):
                return True, "Welcome — Add project to get started"
            def click(self, sel):
                self.clicked.append(sel)
                return True, "ok"
            def close(self):
                pass

        drv = _FakeDriver()

        def _driver_fn():
            return drv, "playwright", "ok"

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ok, msg = fb.connect_flow(tmp, driver_fn=_driver_fn)
        self.assertTrue(ok)
        self.assertIn("Add project", msg)
        self.assertTrue(drv.clicked)


# ── Hosting auto-fix ─────────────────────────────────────────────────────────

class TestHostingAutofix(unittest.TestCase):
    def test_classify_missing_env_known_default(self):
        from core import hosting_autofix as hf
        found = hf.classify_hosting_failure(
            "Error: Missing environment variable: PORT\nTraceback ...")
        self.assertEqual(found["kind"], "missing_env_var")
        self.assertEqual(found["key"], "PORT")
        self.assertEqual(found["fix"], "set_default")

    def test_classify_missing_env_ask_user(self):
        from core import hosting_autofix as hf
        found = hf.classify_hosting_failure(
            "KeyError: 'STRIPE_SECRET_KEY'")
        self.assertEqual(found["kind"], "missing_env_var")
        self.assertEqual(found["fix"], "ask_user")

    def test_classify_dependency(self):
        from core import hosting_autofix as hf
        found = hf.classify_hosting_failure(
            "ERROR: Could not find a version that satisfies the requirement "
            "nonexistent-pkg==9.9.9")
        self.assertEqual(found["kind"], "dependency")
        self.assertEqual(found["key"], "nonexistent-pkg==9.9.9")

    def test_classify_port_oom_transient_unknown(self):
        from core import hosting_autofix as hf
        self.assertEqual(
            hf.classify_hosting_failure("No open ports detected")["kind"],
            "port")
        self.assertEqual(
            hf.classify_hosting_failure("Out of memory: Killed process")["kind"],
            "out_of_memory")
        self.assertEqual(
            hf.classify_hosting_failure(
                "Connection timed out — temporary failure")["kind"],
            "transient")
        self.assertEqual(
            hf.classify_hosting_failure("something odd happened")["kind"],
            "unknown")
        self.assertEqual(hf.classify_hosting_failure("")["kind"], "unknown")

    def test_autofix_sets_known_default_and_redeploys(self):
        from core import hosting_autofix as hf
        calls = {"env": [], "deploys": 0}

        class _FakeRD:
            def find_service(self, needle):
                return {"id": "srv-1", "name": "mark-lvii-dashboard"}
            def latest_deploy(self, sid):
                calls["deploys"] += 1
                if calls["deploys"] == 1:
                    return {"id": "dep-1", "status": "update_failed"}, ""
                return {"id": "dep-2", "status": "live"}, ""
            def deploy_logs(self, sid, did):
                return "Error: Missing environment variable: PORT"
            def set_env_var(self, sid, key, value):
                calls["env"].append((key, value))
                return f"✅ Env var {key} set holo"
            def trigger_deploy(self, sid):
                return "deploy shuru"
            def get_service(self, sid):
                return {"repo": "https://github.com/o/r"}, ""

        with mock.patch.object(hf, "_rd", _FakeRD()):
            out = hf.autofix()
        self.assertIn("live", out)
        self.assertEqual(calls["env"], [("PORT", "10000")])

    def test_autofix_asks_for_unknown_env_value(self):
        from core import hosting_autofix as hf

        class _FakeRD:
            def find_service(self, needle):
                return {"id": "srv-1", "name": "mark-lvii-dashboard"}
            def latest_deploy(self, sid):
                return {"id": "dep-1", "status": "update_failed"}, ""
            def deploy_logs(self, sid, did):
                return "KeyError: 'STRIPE_SECRET_KEY'"
            def set_env_var(self, sid, key, value):
                raise AssertionError("must not guess an unknown value")
            def trigger_deploy(self, sid):
                raise AssertionError("must not redeploy without a fix")
            def get_service(self, sid):
                return {}, ""

        with mock.patch.object(hf, "_rd", _FakeRD()):
            out = hf.autofix()
        self.assertIn("STRIPE_SECRET_KEY", out)
        self.assertIn("value", out)


# ── Live screen ──────────────────────────────────────────────────────────────

class _FakeLink:
    paired = True
    mark_id = "mark-test"
    pc_token = "tok-test"

    def __init__(self, frames):
        # frames: list of (base64-image, at) returned in order
        self._frames = list(frames)
        self._i = 0
        self.fetched = 0

    def _get(self, path, timeout=5.0):
        if "screen-stream" in path:
            return None
        f = self._frames[min(self._i, len(self._frames) - 1)]
        self._i += 1
        return {"image": f[0], "at": f[1]}

    def fetch_phone_screen(self, timeout=15.0):
        self.fetched += 1
        return "ok"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class TestLiveScreen(unittest.TestCase):
    def test_streamer_delivers_changing_frames(self):
        from core import live_screen as ls
        frames = [(_b64(b"jpeg-1"), "t1"), (_b64(b"jpeg-2"), "t2"),
                  (_b64(b"jpeg-3"), "t3")]
        link = _FakeLink(frames)
        got = []
        st = ls.LiveScreenStreamer(link=link, fps=20,
                                   on_frame=lambda b: got.append(b))
        ok, msg = st.start()
        self.assertTrue(ok)
        time.sleep(0.6)
        st.stop()
        time.sleep(0.2)
        self.assertGreaterEqual(len(got), 2)
        self.assertIn(b"jpeg", got[0])
        self.assertIn(st.mode, ("poll", "stream", "stills", "off"))

    def test_streamer_falls_back_to_stills_when_frame_never_changes(self):
        from core import live_screen as ls
        link = _FakeLink([(_b64(b"same"), "t1")])
        got = []
        st = ls.LiveScreenStreamer(link=link, fps=20,
                                   on_frame=lambda b: got.append(b))
        st.start()
        # Stills fallback is time-based (2 s without a new frame), so the
        # wait must cover that window.
        time.sleep(2.5)
        st.stop()
        self.assertGreaterEqual(link.fetched, 1)
        self.assertEqual(len(got), 1)  # only the first (unchanged) frame once

    def test_live_status_with_frame(self):
        from core import live_screen as ls
        link = _FakeLink([(_b64(b"jpeg-1"), "2026-11-17T10:00:00Z")])
        out = ls.live_status(link=link)
        self.assertIn("screen pelam", out)

    def test_live_status_unpaired(self):
        from core import live_screen as ls

        class _Unpaired:
            paired = False
        self.assertIn("pair kora nei", ls.live_status(link=_Unpaired()))


# ── Browser control (mouse-driven Chrome) ────────────────────────────────────

class TestBrowserControl(unittest.TestCase):
    def test_open_chrome_mouse_windows_path(self):
        from core import browser_control as bc

        class _FakeMouse:
            def __init__(self):
                self.calls = []
            def screen_size(self):
                return (1920, 1080)
            def click(self, x, y):
                self.calls.append(("click", x, y))
                return True, "ok"
            def type_text(self, text):
                self.calls.append(("type", text))
                return True, "ok"
            def press_key(self, key):
                self.calls.append(("press", key))
                return True, "ok"

        fake_mouse = _FakeMouse()

        class _FakeDriver:
            def navigate(self, url):
                return True, "ok"
            def close(self):
                pass

        def _driver_fn():
            return _FakeDriver(), "cdp", "attached"

        with mock.patch.object(bc, "_mc", fake_mouse), \
             mock.patch.object(bc, "_wait_chrome", return_value=True), \
             mock.patch("platform.system", return_value="Windows"):
            ok, msg = bc.open_chrome_mouse("https://www.google.com",
                                           driver_fn=_driver_fn)
        self.assertTrue(ok)
        self.assertIn("google.com", msg)
        self.assertIn(("click", 15, 1065), fake_mouse.calls)
        self.assertIn(("type", "chrome"), fake_mouse.calls)
        self.assertIn(("press", "enter"), fake_mouse.calls)

    def test_drive_url_driver_not_ready(self):
        from core import browser_control as bc
        with mock.patch.object(bc, "_drv") as fake_drv:
            fake_drv.ensure_driver.return_value = (None, "", "no playwright")
            fake_drv.BACKEND_PYAUTOGUI = "pyautogui"
            ok, msg = bc.drive_url("https://www.google.com")
        self.assertFalse(ok)
        self.assertIn("Driver ready noy", msg)


# ── Registry intact ──────────────────────────────────────────────────────────

class TestRegistryIntact(unittest.TestCase):
    def test_total_still_23_72m(self):
        from core import feature_registry as fr
        self.assertEqual(fr.TOTAL, 23_720_000)


if __name__ == "__main__":
    unittest.main()
