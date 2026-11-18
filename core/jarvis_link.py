"""
core/jarvis_link.py — "📱 Jarvis Link": QR pairing between this PC (Mark-LVII)
and the user's phone Jarvis app, through the Jarvis backend relay.

It speaks the SAME protocol the JarvisPC app and the phone app (v1.6.0+)
already speak, so the phone pairs with Mark exactly like it pairs with a PC:

    POST /api/pair/request {pc_id, pc_name, os}  -> {pair_code, expires_in}
    GET  /api/pair/status?pc_id&code             -> {paired, install_id, pc_token}
    POST /api/pc/heartbeat {pc_id, token, ...}   -> {paired, install_id}
    POST /api/relay/send {from, from_id, to, kind, text, token?}
    GET  /api/relay/inbox?who=<mark_id>          -> {messages} (DESTRUCTIVE read)
    POST /api/relay/file {from, from_id, to, name, data}   (<= 2 MB)
    GET  /api/relay/file/<id>                    -> file bytes
    POST /api/pc/screen {pc_id, token, image}    -> {ok}

QR payload (the phone app v1.8.2 parses it):

    jarvis-pair://<mark_id>/<6-digit code>[/<32-hex secret>]

The secret is only included when this machine can actually do AES-GCM
(`cryptography` is a declared dependency). The phone then encrypts its text
commands — PBKDF2-HmacSHA256, 100k rounds, salt "jarvis-e2e-v1", AES-256-GCM,
"ENC1:" + base64(iv + ciphertext+tag) — and this module decrypts them the
same way. Without a secret the phone sends plaintext and everything still
works. Results back to the phone stay plaintext by design, so the phone's
/remote page and Telegram can still show them.

Everything here is best-effort and lazy: no backend, no pairing, no problem —
Mark runs exactly as before. All network runs on background threads; nothing
here ever blocks the UI or the Live session. The module's top level is
standard library only, so importing it can never break startup.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import random
import string
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://jarvis-backend-8ray.onrender.com"
APP_VERSION = "Mark-LVII"
_E2E_SALT = b"jarvis-e2e-v1"
_E2E_ITERATIONS = 100_000
_CODE_REFRESH_MS = 9 * 60 * 1000 + 30 * 1000  # backend reuses a code for 10 min
_HEARTBEAT_SECS = 30
_INBOX_SECS = 2

# cryptography (AES-GCM) is a declared dependency, but the link must survive
# an install that never ran `pip install -r requirements.txt` in full.
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM
    _HAS_AES = True
except Exception:
    _AESGCM = None
    _HAS_AES = False


def _base_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _config_path() -> Path:
    return _base_dir() / "config" / "jarvis_link.json"


def _random_hex(n_bytes: int = 16) -> str:
    return "".join(random.choice("0123456789abcdef") for _ in range(n_bytes * 2))


def _derive_key(secret: str) -> bytes:
    """PBKDF2-HmacSHA256 — byte-for-byte the phone app's RelayCrypto."""
    return hashlib.pbkdf2_hmac(
        "sha256", secret.encode("utf-8"), _E2E_SALT, _E2E_ITERATIONS, dklen=32
    )


def _json_payload(text: str) -> dict:
    """Parse a relay payload: JSON object wins, anything else becomes
    {"spec"/"text": raw}. Never raises."""
    try:
        data = json.loads(str(text or "").strip())
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


