"""tests/test_word_rule.py — 🚫 WORD RULE audit (2026-11-18, standing).

The word "extension" must NOT appear in ANY user-visible string — no
UI label, button, message, tool description, help text, card name, or
log line the user sees. This test scans every STRING LITERAL in the
scoped source files (via ast, so comments do not count) and fails on
the banned word.

Allowlist (functional references, never shown to the user):
  * "chrome-extension" in core/exe_package.py — the directory name in
    the EXE-exclusion list.
"""
import ast
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Source files whose user-visible strings are audited.
SCOPED = [
    "core/browser_driver.py",
    "core/browser_automation.py",
    "core/browser_control.py",
    "core/browser_flows.py",
    "core/browser_setup.py",
    "core/video_upload.py",
    "core/social_auto.py",
    "core/youtube_agent.py",
    "core/agent_cards.py",
    "core/reply_guard.py",
    "core/exe_package.py",
    "plugins/browser_advanced.py",
    "plugins/advanced_browser.py",
    "plugins/github_browser.py",
    "plugins/render_browser.py",
    "plugins/cat02_browser.py",
    "plugins/mouse_control.py",
    "plugins/hosting_deploy.py",
    "plugins/browser_setup.py",
    "main.py",
    "gui/overlays.py",
]

# (file, substring) pairs that may keep the word — functional only.
# The check strips these substrings from a literal first, then looks
# for the banned word in what is left.
ALLOW = {
    ("core/exe_package.py", "chrome-extension/"),
}

BANNED = re.compile(r"extension", re.IGNORECASE)


def _string_literals(path):
    """All string literal values in a file (ast — comments excluded)."""
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src, filename=path)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    out.append(part.value)
    return out


class TestWordRule(unittest.TestCase):
    def test_no_banned_word_in_user_visible_strings(self):
        violations = []
        for rel in SCOPED:
            path = os.path.join(ROOT, rel)
            self.assertTrue(os.path.exists(path), f"missing scoped file: {rel}")
            for literal in _string_literals(path):
                stripped = literal
                for (afile, sub) in ALLOW:
                    if afile == rel:
                        stripped = stripped.replace(sub, "")
                if BANNED.search(stripped):
                    violations.append(f"{rel}: {literal[:100]!r}")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_exe_package_excludes_chrome_extension_dir(self):
        from core import exe_package as _ep
        self.assertIn("chrome-extension/", _ep.EXCLUDES)
        self.assertTrue(_ep.is_excluded("chrome-extension/background.js"))
        self.assertTrue(_ep.is_excluded("chrome-extension/manifest.json"))
        self.assertTrue(_ep.is_excluded("chrome-extension"))
        self.assertFalse(_ep.is_excluded("core/browser_driver.py"))
        self.assertFalse(_ep.is_excluded("samples/browser_sample.py"))

    def test_exe_package_excludes_secrets(self):
        from core import exe_package as _ep
        self.assertTrue(_ep.is_excluded("config/api_keys.json"))
        self.assertTrue(_ep.is_excluded("config/jarvis_link.json"))
        self.assertTrue(_ep.is_excluded("python/python.exe"))
        files = _ep.package_files(ROOT)
        self.assertNotIn("chrome-extension/background.js", files)
        self.assertNotIn("config/api_keys.json", files)
        self.assertNotIn("config/jarvis_link.json", files)
        self.assertIn("core/browser_flows.py", files)
        self.assertIn("samples/browser_sample.py", files)
        self.assertIn("core/reply_guard.py", files)

    def test_rsync_exclude_args_cover_chrome_extension(self):
        from core import exe_package as _ep
        args = _ep.rsync_exclude_args()
        self.assertIn("--exclude=chrome-extension/", args)
        self.assertIn("--exclude=config/api_keys.json", args)


if __name__ == "__main__":
    unittest.main()
