"""tests/test_facebook_oauth.py — Facebook OAuth callback (dashboard/server.py).

Run from ~/workspace/mark-lvii:
    python3 tests/test_facebook_oauth.py
    python3 -m unittest discover -s tests -v

Stdlib + FastAPI only. The Graph API layer (server._fb_http_get) is
monkeypatched — no network, no real secrets. Fake tokens are distinctive so
the tests can also prove they never leak into error strings or the login
page. Route handlers are called directly off app.routes (they take only
query params, no Request object).
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("BROWSER_TOKEN", "test-token-for-tests")

import dashboard.server as server  # noqa: E402

_FAKE_APP_ID = "123456789012345"
_FAKE_SECRET = "FAKESECRET-abcdef-123456"
_FAKE_USER_TOKEN = "FAKEUSERTOKEN-aaa-bbb-ccc"
_FAKE_PAGE_TOKEN = "FAKEPAGETOKEN-xxx-yyy-zzz"
_FAKE_PAGE_ID = "987654321098765"


def _fake_http(status, data):
    captured = []

    def _get(url, params):
        captured.append((url, dict(params)))
        return status, data
    _get.captured = captured
    return _get


class _Base(unittest.TestCase):
    def setUp(self):
        self._orig_http = server._fb_http_get
        self._orig_env = {k: os.environ.get(k) for k in
                          ("FACEBOOK_APP_ID", "FACEBOOK_APP_SECRET")}
        os.environ["FACEBOOK_APP_ID"] = _FAKE_APP_ID
        os.environ["FACEBOOK_APP_SECRET"] = _FAKE_SECRET

    def tearDown(self):
        server._fb_http_get = self._orig_http
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _endpoint(self, path):
        srv = server.DashboardServer()
        for route in srv.app.routes:
            if getattr(route, "path", None) == path:
                return route.endpoint
        self.fail(f"route {path} not found")


class TestLoginUrl(_Base):
    def test_login_url_shape(self):
        url = server._fb_login_url(_FAKE_APP_ID)
        self.assertIn("facebook.com/v18.0/dialog/oauth", url)
        self.assertIn("client_id=" + _FAKE_APP_ID, url)
        self.assertIn("response_type=code", url)
        # redirect_uri is the exact Render callback URL (url-encoded)
        self.assertIn("redirect_uri=https%3A%2F%2Fmark-lvii-dashboard"
                      ".onrender.com%2Fapi%2Ffacebook%2Fcallback", url)
        # scope carries all three permissions
        self.assertIn("pages_manage_posts", url)
        self.assertIn("pages_read_engagement", url)
        self.assertIn("pages_show_list", url)

    def test_login_url_never_carries_secret(self):
        url = server._fb_login_url(_FAKE_APP_ID)
        self.assertNotIn(_FAKE_SECRET, url)

    def test_callback_url_constant(self):
        self.assertEqual(
            server._FB_CALLBACK_URL,
            "https://mark-lvii-dashboard.onrender.com/api/facebook/callback")


class TestLoginPage(_Base):
    def test_no_app_id_shows_setup_note(self):
        os.environ.pop("FACEBOOK_APP_ID", None)
        html = server._fb_login_html("")
        self.assertIn("FACEBOOK_APP_ID", html)
        self.assertIn("FACEBOOK_APP_SECRET", html)
        self.assertIn("Render", html)
        self.assertNotIn("dialog/oauth", html)

    def test_with_app_id_shows_button(self):
        html = server._fb_login_html(_FAKE_APP_ID)
        self.assertIn("Login with Facebook", html)
        self.assertIn("dialog/oauth", html)
        self.assertIn(server._FB_CALLBACK_URL, html)
        self.assertNotIn(_FAKE_SECRET, html)


class TestExchange(_Base):
    def test_success(self):
        fake = _fake_http(200, {"access_token": _FAKE_USER_TOKEN,
                                "token_type": "bearer"})
        server._fb_http_get = fake
        tok, err = server._fb_exchange_code("CODE123", _FAKE_APP_ID, _FAKE_SECRET)
        self.assertEqual(tok, _FAKE_USER_TOKEN)
        self.assertIsNone(err)
        url, params = fake.captured[0]
        self.assertIn("/oauth/access_token", url)
        self.assertEqual(params["client_id"], _FAKE_APP_ID)
        self.assertEqual(params["client_secret"], _FAKE_SECRET)
        self.assertEqual(params["redirect_uri"], server._FB_CALLBACK_URL)
        self.assertEqual(params["code"], "CODE123")

    def test_bad_secret_plain_words_no_leak(self):
        server._fb_http_get = _fake_http(400, {"error": {
            "message": "Invalid client secret", "code": 104}})
        tok, err = server._fb_exchange_code("CODE123", _FAKE_APP_ID, _FAKE_SECRET)
        self.assertIsNone(tok)
        self.assertIn("App Secret", err)
        self.assertNotIn(_FAKE_SECRET, err)

    def test_expired_code(self):
        server._fb_http_get = _fake_http(400, {"error": {
            "message": "This authorization code has expired.", "code": 100}})
        tok, err = server._fb_exchange_code("OLDCODE", _FAKE_APP_ID, _FAKE_SECRET)
        self.assertIsNone(tok)
        self.assertIn("expire", err)
        self.assertIn("abar", err.lower())

    def test_network_failure(self):
        server._fb_http_get = _fake_http(0, {"error": {"message": "boom"}})
        tok, err = server._fb_exchange_code("CODE123", _FAKE_APP_ID, _FAKE_SECRET)
        self.assertIsNone(tok)
        self.assertIn("holo na", err)


class TestListPages(_Base):
    def test_success(self):
        server._fb_http_get = _fake_http(200, {"data": [
            {"id": _FAKE_PAGE_ID, "name": "My Test Page",
             "access_token": _FAKE_PAGE_TOKEN}]})
        pages, err = server._fb_list_pages(_FAKE_USER_TOKEN)
        self.assertIsNone(err)
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["id"], _FAKE_PAGE_ID)
        self.assertEqual(pages[0]["name"], "My Test Page")
        self.assertEqual(pages[0]["token"], _FAKE_PAGE_TOKEN)

    def test_empty(self):
        server._fb_http_get = _fake_http(200, {"data": []})
        pages, err = server._fb_list_pages(_FAKE_USER_TOKEN)
        self.assertEqual(pages, [])
        self.assertIsNone(err)

    def test_unauthorized_plain_words(self):
        server._fb_http_get = _fake_http(401, {"error": {
            "message": "Session has expired", "code": 190}})
        pages, err = server._fb_list_pages("STALE")
        self.assertEqual(pages, [])
        self.assertIn("Abar Login", err)


class TestPagesHtml(_Base):
    def test_escapes_page_name(self):
        html = server._fb_pages_html([{
            "id": _FAKE_PAGE_ID, "name": "<script>alert(1)</script>",
            "token": _FAKE_PAGE_TOKEN}])
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn(_FAKE_PAGE_ID, html)
        self.assertIn("Copy token", html)
        self.assertIn("Copy ID", html)

    def test_error_page_escapes_message(self):
        html = server._fb_error_html("X", 'oops <b>"q"</b>')
        self.assertNotIn("<b>", html)
        self.assertIn("&lt;b&gt;", html)
        self.assertIn("/facebook/login", html)


class TestRoutes(_Base):
    def test_login_route_no_app_id(self):
        os.environ.pop("FACEBOOK_APP_ID", None)
        ep = self._endpoint("/facebook/login")
        resp = asyncio.run(ep())
        body = resp.body.decode()
        self.assertIn("FACEBOOK_APP_ID", body)
        self.assertNotIn("dialog/oauth", body)

    def test_login_route_with_app_id(self):
        ep = self._endpoint("/facebook/login")
        resp = asyncio.run(ep())
        body = resp.body.decode()
        self.assertIn("Login with Facebook", body)
        self.assertIn("dialog/oauth", body)

    def test_callback_denied(self):
        ep = self._endpoint("/api/facebook/callback")
        resp = asyncio.run(ep(error="access_denied",
                               error_description="The user denied your request"))
        body = resp.body.decode()
        self.assertIn("cancel", body)
        self.assertIn("user denied", body)
        self.assertNotIn(_FAKE_SECRET, body)

    def test_callback_no_code(self):
        ep = self._endpoint("/api/facebook/callback")
        resp = asyncio.run(ep())
        self.assertIn("kono code pelam na", resp.body.decode())

    def test_callback_missing_env(self):
        os.environ.pop("FACEBOOK_APP_ID", None)
        os.environ.pop("FACEBOOK_APP_SECRET", None)
        ep = self._endpoint("/api/facebook/callback")
        resp = asyncio.run(ep(code="CODE123"))
        self.assertIn("set kora nei", resp.body.decode())

    def test_callback_full_flow(self):
        calls = []

        def _get(url, params):
            calls.append(url)
            if "/oauth/access_token" in url:
                return 200, {"access_token": _FAKE_USER_TOKEN}
            if "/me/accounts" in url:
                return 200, {"data": [
                    {"id": _FAKE_PAGE_ID, "name": "My Test Page",
                     "access_token": _FAKE_PAGE_TOKEN}]}
            return 404, {}
        server._fb_http_get = _get
        ep = self._endpoint("/api/facebook/callback")
        resp = asyncio.run(ep(code="CODE123"))
        body = resp.body.decode()
        self.assertIn("My Test Page", body)
        self.assertIn(_FAKE_PAGE_ID, body)
        self.assertIn(_FAKE_PAGE_TOKEN, body)
        self.assertIn("Copy token", body)
        self.assertIn("facebook_page_token", body)
        self.assertIn("facebook_page_id", body)
        self.assertNotIn(_FAKE_SECRET, body)
        self.assertEqual(len(calls), 2)

    def test_callback_exchange_failure(self):
        server._fb_http_get = _fake_http(400, {"error": {
            "message": "Invalid client secret", "code": 104}})
        ep = self._endpoint("/api/facebook/callback")
        resp = asyncio.run(ep(code="CODE123"))
        body = resp.body.decode()
        self.assertIn("App Secret", body)
        self.assertNotIn(_FAKE_SECRET, body)

    def test_callback_no_pages(self):
        def _get(url, params):
            if "/oauth/access_token" in url:
                return 200, {"access_token": _FAKE_USER_TOKEN}
            return 200, {"data": []}
        server._fb_http_get = _get
        ep = self._endpoint("/api/facebook/callback")
        resp = asyncio.run(ep(code="CODE123"))
        self.assertIn("Kono Page pelam na", resp.body.decode())


if __name__ == "__main__":
    unittest.main(verbosity=2)
