"""tests/test_github_create_repo.py — github_create_repo (core/connectors.py).

Run from ~/workspace/mark-lvii:
    python3 tests/test_github_create_repo.py
    python3 -m unittest discover -s tests -v

Stdlib only. The HTTP layer (connectors._req) and the config read
(connectors._cfg) are monkeypatched — no network, no real token, and no
real repository is ever created. The fake token is distinctive so the
tests can also prove it never leaks into any returned string.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import connectors  # noqa: E402

_FAKE_TOKEN = "ghp_FAKESECRET1234567890"


class _Base(unittest.TestCase):
    def setUp(self):
        self._orig_req = connectors._req
        self._orig_cfg = connectors._cfg
        self.captured = {}

    def tearDown(self):
        connectors._req = self._orig_req
        connectors._cfg = self._orig_cfg

    def _with_token(self):
        connectors._cfg = lambda: {"github_token": _FAKE_TOKEN}  # noqa: E731

    def _fake_req(self, status, data, err=""):
        def _req(method, url, headers=None, params=None, payload=None,
                 files=None):
            self.captured["method"] = method
            self.captured["url"] = url
            self.captured["payload"] = payload
            self.captured["headers"] = headers or {}
            return status, data, err
        connectors._req = _req


class TestCreateRepoSuccess(_Base):
    def test_success_with_description(self):
        self._with_token()
        self._fake_req(201, {"full_name": "someone/my-new-repo",
                             "html_url": "https://github.com/someone/my-new-repo"})
        res = connectors.github_create_repo(None, "my-new-repo",
                                            False, "a test repo")
        self.assertTrue(res.startswith("✅"), res)
        self.assertIn("https://github.com/someone/my-new-repo", res)
        self.assertEqual(self.captured["method"], "POST")
        self.assertEqual(self.captured["url"],
                         "https://api.github.com/user/repos")
        self.assertEqual(self.captured["payload"]["name"], "my-new-repo")
        self.assertEqual(self.captured["payload"]["description"], "a test repo")
        self.assertFalse(self.captured["payload"]["private"])
        self.assertNotIn(_FAKE_TOKEN, res)

    def test_success_private_without_description(self):
        self._with_token()
        self._fake_req(201, {"full_name": "someone/secret",
                             "html_url": "https://github.com/someone/secret"})
        res = connectors.github_create_repo(None, "secret", True)
        self.assertTrue(res.startswith("✅"), res)
        self.assertTrue(self.captured["payload"]["private"])
        self.assertNotIn("description", self.captured["payload"])
        self.assertNotIn(_FAKE_TOKEN, res)

    def test_success_200_counts_too(self):
        self._with_token()
        self._fake_req(200, {"full_name": "someone/x",
                             "html_url": "https://github.com/someone/x"})
        res = connectors.github_create_repo(None, "x")
        self.assertTrue(res.startswith("✅"), res)


class TestCreateRepoErrors(_Base):
    def test_no_token(self):
        connectors._cfg = lambda: {}  # noqa: E731
        self._fake_req(201, {"full_name": "a/b",
                             "html_url": "https://github.com/a/b"})
        res = connectors.github_create_repo(None, "b")
        self.assertIn("token", res)
        self.assertNotIn(_FAKE_TOKEN, res)
        self.assertNotIn("url", self.captured)  # no HTTP call was made

    def test_empty_name(self):
        self._with_token()
        self._fake_req(201, {"full_name": "a/b",
                             "html_url": "https://github.com/a/b"})
        res = connectors.github_create_repo(None, "   ")
        self.assertIn("naam", res)
        self.assertNotIn("url", self.captured)

    def test_401_bad_token(self):
        self._with_token()
        self._fake_req(401, {"message": "Bad credentials"}, "Bad credentials")
        res = connectors.github_create_repo(None, "b")
        self.assertIn("401", res)
        self.assertIn("token", res)
        self.assertNotIn(_FAKE_TOKEN, res)

    def test_422_name_taken(self):
        self._with_token()
        self._fake_req(422, {
            "message": "Repository creation failed.",
            "errors": [{"resource": "Repository", "code": "custom",
                        "field": "name",
                        "message": "name already exists on this account"}]},
            "Repository creation failed.")
        res = connectors.github_create_repo(None, "taken-name")
        self.assertIn("422", res)
        self.assertIn("taken-name", res)
        self.assertIn("already", res)
        self.assertNotIn(_FAKE_TOKEN, res)

    def test_422_no_detail_still_plain(self):
        self._with_token()
        self._fake_req(422, {"message": "Repository creation failed."},
                       "Repository creation failed.")
        res = connectors.github_create_repo(None, "bad name!")
        self.assertIn("422", res)
        self.assertIn("bad name!", res)

    def test_network_error(self):
        self._with_token()
        self._fake_req(0, None, "network error: Connection refused")
        res = connectors.github_create_repo(None, "b")
        self.assertIn("network", res.lower())
        self.assertNotIn(_FAKE_TOKEN, res)

    def test_403_uses_generic_err_path(self):
        self._with_token()
        self._fake_req(403, {"message": "Resource not accessible by integration"},
                       "Resource not accessible by integration")
        res = connectors.github_create_repo(None, "b")
        self.assertIn("403", res)
        self.assertNotIn(_FAKE_TOKEN, res)


class TestCreateRepoToolWiring(unittest.TestCase):
    """The voice/text tool (main.py) must pass description through to the
    connector — a source-level guard so the wiring cannot silently rot."""

    def test_main_dispatch_passes_description(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, "main.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('args.get("description"', src)
        # The tool definition itself declares the description property.
        idx = src.find('"name": "github_create_repo"')
        self.assertGreater(idx, 0)
        block = src[idx:idx + 800]
        self.assertIn('"description": {"type": "STRING"', block)


if __name__ == "__main__":
    unittest.main(verbosity=2)
