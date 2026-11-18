"""tests/test_youtube_agent.py — 🎬 YOUTUBE AGENT: play routing
(HUD player first, then browser driver, then link), search reuse,
like/comment blocked honestly without a token, 401 handling, and the
video panel text. NEVER fakes a like or a comment.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only. Network + config + browser driver are mocked.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import youtube_agent as ya  # noqa: E402


class TestExtractId(unittest.TestCase):
    def test_watch_url(self):
        self.assertEqual(ya._extract_video_id(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ")

    def test_short_url(self):
        self.assertEqual(ya._extract_video_id("https://youtu.be/dQw4w9WgXcQ"),
                         "dQw4w9WgXcQ")

    def test_plain_id(self):
        self.assertEqual(ya._extract_video_id("dQw4w9WgXcQ"), "dQw4w9WgXcQ")

    def test_query_has_no_id(self):
        self.assertEqual(ya._extract_video_id("Sheru video"), "")


class TestPlayRouting(unittest.TestCase):
    def setUp(self):
        self.store = {}
        self._p1 = mock.patch(
            "core.youtube_agent.get_plugin_config",
            lambda ns: dict(self.store.get(ns) or {}))
        self._p2 = mock.patch(
            "core.youtube_agent.save_plugin_config",
            lambda ns, v: self.store.__setitem__(ns, dict(v)))
        self._p1.start()
        self._p2.start()

    def tearDown(self):
        self._p1.stop()
        self._p2.stop()

    def test_direct_url_plays_on_hud_first(self):
        player = mock.Mock()
        with mock.patch("core.youtube_agent.resolve_stream_url",
                        return_value="https://stream.example/v.mp4"):
            out = ya.play_video("https://youtu.be/dQw4w9WgXcQ", player=player)
        player.show_video.assert_called_once()
        args = player.show_video.call_args[0]
        self.assertEqual(args[0], "https://stream.example/v.mp4")
        self.assertIn("nijer video screen", out)
        cur = ya.current_video()
        self.assertEqual(cur["video_id"], "dQw4w9WgXcQ")
        self.assertIn("HUD", cur["source"])

    def test_search_then_play(self):
        player = mock.Mock()
        hits = [{"id": "abc123def45", "title": "Sheru Song",
                 "url": "https://www.youtube.com/watch?v=abc123def45"}]
        with mock.patch("core.youtube_agent.search_videos",
                        return_value=(hits, "")), \
                mock.patch("core.youtube_agent.resolve_stream_url",
                           return_value=""):
            out = ya.play_video("Sheru video", player=player)
        self.assertIn("Sheru Song", out)
        player.show_video.assert_called_once()

    def test_no_browser_just_link(self):
        with mock.patch("core.browser_driver.ensure_driver",
                        return_value=(None, "", "not ready")):
            out = ya.play_video("https://youtu.be/dQw4w9WgXcQ")
        self.assertIn("https://www.youtube.com/watch?v=dQw4w9WgXcQ", out)
        self.assertIn("link-ta", out)

    def test_browser_driver_used_when_no_player(self):
        driver = mock.Mock()
        driver.navigate.return_value = (True, "ok")
        with mock.patch("core.browser_driver.ensure_driver",
                        return_value=(driver, "playwright", "ok")):
            out = ya.play_video("https://youtu.be/dQw4w9WgXcQ")
        driver.navigate.assert_called_once_with(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertIn("Chrome-e khullam", out)

    def test_empty_query(self):
        self.assertIn("Ki chalabo", ya.play_video(""))

    def test_search_fails_honest(self):
        with mock.patch("core.youtube_agent.search_videos",
                        return_value=([], "YouTube API key set kora nei")):
            out = ya.play_video("Sheru video")
        self.assertIn("API key", out)


class TestLikeComment(unittest.TestCase):
    def test_like_without_token_honest(self):
        with mock.patch("core.youtube_agent._oauth_token", return_value=""):
            out = ya.like_video("dQw4w9WgXcQ")
        self.assertIn("Like holo na", out)
        self.assertIn("login/token lagbe", out.lower())
        self.assertNotIn("Like dilam", out)

    def test_comment_without_token_honest(self):
        with mock.patch("core.youtube_agent._oauth_token", return_value=""):
            out = ya.comment_video("dQw4w9WgXcQ", "Sheru best!")
        self.assertIn("Comment holo na", out)
        self.assertIn("login/token lagbe", out.lower())
        self.assertNotIn("Comment dilam", out)

    def test_like_401_expired(self):
        with mock.patch("core.youtube_agent._oauth_token",
                        return_value="expired-token"), \
                mock.patch("core.youtube_agent._api_post",
                           return_value=(401, {}, "Bad credentials")):
            out = ya.like_video("dQw4w9WgXcQ")
        self.assertIn("EXPIRED (401)", out)
        self.assertIn("Fake like deini", out)

    def test_like_success_204(self):
        with mock.patch("core.youtube_agent._oauth_token",
                        return_value="good-token"), \
                mock.patch("core.youtube_agent._api_post",
                           return_value=(204, {}, "")):
            out = ya.like_video("dQw4w9WgXcQ")
        self.assertIn("Like dilam", out)
        self.assertIn("youtu.be/dQw4w9WgXcQ", out)

    def test_comment_success_201(self):
        with mock.patch("core.youtube_agent._oauth_token",
                        return_value="good-token"), \
                mock.patch("core.youtube_agent._api_post",
                           return_value=(201, {"id": "Ugxyz"}, "")):
            out = ya.comment_video("dQw4w9WgXcQ", "Sheru best!")
        self.assertIn("Comment dilam", out)
        self.assertIn("Ugxyz", out)

    def test_comment_needs_text(self):
        self.assertIn("Comment-ta ki", ya.comment_video("dQw4w9WgXcQ", ""))

    def test_like_needs_video(self):
        self.assertIn("Konta video", ya.like_video(""))


class TestPanel(unittest.TestCase):
    def test_panel_shows_current_video(self):
        store = {}
        with mock.patch("core.youtube_agent.get_plugin_config",
                        lambda ns: dict(store.get(ns) or {})), \
                mock.patch("core.youtube_agent.save_plugin_config",
                           lambda ns, v: store.__setitem__(ns, dict(v))), \
                mock.patch("core.connectors._token", return_value=""):
            ya._set_current("dQw4w9WgXcQ", "Sheru Song",
                            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                            "HUD video screen")
            txt = ya.video_panel_text()
        self.assertIn("Sheru Song", txt)
        self.assertIn("dQw4w9WgXcQ", txt)
        self.assertIn("HUD", txt)

    def test_panel_empty(self):
        store = {}
        with mock.patch("core.youtube_agent.get_plugin_config",
                        lambda ns: dict(store.get(ns) or {})), \
                mock.patch("core.youtube_agent.save_plugin_config",
                           lambda ns, v: store.__setitem__(ns, dict(v))), \
                mock.patch("core.connectors._token", return_value=""):
            txt = ya.video_panel_text()
        self.assertIn("Ekhon kichu cholche na", txt)
        self.assertIn("token nei", txt)

    def test_status_mentions_token_state(self):
        with mock.patch("core.youtube_agent._oauth_token", return_value=""):
            txt = ya.youtube_status()
        self.assertIn("token", txt.lower())


if __name__ == "__main__":
    unittest.main()
