"""tests/test_software_builder.py — 🛠️ Software Builder: build → run → fix.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only. The localhost run is REAL (a real http.server on a real free
port, fetched with urllib) — no network beyond 127.0.0.1. Gemini is
mocked where generation is involved; deploy is mocked at the connectors
boundary. Servers started by a test are always stopped again.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import software_builder as sb  # noqa: E402


class _ServerTestBase(unittest.TestCase):
    """Server tests: config (the server registry) is in-memory so no
    real config file is touched, and every started server is stopped
    while the patch is still on."""

    def setUp(self):
        self._store: dict = {}
        self._get = mock.patch(
            "memory.config_manager.get_plugin_config",
            side_effect=lambda ns: dict(self._store.get(ns, {})))
        self._save = mock.patch(
            "memory.config_manager.save_plugin_config",
            side_effect=lambda ns, values: self._store.setdefault(
                ns, {}).update(values))
        self._get.start()
        self._save.start()

    def tearDown(self):
        try:
            for srv in sb.list_servers():
                sb.stop_server(srv["id"])
        except Exception:
            pass
        self._get.stop()
        self._save.stop()


class TestClassify(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(sb.classify_spec("ekta todo dashboard banao"), "web")
        self.assertEqual(sb.classify_spec("ekta website banao"), "web")
        self.assertEqual(sb.classify_spec("desktop app banao"), "desktop")
        self.assertEqual(sb.classify_spec("ekta pyqt app chai"), "desktop")
        self.assertEqual(sb.classify_spec("ekta converter tool banao"), "tool")
        self.assertEqual(sb.classify_spec("kono ekta app"), "web")

    def test_slugify(self):
        self.assertEqual(sb.slugify("My Todo Dashboard!"), "my-todo-dashboard")
        self.assertTrue(sb.slugify(""))


class TestGenerate(unittest.TestCase):
    def test_fallback_web_is_real(self):
        files = sb.generate_project("Todo Dashboard", "web")
        self.assertIn("main.py", files)
        self.assertIn("index.html", files)
        self.assertIn("PORT", files["main.py"])
        self.assertIn("Todo Dashboard", files["index.html"])

    def test_fallback_desktop_and_tool(self):
        desk = sb.generate_project("Note App", "desktop")
        self.assertIn("tkinter", desk["main.py"])
        tool = sb.generate_project("Rename Tool", "tool")
        self.assertIn("def main", tool["main.py"])

    def test_ask_fn_used_when_it_returns_files(self):
        def _ask(prompt):
            return json.dumps({"files": {
                "main.py": "import os\nprint('gemini app', os.environ.get('PORT'))\n",
                "README.md": "# Gemini app\n"}})
        files = sb.generate_project("X", "web", ask_fn=_ask)
        self.assertIn("gemini app", files["main.py"])

    def test_ask_fn_failure_falls_back(self):
        files = sb.generate_project("Y", "web", ask_fn=lambda p: "not json")
        self.assertIn("main.py", files)
        self.assertIn("PORT", files["main.py"])

    def test_never_empty(self):
        self.assertTrue(sb.generate_project("", ""))


class TestBuildProject(unittest.TestCase):
    def test_writes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = sb.build_project("Todo Dashboard", base_dir=tmp)
            self.assertTrue(res["ok"], res)
            folder = Path(res["folder"])
            self.assertTrue((folder / "main.py").is_file())
            self.assertTrue((folder / "index.html").is_file())
            self.assertEqual(res["kind"], "web")

    def test_empty_spec_refused(self):
        self.assertFalse(sb.build_project("")["ok"])


class TestPorts(unittest.TestCase):
    def test_busy_port_skipped(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            busy = s.getsockname()[1]
            port, preferred = sb.pick_free_port(busy)
            self.assertNotEqual(port, busy)
            self.assertFalse(preferred)

    def test_free_port_preferred(self):
        port, preferred = sb.pick_free_port(18765)
        self.assertEqual(port, 18765)
        self.assertTrue(preferred)


class TestLocalhostRun(_ServerTestBase):

    def test_real_server_serves_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            built = sb.build_project("Todo Dashboard", base_dir=tmp)
            self.assertTrue(built["ok"], built)
            res = sb.start_server(built["folder"], port=18766)
            self.assertTrue(res["ok"], res)
            self.assertTrue(res["url"].startswith("http://localhost:"))
            with urllib.request.urlopen(res["url"], timeout=10) as r:
                self.assertEqual(r.status, 200)
                body = r.read().decode("utf-8")
            self.assertIn("Todo Dashboard", body)
            with urllib.request.urlopen(res["url"] + "/api/hello",
                                       timeout=10) as r:
                data = json.loads(r.read().decode("utf-8"))
            self.assertTrue(data.get("ok"))
            servers = sb.list_servers()
            self.assertEqual(len(servers), 1)
            self.assertEqual(servers[0]["port"], res["port"])
            out = sb.stop_server(res["server_id"])
            self.assertIn("bondho", out)
            self.assertEqual(sb.list_servers(), [])

    def test_build_and_run_text_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(sb, "default_projects_dir",
                                   return_value=Path(tmp)):
                out = sb.build_and_run_text("Todo Dashboard",
                                            open_browser=False)
            self.assertIn("Localhost: http://localhost:", out)
            self.assertIn("✅", out)

    def test_build_and_run_text_bad_spec(self):
        self.assertIn("spec dao", sb.build_and_run_text(""))


class TestFixLoop(unittest.TestCase):
    def test_two_failures_then_success(self):
        calls = {"n": 0}

        def _flaky(folder, entry="main.py"):
            calls["n"] += 1
            if calls["n"] < 3:
                return {"ok": False, "error": "boom"}
            return {"ok": True, "url": "http://localhost:18767",
                    "port": 18767, "server_id": "srv-test"}

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(sb, "open_in_browser",
                                   return_value="browser mocked"):
                res = sb.build_and_run("Todo", base_dir=tmp,
                                       start_fn=_flaky, open_browser=True)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["attempts"], 3)
        self.assertEqual(calls["n"], 3)

    def test_always_failing_gives_up_at_3(self):
        def _fail(folder, entry="main.py"):
            return {"ok": False, "error": "boom"}
        with tempfile.TemporaryDirectory() as tmp:
            res = sb.build_and_run("Todo", base_dir=tmp, start_fn=_fail)
        self.assertFalse(res["ok"])
        self.assertEqual(res["attempts"], 3)
        self.assertIn("3 bar", res["error"])


class TestDeploy(unittest.TestCase):
    def test_no_repo_is_honest(self):
        with tempfile.TemporaryDirectory() as tmp:
            link, note = sb.deploy_project(tmp, "my-app", repo="")
            self.assertEqual(link, "")
            self.assertIn("repo dao", note)

    def test_push_then_no_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "main.py").write_text("print(1)\n", encoding="utf-8")
            with mock.patch("core.connectors.github_push_file",
                           return_value="✅ pushed") as push, \
                 mock.patch("core.render_deploy.find_service",
                           return_value=None):
                link, note = sb.deploy_project(tmp, "my-app",
                                               repo="o/my-app")
            self.assertTrue(push.called)
            self.assertIn("github.com/o/my-app", link)
            self.assertIn("service ekhono nei", note)

    def test_push_then_service_triggers_deploy(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "main.py").write_text("print(1)\n", encoding="utf-8")
            svc = {"id": "srv-1",
                   "serviceDetails": {"url": "my-app.onrender.com"}}
            with mock.patch("core.connectors.github_push_file",
                           return_value="✅ pushed"), \
                 mock.patch("core.render_deploy.find_service",
                           return_value=svc), \
                 mock.patch("core.render_deploy.trigger_deploy",
                           return_value="ok") as trig:
                link, note = sb.deploy_project(tmp, "my-app",
                                               repo="o/my-app")
            self.assertEqual(link, "https://my-app.onrender.com")
            self.assertTrue(trig.called)
            self.assertIn("deploy trigger", note)


class TestPhoneRelay(_ServerTestBase):
    def test_prefix_detection(self):
        self.assertTrue(sb.is_phone_request("SOFTWARE_BUILD::{}"))
        self.assertFalse(sb.is_phone_request("hello"))

    def test_phone_request_builds_and_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(sb, "default_projects_dir",
                                   return_value=Path(tmp)), \
                 mock.patch.object(sb, "open_in_browser",
                                   return_value="browser mocked"):
                out = sb.handle_phone_request(
                    'SOFTWARE_BUILD::{"spec": "Todo Dashboard"}')
        self.assertIn("Localhost: http://localhost:", out)

    def test_phone_request_plain_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(sb, "default_projects_dir",
                                   return_value=Path(tmp)), \
                 mock.patch.object(sb, "open_in_browser",
                                   return_value="browser mocked"):
                out = sb.handle_phone_request(
                    "SOFTWARE_BUILD::ekta todo dashboard banao")
        self.assertIn("Localhost: http://localhost:", out)

    def test_phone_request_empty_spec(self):
        self.assertIn("spec dao",
                      sb.handle_phone_request('SOFTWARE_BUILD::{"spec": ""}'))


class TestPluginContract(_ServerTestBase):
    def test_plugin_never_raises(self):
        from plugins import software_builder as plugin
        self.assertEqual(plugin.PLUGIN["name"], "software_builder")
        self.assertEqual(plugin.PLUGIN_SETTINGS["widget"], "software_builder")
        self.assertIn("spec dao", plugin.run({}))
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(sb, "default_projects_dir",
                                   return_value=Path(tmp)), \
                 mock.patch.object(sb, "open_in_browser",
                                   return_value="browser mocked"):
                out = plugin.run({"spec": "Todo Dashboard"})
        self.assertIn("Localhost: http://localhost:", out)


if __name__ == "__main__":
    unittest.main()
