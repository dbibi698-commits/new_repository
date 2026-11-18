"""tests/test_new_agent_cards.py — 🤖 NEW AGENT CARDS (32 total): Data
Analyzer, Report Writer, Email Sender, File Organizer.

Run from ~/workspace/mark-lvii:
    python3 -m unittest discover -s tests -v

Stdlib only. Real network/SMTP is never used; the email test injects a
fake SMTP class. File moves happen only inside temp dirs.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import agent_cards as ac  # noqa: E402
from core import data_analyzer as da  # noqa: E402
from core import email_sender as em  # noqa: E402
from core import file_organizer as fo  # noqa: E402
from core import report_writer as rw  # noqa: E402

NEW_CARDS = ("data_analyzer", "report_writer", "email_sender",
             "file_organizer")


def _real_tools() -> set[str]:
    """Every real tool/plugin/connector-function name in this codebase
    (same derivation as tests/test_agent_cards_update.py)."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    tools: set[str] = set()
    for path in (root / "plugins").glob("*.py"):
        if path.name.startswith("_"):
            continue
        m = re.search(r'"name":\s*"([^"]+)"', path.read_text(errors="ignore"))
        if m:
            tools.add(m.group(1))
    for path in (root / "actions").glob("*.py"):
        m = re.search(r'"name":\s*"([^"]+)"', path.read_text(errors="ignore"))
        if m:
            tools.add(m.group(1))
    tools.update(re.findall(r'"name":\s*"([a-z_0-9]+)"',
                            (root / "main.py").read_text(errors="ignore")))
    conn = (root / "core" / "connectors.py").read_text(errors="ignore")
    for m in re.findall(r"^def ([a-z_0-9]+)\(", conn, re.M):
        if (m.startswith(("github_", "whatsapp_", "youtube_", "facebook_",
                          "instagram_", "drive_"))
                or m == "connectors_status"):
            tools.add(m)
    return tools


class TestCardCountAndMapping(unittest.TestCase):
    def test_32_cards(self):
        self.assertEqual(ac.count(), 32)
        self.assertEqual(len(ac.CARD_DEFS), 32)

    def test_ids_unique_and_new_cards_present(self):
        ids = [c["id"] for c in ac.CARD_DEFS]
        self.assertEqual(len(ids), len(set(ids)))
        for cid in NEW_CARDS:
            self.assertIn(cid, ids)

    def test_every_card_maps_to_real_tool_and_action(self):
        tools = _real_tools()
        for card in ac.CARD_DEFS:
            with self.subTest(card=card["id"]):
                self.assertIn(card["tool"], tools,
                              f"tool missing: {card['tool']}")
                self.assertIn(card["action"], ac._ACTIONS,
                              f"action missing: {card['action']}")
                self.assertTrue(card["name"] and card["job"])

    def test_run_card_with_injected_actions(self):
        fakes = {ac.card_def(cid)["action"]: (lambda c=cid: f"fake {c}")
                 for cid in NEW_CARDS}
        for cid in NEW_CARDS:
            out = ac.run_card(cid, actions=fakes)
            self.assertEqual(out, f"fake {cid}")


class TestDataAnalyzer(unittest.TestCase):
    _CSV = "name,age,city\nA,10,Dhaka\nB,20,Chittagong\nC,30,Dhaka\n"

    def test_csv_text_stats(self):
        res = da.analyze_csv_text(self._CSV)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["rows"], 3)
        self.assertEqual(res["cols"], ["name", "age", "city"])
        age = res["summary"]["age"]
        self.assertEqual(age["type"], "number")
        self.assertAlmostEqual(age["mean"], 20.0)
        self.assertEqual(age["min"], 10)
        self.assertEqual(age["max"], 30)

    def test_csv_text_top_values(self):
        res = da.analyze_csv_text(self._CSV)
        city = res["summary"]["city"]
        self.assertEqual(city["type"], "text")
        self.assertEqual(city["top"][0], "Dhaka (2)")

    def test_analyze_text_summary(self):
        text = da.analyze_text(da.analyze_csv_text(self._CSV))
        self.assertIn("3 row", text)
        self.assertIn("20", text)

    def test_analyze_file_real_csv(self):
        folder = tempfile.mkdtemp(prefix="mark-da-")
        try:
            path = os.path.join(folder, "sample.csv")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self._CSV)
            res = da.analyze_file(path)
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["rows"], 3)
            self.assertEqual(res["file"], "sample.csv")
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_analyze_file_missing(self):
        res = da.analyze_file("/tmp/mark-no-such-file.csv")
        self.assertFalse(res["ok"])
        self.assertIn("pelam na", res["error"])

    def test_analyze_empty(self):
        res = da.analyze_csv_text("")
        self.assertFalse(res["ok"])


