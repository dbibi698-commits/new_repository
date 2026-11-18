"""tests/test_autostart_gradle.py — 🖥️ autostart + system status and
🛠️ Gradle/Kotlin scaffolding + local build detection.

Run from ~/workspace/mark-lvii:
    python3 tests/test_autostart_gradle.py
    python3 -m unittest discover -s tests -v

Stdlib only. Windows paths are mocked (this VM is Linux); no real
shortcut is created on this machine, no network, no real Gradle/Java
needed — the toolchain probes are mocked, and the scaffold writer works
on a temp dir. No Qt.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import autostart as autostart_mod  # noqa: E402
from core import gradle_build as gb  # noqa: E402


# ── autostart ────────────────────────────────────────────────────────────────

class TestAutostart(unittest.TestCase):
    def test_not_windows_is_honest(self):
        with mock.patch.object(autostart_mod.platform, "system",
                               return_value="Linux"):
            self.assertEqual(autostart_mod.startup_folder(), "")
            self.assertFalse(autostart_mod.autostart_enabled())
            ok, msg = autostart_mod.set_autostart(True)
            self.assertFalse(ok)
            self.assertIn("Windows", msg)

    def test_windows_shortcut_lifecycle_mocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            appdata = Path(tmp) / "AppData" / "Roaming"
            appdata.mkdir(parents=True)
            with mock.patch.object(autostart_mod.platform, "system",
                                   return_value="Windows"), \
                 mock.patch.dict(os.environ, {"APPDATA": str(appdata)}):
                folder = autostart_mod.startup_folder()
                self.assertTrue(folder.endswith("Startup"))
                self.assertFalse(autostart_mod.autostart_enabled())

                def _fake_cscript(argv, **kwargs):
                    # Pretend cscript created the shortcut.
                    Path(autostart_mod.shortcut_path()).touch()
                    return mock.Mock(returncode=0, stdout="", stderr="")

                with mock.patch.object(autostart_mod.subprocess, "run",
                                       side_effect=_fake_cscript):
                    ok, msg = autostart_mod.set_autostart(True)
                self.assertTrue(ok)
                self.assertIn("ON", msg)
                self.assertTrue(autostart_mod.autostart_enabled())
                ok, msg = autostart_mod.set_autostart(False)
                self.assertTrue(ok)
                self.assertIn("OFF", msg)
                self.assertFalse(autostart_mod.autostart_enabled())

    def test_environment_status_mocked_probes(self):
        def _fake_which(cmd, args, timeout=5):
            if cmd == "java":
                return True, "openjdk version \"17.0.9\""
            return False, ""

        with mock.patch.object(autostart_mod, "_which_version",
                               side_effect=_fake_which), \
             mock.patch.object(autostart_mod, "_chrome_path",
                               return_value=r"C:\Program Files\Google\Chrome\Application\chrome.exe"), \
             mock.patch.object(autostart_mod, "_playwright_installed",
                               return_value=True), \
             mock.patch.object(autostart_mod, "autostart_enabled",
                               return_value=True):
            st = autostart_mod.environment_status()
            self.assertTrue(st["autostart"])
            self.assertEqual(st["python_version"], sys.version.split()[0])
            self.assertTrue(st["chrome_found"])
            self.assertTrue(st["playwright"])
            self.assertTrue(st["java"])
            self.assertIn("17.0.9", st["java_version"])
            self.assertFalse(st["gradle"])
            lines = autostart_mod.environment_lines()
            self.assertIn("Autostart: ✅", lines)
            self.assertIn("Chrome: ✅", lines)
            self.assertIn("Java: ✅", lines)
            self.assertIn("Gradle: ❌", lines)

    def test_system_status_plugin(self):
        from plugins import system_status as plugin
        self.assertEqual(plugin.PLUGIN["name"], "system_status")
        self.assertEqual(plugin.PLUGIN_SETTINGS.get("widget"),
                         "system_status")
        out = plugin.run({})
        self.assertIn("System status", out)
        self.assertIn("Autostart", out)


# ── Gradle / Kotlin ──────────────────────────────────────────────────────────

class TestGradleScaffold(unittest.TestCase):
    def test_scaffold_files_shape(self):
        files = gb.scaffold_files("com.example.myapp", "My App")
        self.assertEqual(len(files), 6)
        self.assertIn("build.gradle.kts", files)
        self.assertIn("settings.gradle.kts", files)
        self.assertIn("gradle/wrapper/gradle-wrapper.properties", files)
        self.assertIn("app/build.gradle.kts", files)
        self.assertIn("app/src/main/AndroidManifest.xml", files)
        kt = "app/src/main/java/com/example/myapp/MainActivity.kt"
        self.assertIn(kt, files)
        self.assertIn("com.example.myapp", files["app/build.gradle.kts"])
        self.assertIn("8.5.2", files["build.gradle.kts"])
        self.assertIn("2.0.0", files["build.gradle.kts"])
        self.assertIn('android:exported="true"',
                      files["app/src/main/AndroidManifest.xml"])
        self.assertIn("gradle-8.7-bin.zip",
                      files["gradle/wrapper/gradle-wrapper.properties"])
        self.assertIn("class MainActivity", files[kt])

    def test_custom_kotlin_code_and_bad_package(self):
        files = gb.scaffold_files("123bad package!!", "App",
                                  kotlin_code="package x\nclass MainActivity")
        kt = [k for k in files if k.endswith("MainActivity.kt")][0]
        self.assertIn("class MainActivity", files[kt])
        self.assertNotIn("123bad", kt)

    def test_write_scaffold_to_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, msg, written = gb.write_android_scaffold(
                str(Path(tmp) / "myapp"), package="com.example.demo",
                app_name="Demo")
            self.assertTrue(ok)
            self.assertEqual(len(written), 6)
            self.assertTrue((Path(tmp) / "myapp" / "app" / "build.gradle.kts").is_file())
            self.assertIn("Demo", msg)
            ok, msg, _ = gb.write_android_scaffold("")
            self.assertFalse(ok)
            self.assertIn("path dao", msg)

    def test_local_toolchain_status_mocked(self):
        def _fake_which(cmd, args, timeout=5):
            if cmd == "java":
                return True, 'openjdk version "21.0.1"'
            if cmd == "gradle":
                return True, "Gradle 8.7"
            return False, ""

        with mock.patch.object(gb, "_which_version", side_effect=_fake_which):
            st = gb.local_toolchain_status()
            self.assertTrue(st["java"])
            self.assertTrue(st["gradle"])
            self.assertFalse(st["gradlew"])

    def test_local_build_no_java_is_honest(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(gb, "local_toolchain_status",
                                   return_value={"java": False, "java_version": "",
                                                 "gradle": False, "gradle_version": "",
                                                 "gradlew": False, "gradlew_path": ""}):
                out = gb.local_gradle_build(tmp)
            self.assertIn("Java pelam na", out)
            self.assertIn("GitHub Actions", out)

    def test_local_build_no_gradle_is_honest(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(gb, "local_toolchain_status",
                                   return_value={"java": True, "java_version": "17",
                                                 "gradle": False, "gradle_version": "",
                                                 "gradlew": False, "gradlew_path": ""}):
                out = gb.local_gradle_build(tmp)
            self.assertIn("Gradle pelam na", out)

    def test_local_build_gradlew_mocked_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            gradlew = Path(tmp) / "gradlew"
            gradlew.write_text("#!/bin/sh\n", encoding="utf-8")
            fake = mock.Mock(returncode=0, stdout="BUILD SUCCESSFUL",
                             stderr="")
            tc = {"java": True, "java_version": "17",
                  "gradle": False, "gradle_version": "",
                  "gradlew": True, "gradlew_path": str(gradlew)}
            with mock.patch.object(gb, "local_toolchain_status",
                                   return_value=tc), \
                 mock.patch.object(gb.subprocess, "run",
                                   return_value=fake) as run:
                out = gb.local_gradle_build(tmp)
            self.assertIn("success", out)
            self.assertTrue(run.called)
            self.assertIn("gradlew", str(run.call_args[0][0][0]))

    def test_push_scaffold_mocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, _msg, _ = gb.write_android_scaffold(tmp)
            self.assertTrue(ok)
            pushed = []

            def _push(token, owner, repo, path, content, message):
                pushed.append(path)
                return "✅ pushed"

            out = gb.push_scaffold_to_repo("o", "r", tmp, push_fn=_push)
            self.assertEqual(len(pushed), 6)
            self.assertIn("6 ta file push holo", out)

    def test_build_android_delegates_to_selfheal(self):
        with mock.patch("core.apk_selfheal.build_apk_selfheal",
                        return_value="mocked self-heal report") as sh:
            out = gb.build_android("o/r", "build-apk.yml")
        self.assertEqual(out, "mocked self-heal report")
        sh.assert_called_once_with("o/r", "build-apk.yml", ref="main")


class TestGradlePlugin(unittest.TestCase):
    def test_plugin_writes_only_without_repo(self):
        from plugins import gradle_build as plugin
        self.assertEqual(plugin.PLUGIN["name"], "gradle_build")
        with tempfile.TemporaryDirectory() as tmp:
            folder = str(Path(tmp) / "app1")
            out = plugin.run({"folder": folder, "package": "com.example.t",
                              "app_name": "T"})
            self.assertIn("scaffold likhlam", out)
            self.assertTrue((Path(folder) / "app" / "build.gradle.kts").is_file())

    def test_plugin_never_raises(self):
        from plugins import gradle_build as plugin
        self.assertIn("path dao", plugin.run({}))
        self.assertIn("pelam na", plugin.run({"folder": "/no/such/folder-xyz"}))


if __name__ == "__main__":
    unittest.main()