class JarvisLink:
    """One link between this machine and the phone Jarvis app."""

    def __init__(self, on_text=None, say=None, log=None, tools_fn=None):
        # on_text(text) -> str : blocking ask — feed text to the Live session
        #   and return the assistant's reply (main.py: _link_ask).
        # say(text)     : speak a short line through the session (plugin_say).
        # log(msg)      : write a line to the activity log.
        # tools_fn()    : list of tool names for the sync reply.
        self.on_text = on_text
        self.say = say or (lambda _t: None)
        self.log = log or print
        self.tools_fn = tools_fn or (lambda: [])
        self._cfg = self._load_cfg()
        self.mark_id = self._cfg.get("mark_id") or ("mark-" + _random_hex(4))
        self.pc_token = self._cfg.get("pc_token", "")
        self.install_id = self._cfg.get("install_id", "")
        self.paired = bool(self._cfg.get("paired") and self.pc_token and self.install_id)
        self.e2e_secret = self._cfg.get("e2e_secret", "")
        if _HAS_AES and not self.e2e_secret:
            self.e2e_secret = _random_hex(16)
        self._save_cfg()
        self._pair_code = ""
        self._pair_code_at = 0.0
        self._running = False
        self._threads: list[threading.Thread] = []
        # Result waiter: the phone answers a PC-initiated text/file command
        # with kind="result" in our inbox. Tools that need the phone's reply
        # (phone_say, phone_open_app, ...) wait on this event instead of
        # polling the log. One waiter at a time — tools run sequentially.
        self._result_event = threading.Event()
        self._last_result = ""
        self._result_lock = threading.Lock()
        # Latest phone screenshot fetched by fetch_phone_screen() — the
        # dashboard serves it at /api/phone-screen (+ /phone-screen page).
        self._last_phone_screen_at = ""
        # Last time ANY message arrived from the phone (ISO). The 24h
        # status box + Tasks panel use it to show the phone's background
        # state (alive / silent for X minutes). "" = never heard from it.
        self.last_phone_seen = ""

    # ------------------------------------------------------------ config

    def _load_cfg(self) -> dict:
        try:
            p = _config_path()
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_cfg(self) -> None:
        try:
            p = _config_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({
                "mark_id": self.mark_id,
                "pc_token": self.pc_token,
                "install_id": self.install_id,
                "paired": self.paired,
                "e2e_secret": self.e2e_secret,
            }, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------ E2E

    @property
    def e2e_on(self) -> bool:
        """True when the phone will encrypt its commands to us."""
        return _HAS_AES and bool(self.e2e_secret)

    @e2e_on.setter
    def e2e_on(self, value: bool) -> None:
        # False clears the secret (plaintext mode). True cannot invent a
        # secret — it only keeps the existing one, so e2e_on stays False
        # until a real pair secret is set.
        if not value:
            self.e2e_secret = ""

    def _e2e_encrypt(self, plain: str) -> str:
        if not self.e2e_on:
            return plain
        try:
            key = _derive_key(self.e2e_secret)
            iv = os.urandom(12)
            ct = _AESGCM(key).encrypt(iv, plain.encode("utf-8"), None)
            return "ENC1:" + base64.b64encode(iv + ct).decode("ascii")
        except Exception:
            return plain

    def _e2e_decrypt(self, s: str) -> str:
        if not s.startswith("ENC1:"):
            return s
        if not self.e2e_on:
            return s
        try:
            raw = base64.b64decode(s[5:])
            if len(raw) <= 12:
                return s
            iv, ct = raw[:12], raw[12:]
            key = _derive_key(self.e2e_secret)
            return _AESGCM(key).decrypt(iv, ct, None).decode("utf-8")
        except Exception:
            return s

    # ------------------------------------------------------------ HTTP

    def _post(self, path: str, body: dict, timeout: int = 10) -> dict | None:
        try:
            req = urllib.request.Request(
                BASE_URL + path,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            return None

    def _get(self, path: str, timeout: int = 10) -> dict | None:
        try:
            with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            return None

    def _get_bytes(self, path: str, timeout: int = 20) -> bytes | None:
        try:
            with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as r:
                return r.read()
        except Exception:
            return None

    # ------------------------------------------------------------ pairing

    def qr_payload(self) -> str:
        """The string the phone scans. Asks for a fresh code when needed."""
        now_ms = time.time() * 1000
        if not self._pair_code or (now_ms - self._pair_code_at) > _CODE_REFRESH_MS:
            r = self._post("/api/pair/request", {
                "pc_id": self.mark_id,
                "pc_name": f"Mark-LVII ({platform.node() or platform.system()})",
                "os": f"{platform.system()} {platform.release()}",
            })
            code = (r or {}).get("pair_code", "")
            if code:
                self._pair_code = code
                self._pair_code_at = now_ms
        if not self._pair_code:
            return ""
        payload = f"jarvis-pair://{self.mark_id}/{self._pair_code}"
        if self.e2e_on:
            payload += f"/{self.e2e_secret}"
        return payload

    def qr_image(self, size: int = 280):
        """PIL image of the pairing QR, or None (qrcode missing / no code)."""
        payload = self.qr_payload()
        if not payload:
            return None
        try:
            import qrcode
            qr = qrcode.QRCode(
                box_size=10, border=2,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
            )
            qr.add_data(payload)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            return img.resize((size, size))
        except Exception:
            return None

    def status_text(self) -> str:
        if self.paired:
            e2e = "🔒 E2E ON" if self.e2e_on else "plaintext"
            return (f"📱 Jarvis Link: ✅ Paired — phone: {self.install_id[:8]}… "
                    f"• {e2e} • Mark ID: {self.mark_id}")
        if self._pair_code:
            return (f"📱 Jarvis Link: QR dekhiye phone diye scan koro — "
                    f"code: {self._pair_code} • Mark ID: {self.mark_id}")
        return (f"📱 Jarvis Link: phone pair kora nei — JARVIS LINK button chaple "
                f"QR asbe. Mark ID: {self.mark_id}")

    def status_dict(self) -> dict:
        return {
            "paired": self.paired,
            "mark_id": self.mark_id,
            "install_id": self.install_id,
            "pair_code": self._pair_code,
            "e2e": self.e2e_on,
            "version": APP_VERSION,
            "last_phone_seen": self.last_phone_seen,
        }

    def send_text(self, text: str) -> bool:
        """Send a plain text message to the phone (E2E when on).
        Used by auto-tasks (TASK_SCHEDULE::) and other PC->phone sends."""
        return self.send_to_phone("text", text)

    def refresh_code(self) -> str:
        self._pair_code = ""
        self._pair_code_at = 0.0
        return self.qr_payload()

    def unpair(self) -> None:
        self._post("/api/pair/unpair", {"pc_id": self.mark_id})
        self.paired = False
        self.pc_token = ""
        self.install_id = ""
        self._pair_code = ""
        # Fresh secret next time, so an old QR can never pair again.
        self.e2e_secret = _random_hex(16) if _HAS_AES else ""
        self._save_cfg()

    # ------------------------------------------------------------ relay out

    def send_to_phone(self, kind: str, text: str, audio_b64: str | None = None) -> bool:
        if not self.paired:
            return False
        body = {
            "from": "pc", "from_id": self.mark_id,
            "to": self.install_id, "kind": kind,
            "text": self._e2e_encrypt(text) if kind == "text" else text,
            "token": self.pc_token,
        }
        if audio_b64:
            body["audio"] = audio_b64
        r = self._post("/api/relay/send", body)
        return bool(r and r.get("ok"))

    def send_result(self, text: str) -> bool:
        return self.send_to_phone("result", text)

    def wait_result(self, timeout: float = 90.0) -> str:
        """Wait for the phone's next kind="result" reply ("" on timeout)."""
        if self._result_event.wait(timeout):
            with self._result_lock:
                out = self._last_result
            self._result_event.clear()
            return out
        return ""

    def send_and_wait_result(self, text: str, timeout: float = 90.0) -> str:
        """Send a text command to the phone and wait for its reply.

        Used by phone_say (AI-to-AI talk) and the phone_* tools. Returns ""
        when the phone is not paired, the send fails, or no reply arrives
        in time — the caller turns that into a spoken sentence.
        """
        self._result_event.clear()
        with self._result_lock:
            self._last_result = ""
        if not self.send_to_phone("text", text):
            return ""
        return self.wait_result(timeout)

    def send_file_to_phone(self, path: str) -> str:
        """Send a local file to the phone over the relay (<= 2 MB, the same
        JSON the phone uses: POST /api/relay/file {from, from_id, to, name,
        data base64}). Waits up to 60 s for the phone's reply. Never raises."""
        if not self.paired:
            return "📱 Phone pair kora nei — age jarvis_link_qr diye QR scan koro."
        p = Path(path).expanduser()
        if not p.is_file():
            return f"File-ta khuje pelam na: {path}"
        try:
            size = p.stat().st_size
        except Exception:
            return f"File-ta porte parlam na: {path}"
        if size > 2 * 1024 * 1024:
            return (f"File-ta 2 MB-er boro ({size // (1024 * 1024)} MB) — relay diye "
                    "jabe na. Chhoto file dao, ba Drive diye pathao.")
        try:
            data = base64.b64encode(p.read_bytes()).decode("ascii")
        except Exception:
            return f"File-ta porte parlam na: {p.name}"
        self._result_event.clear()
        with self._result_lock:
            self._last_result = ""
        r = self._post("/api/relay/file", {
            "from": "pc", "from_id": self.mark_id,
            "to": self.install_id, "name": p.name, "data": data,
        }, timeout=30)
        if not (r and r.get("ok")):
            return "⚠️ Phone-e file pathate parlam na — phone online ache kina dekho."
        reply = self.wait_result(60.0)
        return reply or f"📁 Phone-e pathano holo: {p.name}"

    def phone_screen_file(self) -> Path:
        """Where the latest phone screenshot is saved on this PC."""
        return _base_dir() / "memory" / "phone_screen.jpg"

    def fetch_phone_screen(self, timeout: float = 30.0) -> str:
        """Ask the phone for a fresh screenshot and save it locally.

        Flow: kind="screen_req" -> phone screenshots (Accessibility ON
        lagbe) -> POST /api/screenshot -> phone replies kind="result" ->
        we GET /api/phone/screen?pc_id&token and save the JPEG to
        memory/phone_screen.jpg (dashboard: /api/phone-screen).

        Honest limit: ekta still image per request — live video na. Phone
        prottek bar notun ekta chhobi pathay; dashboard page-ta 4 sec-e
        refresh kore, tai slideshow-er moto dekhay. Never raises.
        """
        if not self.paired:
            return "📱 Phone pair kora nei — age jarvis_link_qr diye QR scan koro."
        before = self._get("/api/phone/screen?pc_id="
                           + urllib.parse.quote(self.mark_id)
                           + "&token=" + urllib.parse.quote(self.pc_token))
        before_at = (before or {}).get("at", "") or ""
        self._result_event.clear()
        with self._result_lock:
            self._last_result = ""
        if not self.send_to_phone("screen_req", ""):
            return "⚠️ Phone-e screen request pathate parlam na — pair thik ache kina dekho."
        reply = self.wait_result(timeout)
        if not reply:
            return ("⚠️ Phone theke 30 sec-e kono uttor elo na — phone-e Jarvis "
                    "khola ache kina dekho, tarpor abar bolo.")
        if "Accessibility" in reply:
            return reply
        if "hoyeche" not in reply and "pathano" not in reply:
            return reply
        # The phone uploads BEFORE it replies, so the image is usually
        # already there — poll briefly for a FRESH one (mtime newer than
        # the request) so we never hand back a stale screenshot. First
        # fetch ever: any image counts (nothing stale exists locally yet).
        had_previous = self.phone_screen_file().is_file()
        deadline = time.time() + 15
        while time.time() < deadline:
            shot = self._get("/api/phone/screen?pc_id="
                             + urllib.parse.quote(self.mark_id)
                             + "&token=" + urllib.parse.quote(self.pc_token),
                             timeout=10)
            if shot and shot.get("image"):
                at = shot.get("at", "") or ""
                if not at or at > before_at or not had_previous:
                    try:
                        data = base64.b64decode(shot["image"])
                        p = self.phone_screen_file()
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_bytes(data)
                        self._last_phone_screen_at = at
                        return ("📱 Phone-er screen pelam — dashboard-e /phone-screen "
                                "khulle dekhte parbe. (Notun still image — live video na, "
                                "prottek refresh-e notun chhobi ashe.)")
                    except Exception:
                        return "⚠️ Screenshot download holo, kintu PC-te save korte parlam na."
            time.sleep(2)
        return ("⚠️ Phone bollo screen pathiyeche, kintu backend-e notun image "
                "pelam na — abar try koro.")

    def pc_screen_file(self) -> Path:
        """Where the latest PC screenshot is saved on this machine."""
        return _base_dir() / "memory" / "pc_screen.jpg"

    def capture_pc_screen(self) -> str:
        """Capture THIS PC's own screen with mss and save it to
        memory/pc_screen.jpg (dashboard: /api/pc-screen). Returns the path
        as a string, or "" when the capture failed. Never raises.

        The same mss helper the phone uses when it asks for our screen
        (kind="screen_req" -> _capture_screen_b64) — no duplicate capture
        code: this writes the JPEG to disk, that one returns base64.
        """
        try:
            import io
            import mss
            from PIL import Image
            with mss.mss() as sct:
                shot = sct.grab(sct.monitors[1])
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            img.thumbnail((1280, 1280))
            p = self.pc_screen_file()
            p.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(p), format="JPEG", quality=80)
            return str(p)
        except Exception:
            # Fallback: PIL ImageGrab (Windows/macOS) — same JPEG, same path.
            try:
                from PIL import ImageGrab
                img = ImageGrab.grab()
                img.thumbnail((1280, 1280))
                p = self.pc_screen_file()
                p.parent.mkdir(parents=True, exist_ok=True)
                img.save(str(p), format="JPEG", quality=80)
                return str(p)
            except Exception:
                return ""

    def request_phone_location(self, timeout: float = 30.0) -> str:
        """Ask the phone for its current location and store the fix.

        HONEST LIMIT (checked 2026-11-17): the phone relay has NO dedicated
        location request — PcRelay.kt handles text / voice / tts /
        screen_req / result / clip / file only, and the backend relay
        allowlist rejects any other kind with 400. So this tries, in order:
          1. kind="location_req" — the dedicated path, for a future phone
             app update that handles it (today the backend 400s it, so the
             send returns False and we move on);
          2. the REAL existing path — a text command the phone's own AI
             answers with its get_location tool (ToolExecutor.kt), whose
             reply carries "Lat …, Lng …" — parsed and stored.
        Returns a short human string. When no coordinates arrive, the
        honest string "location unavailable — phone app update needed"
        (no fix is stored, no coordinates are ever faked). Never raises.
        """
        if not self.paired:
            return "location unavailable — phone pair kora nei."
        # 1. Dedicated kind (future phone update).
        try:
            self._result_event.clear()
            with self._result_lock:
                self._last_result = ""
            if self.send_to_phone("location_req", ""):
                reply = self.wait_result(timeout)
                fix = None
                try:
                    from core.phone_location import parse_location_text, record_fix
                    parsed = parse_location_text(reply or "")
                    if parsed:
                        fix = record_fix(parsed["lat"], parsed["lon"])
                except Exception:
                    fix = None
                if fix:
                    return (f"📍 Phone location: {fix['lat']}, {fix['lon']} "
                            f"({fix.get('at') or ''}) — "
                            f"https://www.google.com/maps?q={fix['lat']},{fix['lon']}")
                if reply:
                    return ("location unavailable — phone location pathay ni "
                            f"({str(reply)[:120]})")
        except Exception:
            pass
        # 2. Real existing path: phone AI + its get_location tool.
        try:
            reply = self.send_and_wait_result(
                "get_location — amar current location-ta dao: Lat, Lng ar address",
                timeout=timeout)
            if not reply:
                return "location unavailable — phone app update needed"
            try:
                from core.phone_location import parse_location_text, record_fix
                parsed = parse_location_text(reply)
            except Exception:
                parsed = None
            if parsed:
                fix = record_fix(parsed["lat"], parsed["lon"])
                if fix:
                    return (f"📍 Phone location: {fix['lat']}, {fix['lon']} "
                            f"({fix.get('at') or ''}) — "
                            f"https://www.google.com/maps?q={fix['lat']},{fix['lon']}")
            if "permission" in reply.lower() or "Location permission" in reply:
                return ("location unavailable — phone-e Location permission "
                        "ON koro (Settings > Permissions > Location).")
            if "pelam na" in reply or "GPS" in reply:
                return ("location unavailable — phone-er GPS ON ache kina "
                        "dekho, tarpor abar bolo.")
            return "location unavailable — phone app update needed"
        except Exception:
            return "location unavailable — phone app update needed"

    # ------------------------------------------------------------ loops

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        for target in (self._pair_loop, self._heartbeat_loop, self._inbox_loop):
            t = threading.Thread(target=target, daemon=True,
                                 name=f"jarvis-link-{target.__name__}")
            t.start()
            self._threads.append(t)
        self.log("[Jarvis Link] Phone pairing chalu — JARVIS LINK button-e QR dekhabe.")

    def stop(self) -> None:
        self._running = False

    def _pair_loop(self) -> None:
        while self._running:
            try:
                if not self.paired:
                    if not self._pair_code:
                        self.qr_payload()  # request one code, then poll status
                    if self._pair_code:
                        r = self._get(
                            "/api/pair/status?pc_id=" + urllib.parse.quote(self.mark_id)
                            + "&code=" + urllib.parse.quote(self._pair_code))
                        if r and r.get("paired"):
                            self.pc_token = r.get("pc_token", "")
                            self.install_id = r.get("install_id", "")
                            self.paired = bool(self.pc_token and self.install_id)
                            self._save_cfg()
                            if self.paired:
                                self.log(f"[Jarvis Link] ✅ Phone paired: {self.install_id[:8]}…")
                                self.say("Phone connected. Your mobile Jarvis can reach me now.")
                time.sleep(2)
            except Exception:
                time.sleep(2)

    def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                if self.paired:
                    r = self._post("/api/pc/heartbeat", {
                        "pc_id": self.mark_id, "token": self.pc_token,
                        "pc_name": f"Mark-LVII ({platform.node() or platform.system()})",
                        "os": f"{platform.system()} {platform.release()}",
                    })
                    if r is not None and not r.get("paired"):
                        self.paired = False
                        self._save_cfg()
                time.sleep(_HEARTBEAT_SECS)
            except Exception:
                time.sleep(_HEARTBEAT_SECS)

    def _inbox_loop(self) -> None:
        while self._running:
            try:
                if self.paired:
                    self._poll_once()
                time.sleep(_INBOX_SECS)
            except Exception:
                time.sleep(_INBOX_SECS)

    def _poll_once(self) -> None:
        # A PC reading its own inbox MUST pass its pc_token — the backend
        # 403s a token-less read ("bad pc_token or not paired").
        r = self._get("/api/relay/inbox?who=" + urllib.parse.quote(self.mark_id)
                      + "&token=" + urllib.parse.quote(self.pc_token))
        msgs = (r or {}).get("messages") or []
        for m in msgs:
            try:
                self._handle_message(m)
            except Exception as e:
                print(f"[Jarvis Link] message handle error: {e!r}")

    def _handle_location_update(self, text: str) -> None:
        """Record one phone GPS fix (JSON or 'Lat: .., Lng: ..' text).
        Never raises; never fakes a fix."""
        try:
            from core import phone_location as _pl
            fix = _pl.parse_location_text(str(text or ""))
            if fix is None:
                try:
                    data = _json_payload(str(text or ""))
                    lat = data.get("lat", data.get("latitude"))
                    lon = data.get("lng", data.get("lon",
                                   data.get("longitude")))
                    if lat is not None and lon is not None:
                        fix = {"lat": float(lat), "lon": float(lon),
                               "accuracy": data.get("accuracy")}
                except Exception:
                    fix = None
            if fix is None:
                self.log("[Jarvis Link] 📍 Location update bujhlam na.")
                return
            stored = _pl.record_fix(fix.get("lat"), fix.get("lon"),
                                    fix.get("accuracy"))
            if stored:
                self.log(f"[Jarvis Link] 📍 Phone location: "
                         f"{stored['lat']:.5f}, {stored['lon']:.5f}")
        except Exception as e:
            self.log(f"[Jarvis Link] location handle error: {e!r}")

    # ------------------------------------------------------------ inbox in

    def _handle_message(self, msg: dict) -> None:
        kind = msg.get("kind", "")
        text = msg.get("text", "") or ""
        audio_file = msg.get("audio_file", "") or ""
        # Any message from the phone = the phone is alive. The 24h status
        # box + Tasks panel read last_phone_seen.
        try:
            from datetime import datetime as _dt
            self.last_phone_seen = _dt.now().isoformat(timespec="seconds")
        except Exception:
            pass
        if kind == "location_update":
            # Dedicated kind from the phone (v1.9.9): text = JSON
            # {lat, lng, accuracy} or "Lat: .., Lng: ..".
            self._handle_location_update(text)
            return
        if kind == "text":
            plain = self._e2e_decrypt(text)
            # Phone reports (text-prefix fallbacks — the reliable path):
            # LOCATION_UPDATE:: — the phone's GPS fix; TASK_REPORT:: — a
            # scheduled task the phone ran while the PC was off. Neither
            # needs a reply; both are recorded, not answered.
            try:
                if plain.startswith("LOCATION_UPDATE::"):
                    self._handle_location_update(
                        plain[len("LOCATION_UPDATE::"):])
                    return
                if plain.startswith("TASK_REPORT::"):
                    from core import auto_tasks as _at
                    self.log("[Jarvis Link] " + _at.handle_task_report(
                        plain[len("TASK_REPORT::"):]))
                    return
            except Exception as e:
                self.log(f"[Jarvis Link] phone report handle error: {e!r}")
                return
            # Phone-er Commander orders + prefixed fallbacks — the text
            # path is always allowed by the relay, so these work even if
            # the backend allowlist has no dedicated kind yet. Everything
            # goes through the Commander (core/commander.issue_order):
            # the Commander plans it and delegates to the worker.
            try:
                from core import commander as _cmd
                if _cmd.is_commander_request(plain):
                    self.send_result(_cmd.handle_phone_request(plain))
                    return
                from core import software_builder as _sb
                if _sb.is_phone_request(plain):
                    payload = _json_payload(plain[len("SOFTWARE_BUILD::"):])
                    spec = str(payload.get("spec") or "") or plain
                    res = _cmd.issue_order(spec, intent="software_build",
                                           payload=payload)
                    self.send_result(res.get("result_text", ""))
                    return
                from core import python_run as _pr
                if _pr.is_phone_request(plain):
                    code = plain[len("PYTHON_RUN::"):]
                    res = _cmd.issue_order(plain, intent="python_run",
                                           payload={"code": code})
                    self.send_result(res.get("result_text", ""))
                    return
            except Exception as e:
                self.send_result(f"Phone-er command chalate parlam na: {e}")
                return
            self.log(f"[Jarvis Link] 📱 Phone: {plain[:200]}")
            reply = ""
            if self.on_text is not None:
                try:
                    reply = self.on_text(plain) or ""
                except Exception as e:
                    reply = f"⚠️ Command-ta cholate parlam na: {e}"
            if not reply:
                reply = "✅ Bujhechi — kintu uttor dite parlam na (session connect hoy ni)."
            self.send_result(reply)
        elif kind == "python_run":
            # Dedicated kind from the phone (needs the backend relay
            # allowlist to accept it; the PYTHON_RUN:: text prefix above
            # is the fallback when it does not). text = the code, plaintext.
            # Runs through the Commander — Builder worker executes it.
            try:
                from core import commander as _cmd
                res = _cmd.issue_order(text, intent="python_run",
                                       payload={"code": text})
                self.send_result(res.get("result_text", ""))
            except Exception as e:
                self.send_result(f"Phone-er Python code chalate parlam na: {e}")
        elif kind == "software_build":
            # Dedicated kind: text = JSON {spec, kind, deploy, repo} or a
            # plain spec. Commander → Software Builder → localhost + link.
            try:
                from core import commander as _cmd
                payload = _json_payload(text)
                spec = str(payload.get("spec") or "") or text
                res = _cmd.issue_order(spec, intent="software_build",
                                       payload=payload)
                self.send_result(res.get("result_text", ""))
            except Exception as e:
                self.send_result(f"Phone-er software build korte parlam na: {e}")
        elif kind == "apk_build":
            # Dedicated kind: text = JSON {repo, workflow} or "owner/repo".
            try:
                from core import commander as _cmd
                payload = _json_payload(text)
                repo = str(payload.get("repo") or "") or text
                res = _cmd.issue_order(repo, intent="apk_build",
                                       payload=payload)
                self.send_result(res.get("result_text", ""))
            except Exception as e:
                self.send_result(f"Phone-er APK build korte parlam na: {e}")
        elif kind == "render_deploy":
            # Dedicated kind: text = JSON {service_id} or a service name.
            try:
                from core import commander as _cmd
                payload = _json_payload(text)
                order = str(payload.get("service_id") or "") or text or "render deploy"
                res = _cmd.issue_order(order, intent="render_deploy",
                                       payload=payload)
                self.send_result(res.get("result_text", ""))
            except Exception as e:
                self.send_result(f"Phone-er Render deploy korte parlam na: {e}")
        elif kind == "photo_edit":
            # Dedicated kind: text = JSON {photo, file_id, top_text, size}
            # or a photo path. Commander → Photo Editor → sheet PNG.
            # A file_id means the phone sent the photo as a relay file —
            # download it first, then edit the saved copy.
            try:
                from core import commander as _cmd
                payload = _json_payload(text)
                file_id = str(payload.get("file_id") or "")
                if file_id:
                    data = self._get_bytes("/api/relay/file/" + file_id)
                    if data:
                        folder = Path.home() / "Downloads" / "MarkLVII"
                        try:
                            folder.mkdir(parents=True, exist_ok=True)
                        except Exception:
                            pass
                        saved = folder / f"phone-photo-{file_id}.png"
                        try:
                            saved.write_bytes(data)
                            payload["photo"] = str(saved)
                        except Exception:
                            pass
                order = str(payload.get("photo") or "") or text
                res = _cmd.issue_order(order, intent="photo_edit",
                                       payload=payload)
                self.send_result(res.get("result_text", ""))
            except Exception as e:
                self.send_result(f"Phone-er photo edit korte parlam na: {e}")
        elif kind in ("voice", "tts"):
            if audio_file:
                data = self._get_bytes("/api/relay/audio/" + audio_file)
                if data:
                    self._play_wav(data)
                    if kind == "voice":
                        self.send_result("🔊 Voice note PC-te bajano hoyeche — voice command ekhono text-e pathao, Mark likhe uttor debe.")
                    return
            self.send_result("⚠️ Voice note-ta bajate parlam na.")
        elif kind == "screen_req":
            img_b64 = self._capture_screen_b64()
            if img_b64:
                r = self._post("/api/pc/screen", {
                    "pc_id": self.mark_id, "token": self.pc_token, "image": img_b64,
                })
                self.send_result("🖥️ PC-er screen phone-e pathano hoyeche."
                                 if (r and r.get("ok")) else "⚠️ PC screen upload hoy ni.")
            else:
                self.send_result("⚠️ PC screen nite parlam na.")
        elif kind == "sync_req":
            sync = {
                "app_version": APP_VERSION,
                "monitoring": False,
                "pc_control": True,
                "voice_call": False,
                "tools": self.tools_fn(),
                "agents": [],
                "e2e": self.e2e_on,
            }
            self.send_to_phone("sync", json.dumps(sync))
        elif kind == "clip":
            try:
                import pyperclip
                pyperclip.copy(text)
                self.send_result("📋 Clipboard PC-te bosano hoyeche — ekhane paste korte paro.")
            except Exception:
                self.send_result("⚠️ Clipboard set korte parlam na.")
        elif kind == "file":
            file_id = msg.get("file_id", "")
            size = msg.get("size", 0)
            if file_id:
                data = self._get_bytes("/api/relay/file/" + file_id)
                if data is not None:
                    name = "".join(c for c in text if c.isalnum() or c in "._- ")[:80] or "file"
                    folder = Path.home() / "Downloads" / "MarkLVII"
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / name).write_bytes(data)
                    self.send_result(f"📁 File pelam: {name} ({len(data)} bytes) — Downloads/MarkLVII-te rakha holo.")
                    return
            self.send_result("⚠️ File-ta download korte parlam na.")
        elif kind == "voice_call":
            self.send_result("📞 Live voice call ei link-e ekhono ashe ni — voice note pathale PC-te bajbe, ar text command-e sob kaj hobe.")
        elif kind == "voice_end":
            pass
        elif kind == "result":
            self.log(f"[Jarvis Link] 📱 Phone uttor: {text[:200]}")
            with self._result_lock:
                self._last_result = text
            self._result_event.set()
        elif kind == "notif":
            self.log(f"[Jarvis Link] 🔔 {text[:200]}")

    # ------------------------------------------------------------ helpers

    def _play_wav(self, data: bytes) -> None:
        try:
            import io
            import wave
            import numpy as np
            import sounddevice as sd
            with wave.open(io.BytesIO(data), "rb") as w:
                frames = w.readframes(w.getnframes())
                sr = w.getframerate()
                ch = w.getnchannels()
                sw = w.getsampwidth()
            audio = np.frombuffer(frames, dtype=np.int16 if sw == 2 else np.int8)
            if ch == 2:
                audio = audio.reshape(-1, 2)
            sd.play(audio, samplerate=sr, blocking=False)
        except Exception as e:
            print(f"[Jarvis Link] wav play failed: {e!r}")

    def _capture_screen_b64(self) -> str | None:
        try:
            import io
            import mss
            from PIL import Image
            with mss.mss() as sct:
                shot = sct.grab(sct.monitors[1])
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            img.thumbnail((1024, 1024))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            return base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            return None