class TestReportWriter(unittest.TestCase):
    def test_writes_real_file(self):
        folder = tempfile.mkdtemp(prefix="mark-rw-")
        try:
            res = rw.write_report("Weekly sales summary",
                                  extra="Sales barlo.", base_dir=folder)
            self.assertTrue(res["ok"], res)
            self.assertTrue(os.path.exists(res["path"]))
            text = open(res["path"], encoding="utf-8").read()
            self.assertIn("Weekly sales summary", text)
            self.assertIn("Sales barlo.", text)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_empty_topic_rejected(self):
        res = rw.write_report("", base_dir=tempfile.mkdtemp())
        self.assertFalse(res["ok"])
        self.assertIn("topic dao", res["error"])


class TestEmailSender(unittest.TestCase):
    def test_honest_without_smtp(self):
        ok, msg = em.send_email("someone@example.com", "Hi", "Hello",
                                store={})
        self.assertFalse(ok)
        self.assertIn("SMTP set kora nei", msg)

    def test_bad_address_rejected(self):
        ok, msg = em.send_email("not-an-email", store={})
        self.assertFalse(ok)
        self.assertIn("email address dao", msg)

    def test_send_with_fake_smtp(self):
        sent = {}

        class _FakeSMTP:
            def __init__(self, host, port, timeout=30):
                sent["host"] = host
                sent["port"] = port

            def starttls(self):
                sent["tls"] = True

            def login(self, user, pw):
                sent["user"] = user

            def send_message(self, msg):
                sent["to"] = msg["To"]
                sent["subject"] = msg["Subject"]

            def quit(self):
                sent["quit"] = True

        settings = {"smtp_host": "smtp.gmail.com", "smtp_port": 587,
                    "smtp_user": "jan@example.com",
                    "smtp_pass": "app-password", "use_tls": True}
        ok, msg = em.send_email("friend@example.com", "Hello", "Body text",
                                settings=settings, smtp_class=_FakeSMTP)
        self.assertTrue(ok, msg)
        self.assertEqual(sent["host"], "smtp.gmail.com")
        self.assertEqual(sent["to"], "friend@example.com")
        self.assertTrue(sent.get("tls"))
        self.assertTrue(sent.get("quit"))

    def test_describe_without_config(self):
        text = em.describe(store={})
        self.assertIn("SMTP set kora nei", text)


class TestFileOrganizer(unittest.TestCase):
    def _make_folder(self):
        folder = tempfile.mkdtemp(prefix="mark-fo-")
        for name in ("pic.jpg", "doc.pdf", "song.mp3", "clip.mp4",
                     "arc.zip", "code.py", "note.txt", "weird.xyz"):
            with open(os.path.join(folder, name), "w") as fh:
                fh.write("x")
        return folder

    def test_dry_run_preview_only(self):
        folder = self._make_folder()
        try:
            res = fo.organize_folder(folder, dry_run=True)
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["moved"], 0)
            self.assertEqual(res["planned"], 8)
            # Nothing moved yet.
            self.assertTrue(os.path.exists(os.path.join(folder, "pic.jpg")))
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_real_move_sorts_by_type(self):
        folder = self._make_folder()
        try:
            res = fo.organize_folder(folder, dry_run=False)
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["moved"], 8)
            self.assertTrue(os.path.exists(
                os.path.join(folder, "Images", "pic.jpg")))
            self.assertTrue(os.path.exists(
                os.path.join(folder, "Documents", "doc.pdf")))
            self.assertTrue(os.path.exists(
                os.path.join(folder, "Audio", "song.mp3")))
            self.assertTrue(os.path.exists(
                os.path.join(folder, "Code", "code.py")))
            self.assertTrue(os.path.exists(
                os.path.join(folder, "Other", "weird.xyz")))
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_missing_folder(self):
        res = fo.organize_folder("/tmp/mark-no-such-folder-xyz")
        self.assertFalse(res["ok"])
        self.assertIn("pelam na", res["error"])


if __name__ == "__main__":
    unittest.main()