# Module-level singleton, like the dashboard: main.py attaches it once.
LINK: JarvisLink | None = None


def attach(on_text=None, say=None, log=None, tools_fn=None) -> JarvisLink:
    """Create (or return) the link and start its background loops."""
    global LINK
    if LINK is None:
        LINK = JarvisLink(on_text=on_text, say=say, log=log, tools_fn=tools_fn)
    else:
        if on_text is not None:
            LINK.on_text = on_text
        if say is not None:
            LINK.say = say
        if log is not None:
            LINK.log = log
        if tools_fn is not None:
            LINK.tools_fn = tools_fn
    LINK.start()
    return LINK


def status() -> dict:
    """For the dashboard / tools: {} when the link was never attached."""
    if LINK is None:
        return {"paired": False, "running": False}
    d = LINK.status_dict()
    d["running"] = LINK._running
    return d


def latest_phone_screen() -> dict:
    """{'path': str, 'at': str} of the latest saved phone screenshot, or {}.

    For the dashboard: /api/phone-screen serves the file, /phone-screen
    shows it live-ish (auto-refresh). Empty when no screenshot was ever
    fetched — ask Mark for phone_screen first.
    """
    if LINK is None:
        return {}
    p = LINK.phone_screen_file()
    if not p.is_file():
        return {}
    return {"path": str(p), "at": LINK._last_phone_screen_at}
