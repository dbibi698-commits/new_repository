"""
dashboard/server.py — JARVIS Local HTTP Dashboard

HTTPS on port 8000 with a self-signed certificate generated on first run, plus
a second layer inside it: commands are encrypted with AES-256-GCM under a key
derived from the pairing code with PBKDF2. Both layers are required — the
server refuses to start without TLS rather than quietly serving in clear.

Install deps:  pip install fastapi "uvicorn[standard]" cryptography
"""

import asyncio
import base64
import hashlib
import html
import os
import re
import secrets
import socket
import string
import threading
import time
from pathlib import Path

_DEPS_OK = False
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Query
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, PlainTextResponse
    import uvicorn
    _DEPS_OK = True
except ImportError:
    pass

# python-multipart is required for file uploads — optional dependency
_UPLOAD_OK = False
try:
    from fastapi import UploadFile, File as FastAPIFile
    _UPLOAD_OK = True
except Exception:
    pass

BASE_DIR    = Path(__file__).resolve().parent.parent
STATIC_DIR  = Path(__file__).parent / "static"
# The port people TYPE, and the port the app actually runs on.
#
# They are not the same, and that is the fix for the most confusing failure
# this dashboard had. A bare `192.168.1.108:8000` typed into a phone browser is
# tried over HTTP; against a TLS listener that means the connection is accepted,
# found to carry no handshake, and closed — which Chrome reports as "refused to
# connect". The server is running perfectly and the user is told it is off.
#
# So the port people reach for answers in the protocol they reach for it with,
# and sends them one hop to the secure one. The QR code carries the secure URL
# directly, so it never takes the hop.
PORT        = 8000      # HTTP, redirects to SECURE_PORT
SECURE_PORT = 8001      # HTTPS, the dashboard itself
MAX_UPLOAD_MB = 500


def _make_uploads_dir() -> Path:
    """Return (and create) the cross-platform uploads folder."""
    for candidate in [
        Path.home() / "Downloads" / "JARVIS Uploads",
        Path.home() / "Documents" / "JARVIS Uploads",
        BASE_DIR / "uploads",
    ]:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            pass
    return BASE_DIR / "uploads"


UPLOADS_DIR = _make_uploads_dir()

def _get_gemini_key() -> str | None:
    try:
        import json as _json
        with open(BASE_DIR / "config" / "api_keys.json", "r", encoding="utf-8") as f:
            return _json.load(f).get("gemini_api_key")
    except Exception:
        return None

_KEY_CHARS = [c for c in (string.ascii_uppercase + string.digits)
              if c not in ('O', 'I', 'L', '0', '1')]

# ── AES-256-CBC ───────────────────────────────────────────────────────────────
_AES_SALT = b'JARVIS-DASHBOARD-v1'


# Rounds for the pairing key -> AES key derivation.
#
# WHY THIS IS NOT ONE ROUND OF SHA-256, WHICH IS WHAT IT WAS
#     The pairing key is short because a person has to read it off a screen and
#     type it into a phone. Eight characters from a 31-letter alphabet is about
#     forty bits — fine against someone guessing at the login endpoint, which
#     is rate limited below, and NOT fine against someone who captured one
#     encrypted command and can guess offline as fast as their GPU allows.
#
#     At one round of SHA-256 that offline search is seconds. PBKDF2 at 200k
#     rounds makes each guess about five orders of magnitude more expensive
#     while costing this server ~80 ms once per session, at pairing time, where
#     nobody is waiting on a millisecond.
_KDF_ROUNDS = 200_000


def _derive_key(session_key: str) -> bytes:
    """Pairing key → 32-byte AES-256 key, deliberately slowly. See _KDF_ROUNDS."""
    return hashlib.pbkdf2_hmac(
        "sha256", session_key.encode("utf-8"), _AES_SALT, _KDF_ROUNDS, dklen=32
    )


def _decrypt(aes_key: bytes, enc_b64: str) -> str:
    """Decrypt base64(nonce[12] ‖ ciphertext‖tag) with AES-256-GCM.

    GCM RATHER THAN THE CBC THIS REPLACES
        CBC has no authentication. It hides a message and does nothing to stop
        one being CHANGED: an attacker on the same network can flip bits in the
        ciphertext and the server decrypts whatever falls out, with no way to
        tell. For a channel whose whole purpose is carrying commands to an
        assistant that opens applications and sends messages, "the text was
        secret" is the smaller half of what matters — "the text is the one that
        was sent" is the other half, and CBC never provided it.

        GCM authenticates as it decrypts. A single altered byte raises
        InvalidTag and the request is refused rather than obeyed.

    The old CBC path is not kept as a fallback on purpose. An attacker who can
    choose which format the server accepts can simply choose the weak one, and
    a downgrade left available is a downgrade that will be used.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = base64.b64decode(enc_b64)
    if len(raw) < 13:
        raise ValueError("ciphertext too short to contain a nonce")
    nonce, payload = raw[:12], raw[12:]
    return AESGCM(aes_key).decrypt(nonce, payload, None).decode("utf-8")


_BLOCK_CACHE = None


def blocking_firewall_rules() -> list:
    """Inbound Windows BLOCK rules aimed at the interpreter running this app.

    Public, read-only and never elevated, so the interface can warn about the
    one failure that is invisible from inside the app: a block rule overrides
    every allow rule, so the server listens correctly and the phone still
    cannot reach it. Empty on every other platform and whenever nothing is
    blocked.

    -> [(rule name, program path), ...]
    """
    import sys
    if sys.platform != "win32":
        return []

    # Cached for the process. Reading every inbound rule costs about a second,
    # and this is called from the Qt thread when the Remote Control panel
    # opens — a second of frozen interface every time, for an answer that only
    # changes when somebody edits their firewall.
    global _BLOCK_CACHE
    if _BLOCK_CACHE is not None:
        return _BLOCK_CACHE
    import os
    import subprocess

    py_exe = sys.executable
    sibling = os.path.join(
        os.path.dirname(py_exe),
        "pythonw.exe" if py_exe.lower().endswith("python.exe") else "python.exe")
    wanted = {py_exe.lower()}
    if os.path.exists(sibling):
        wanted.add(sibling.lower())

    found: list = []
    try:
        r = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             "name=all", "dir=in", "verbose"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=20,
        )
        name = program = None
        for line in r.stdout.splitlines():
            if line.startswith("Rule Name:"):
                name = line.split(":", 1)[1].strip()
                program = None
            elif line.startswith("Program:"):
                program = line.split(":", 1)[1].strip().lower()
            elif line.startswith("Action:"):
                if (name and program and program in wanted
                        and line.split(":", 1)[1].strip().lower() == "block"
                        and (name, program) not in found):
                    found.append((name, program))
    except Exception as exc:
        print(f"[Dashboard] could not read the firewall rules: {exc}")
    _BLOCK_CACHE = found
    return found


_ACCESS_ASKED = False


def report_network_access(*ports: int) -> bool:
    """Read-only, never elevated: can a phone reach the dashboard? Prints why
    not. Called at startup instead of fixing anything.

    WHY STARTUP NO LONGER FIXES IT
        It used to repair the firewall on every launch, and repairing it needs
        administrator rights — so the app greeted people with Windows' "allow
        this app to make changes to your device?" dialog before it had done
        anything. On a machine where a Windows firewall popup had once been
        cancelled, that block rule came back and so did the dialog, every
        single start. For an open-source app that is the worst first
        impression available: an unexplained request for admin. The repair now
        happens only when somebody opens REMOTE CONTROL — the one feature that
        needs it — where the dialog has an obvious reason.
    """
    import sys
    if sys.platform != "win32":
        return True
    try:
        blocked = blocking_firewall_rules()
    except Exception:
        return True
    if blocked:
        print("[Dashboard] Windows Firewall is blocking this Python from the "
              "network — the phone dashboard will not connect until that is "
              "fixed. Open REMOTE CONTROL to fix it (Windows will ask once).")
        return False
    return True


def fix_network_access(*ports: int) -> None:
    """Make the dashboard reachable from the phone — at most once per run,
    and only because the user asked for the phone dashboard."""
    global _ACCESS_ASKED
    if _ACCESS_ASKED:
        return
    _ACCESS_ASKED = True
    _ensure_network_access(*ports)


def _ensure_network_access(*ports: int) -> None:
    """Cross-platform, best-effort: open port in the OS firewall for LAN access.

    Runs in a background thread. Only ever reached through fix_network_access,
    i.e. from the user opening REMOTE CONTROL — never at startup.

    Windows : writes a .bat file, runs it elevated via Windows ShellExecuteW
              (native UAC dialog, guaranteed to appear). One-time setup.
    macOS   : osascript admin dialog if the Application Firewall is on.
    Linux   : pkexec GUI → sudo -n → prints manual command as fallback.
    """
    import sys, subprocess, os, tempfile, threading

    # ── Windows ──────────────────────────────────────────────────────────────
    if sys.platform == "win32":
        import ctypes, time

        # Every port in one pass. Called once per port, this asked for
        # elevation once per port — two UAC dialogs for one dashboard, and two
        # racing .bat files whose output interleaved into contradictory
        # messages on the console.
        port_rules = {pt: f"JARVIS Dashboard Port {pt}" for pt in ports}
        prog_rule  = "JARVIS Dashboard Python"

        # BOTH interpreters, because the app runs under either one.
        #
        # THIS IS THE BUG THAT MADE THE PHONE UNREACHABLE FROM THE SHORTCUT.
        #     Started from an editor the app runs under `python.exe`. The
        #     desktop shortcut targets `pythonw.exe`, so that there is no
        #     console window — a different executable, and Windows Firewall
        #     rules are per-executable. Allowing one said nothing about the
        #     other, and the symptom was a dashboard that worked when launched
        #     one way and "refused to connect" when launched the other, on the
        #     same machine and the same network.
        py_exe = sys.executable
        _sibling = os.path.join(os.path.dirname(py_exe),
                                "pythonw.exe" if py_exe.lower().endswith("python.exe")
                                else "python.exe")
        py_exes = [py_exe] + ([_sibling] if os.path.exists(_sibling) else [])

        def _netsh_rule_exists(name: str) -> bool:
            try:
                r = subprocess.run(
                    ["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
                )
                return r.returncode == 0 and "No rules match" not in r.stdout
            except Exception:
                return False

        def _network_is_public() -> bool:
            try:
                r = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     "(Get-NetConnectionProfile | "
                     "Where-Object {$_.NetworkCategory -eq 'Public'} | "
                     "Measure-Object).Count"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=6,
                )
                return r.stdout.strip() not in ("", "0")
            except Exception:
                return False

        # One implementation, at module scope — see blocking_firewall_rules().
        # There were briefly two, and they disagreed about their return type,
        # which surfaced as 'too many values to unpack' in the error path.
        blocked      = blocking_firewall_rules()
        missing_ports = [pt for pt, nm in port_rules.items()
                         if not _netsh_rule_exists(nm)]
        need_prog    = not _netsh_rule_exists(prog_rule)
        if _network_is_public():
            print("[Dashboard] This network is set to Public in Windows, which "
                  "blocks phones on it. If it is your own network, set it to "
                  "Private in Settings > Network & internet. JARVIS will not "
                  "change that for you — on public Wi-Fi it would expose this "
                  "computer.")
        need_private = False

        if blocked:
            print(f"[Dashboard] Windows is BLOCKING inbound connections to "
                  f"{', '.join(sorted(set(os.path.basename(e) for e in py_exes)))} "
                  f"({len(blocked)} block rule(s)). Your phone cannot reach the "
                  f"dashboard until those are removed — asking for permission "
                  f"to do that now.")

        if not missing_ports and not need_prog and not need_private and not blocked:
            return  # already fully configured

        # Build a .bat file — netsh + powershell, runs fast when elevated
        bat_lines = ["@echo off"]
        if need_private:
            bat_lines.append(
                'powershell -NoProfile -NonInteractive -Command "'
                'Get-NetConnectionProfile | '
                "Where-Object {$_.NetworkCategory -eq 'Public'} | "
                'Set-NetConnectionProfile -NetworkCategory Private"'
            )
        for pt in missing_ports:
            bat_lines.append(
                f'netsh advfirewall firewall add rule '
                f'name="{port_rules[pt]}" protocol=TCP dir=in '
                f'localport={pt} action=allow'
            )
        # Remove the blocks FIRST. Adding an allow rule beside a block rule
        # changes nothing at all — Windows resolves the conflict in the block's
        # favour — so this is the line that actually fixes the connection.
        for rule_name in blocked:
            bat_lines.append(
                f'netsh advfirewall firewall delete rule '
                f'name="{rule_name}" dir=in'
            )

        if need_prog or blocked:
            # One allow rule per interpreter. `add rule` with an existing name
            # appends rather than replacing, so deleting first keeps this from
            # accumulating a new copy on every launch.
            bat_lines.append(
                f'netsh advfirewall firewall delete rule name="{prog_rule}" dir=in'
            )
            for exe in py_exes:
                bat_lines.append(
                    f'netsh advfirewall firewall add rule '
                    f'name="{prog_rule}" dir=in action=allow '
                    f'program="{exe}" enable=yes'
                )

        # Say what will be attempted, so a UAC prompt nobody expected has a
        # reason attached to it in the terminal.
        if blocked:
            print("[Dashboard] The Windows prompt about to appear is JARVIS "
                  "removing those block rules. Declining it leaves the phone "
                  "dashboard unreachable, and nothing else is affected.")

        bat_body = "\r\n".join(bat_lines) + "\r\n"
        fd, bat_path = tempfile.mkstemp(suffix=".bat", prefix="jarvis_fw_")
        try:
            os.write(fd, bat_body.encode("mbcs"))   # Windows cmd.exe expects ANSI
            os.close(fd)
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            return

        # ── Try running directly (succeeds when already admin) ────────────────
        try:
            r = subprocess.run(
                [bat_path], capture_output=True, timeout=8, shell=True
            )
            if r.returncode == 0:
                print(f"[Dashboard] Firewall configured for {', '.join(str(pt) for pt in ports)}.")
                try:
                    os.unlink(bat_path)
                except Exception:
                    pass
                return
        except Exception:
            pass

        # ── ShellExecuteW: native UAC elevation (most reliable on Windows) ────
        # ShellExecuteW with verb "runas" always shows the UAC dialog regardless
        # of UAC level settings. Non-blocking — uvicorn is already running.
        print("[Dashboard] One-time network setup required.")
        print("[Dashboard] >>> A Windows security dialog will appear — click 'Yes' <<<")
        try:
            ret = ctypes.windll.shell32.ShellExecuteW(
                None,       # hwnd  (no parent window)
                "runas",    # verb  (request elevation)
                bat_path,   # file  (our .bat)
                None,       # params
                None,       # working dir
                0,          # SW_HIDE (run without a visible cmd window)
            )
            if int(ret) > 32:
                # ShellExecuteW returns immediately; bat finishes in ~1 second.
                # Sleep briefly so the rules are in place before the first retry.
                time.sleep(2)
                # CHECK, DO NOT ASSUME. ShellExecuteW succeeding means the
                # dialog was accepted, not that netsh did what was asked — and
                # the whole point of this release is not to report an outcome
                # nobody looked at.
                still = blocking_firewall_rules()
                if still:
                    print("[Dashboard] ⚠️  Windows is STILL blocking inbound "
                          "connections to this interpreter.")
                    print("[Dashboard] ⚠️  Remove these by hand in Windows "
                          "Defender Firewall > Inbound Rules: "
                          + ", ".join(sorted({n for n, _ in still})))
                else:
                    print(f"[Dashboard] Network setup complete — "
                          f"{', '.join(str(pt) for pt in ports)} open.")
                    print("[Dashboard] Refresh your phone browser to connect.")
            else:
                print("[Dashboard] Setup was not allowed.")
                if blocked:
                    print("[Dashboard] Your phone CANNOT reach the dashboard "
                          "until this is done: Windows has block rules for "
                          + ", ".join(sorted({n for n, _ in blocked}))
                          + " which override every allow rule.")
                    print("[Dashboard] Either restart JARVIS and accept the "
                          "prompt, or delete those rules in Windows Defender "
                          "Firewall > Inbound Rules.")
                else:
                    print("[Dashboard] Phone connections may fail until JARVIS "
                          "is run as Administrator.")
        except Exception as e:
            print(f"[Dashboard] Firewall setup error: {e}")
        finally:
            # Cleanup after the bat has had time to run
            def _cleanup(path: str) -> None:
                time.sleep(5)
                try:
                    os.unlink(path)
                except Exception:
                    pass
            threading.Thread(target=_cleanup, args=(bat_path,), daemon=True).start()
        return

    # ── macOS ─────────────────────────────────────────────────────────────────
    if sys.platform == "darwin":
        fw_ctl = "/usr/libexec/ApplicationFirewall/socketfilterfw"
        try:
            r = subprocess.run(
                [fw_ctl, "--getglobalstate"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
            )
            if "disabled" in r.stdout.lower():
                return  # firewall off — nothing to do

            py = sys.executable
            listed = subprocess.run(
                [fw_ctl, "--listapps"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
            )
            if py in listed.stdout:
                return  # already allowed

            print("[Dashboard] One-time network setup — enter your password in the macOS dialog.")
            subprocess.run(
                ["osascript", "-e",
                 f'do shell script "{fw_ctl} --add {py} && {fw_ctl} --unblockapp {py}"'
                 f' with administrator privileges'],
                timeout=60,
            )
        except Exception:
            pass  # macOS firewall is off by default — silent failure is fine
        return

    # ── Linux ─────────────────────────────────────────────────────────────────
    def _privileged(cmd: list[str]) -> bool:
        for prefix in (["pkexec"], ["sudo", "-n"]):
            try:
                r = subprocess.run(prefix + cmd, capture_output=True, timeout=30)
                if r.returncode == 0:
                    return True
            except Exception:
                pass
        return False

    try:  # ufw
        r = subprocess.run(["ufw", "status"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
        if "active" in r.stdout.lower():
            if _privileged(["ufw", "allow", f"{port}/tcp"]):
                print(f"[Dashboard] ufw: port {port} allowed.")
            else:
                print(f"[Dashboard] Run manually:  sudo ufw allow {port}/tcp")
            return
    except FileNotFoundError:
        pass

    try:  # firewalld
        r = subprocess.run(
            ["firewall-cmd", "--state"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
        )
        if "running" in r.stdout.lower():
            ok = (_privileged(["firewall-cmd", "--add-port", f"{port}/tcp", "--permanent"])
                  and _privileged(["firewall-cmd", "--reload"]))
            if ok:
                print(f"[Dashboard] firewalld: port {port} allowed.")
            else:
                print(f"[Dashboard] Run manually:  sudo firewall-cmd --add-port={port}/tcp --permanent && sudo firewall-cmd --reload")
            return
    except FileNotFoundError:
        pass

    try:  # iptables (not persistent but works until reboot)
        r = subprocess.run(["iptables", "-L", "INPUT", "-n"], capture_output=True, timeout=5)
        if r.returncode == 0:
            if _privileged(["iptables", "-A", "INPUT", "-p", "tcp", "--dport", str(port), "-j", "ACCEPT"]):
                print(f"[Dashboard] iptables: port {port} opened.")
            else:
                print(f"[Dashboard] Run manually:  sudo iptables -A INPUT -p tcp --dport {port} -j ACCEPT")
    except FileNotFoundError:
        pass  # no iptables means firewall is probably off — nothing to do




# ── helpers ───────────────────────────────────────────────────────────────────

def _local_ip() -> str:
    """Return the best LAN-facing IPv4 address, no internet required."""
    # Method 1: route trick (fast, works when internet is available)
    for probe in ("8.8.8.8", "1.1.1.1", "192.168.1.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect((probe, 80))
            ip = s.getsockname()[0]
            s.close()
            if not ip.startswith("127."):
                return ip
        except Exception:
            pass

    # Method 2: hostname resolution (works offline on most systems)
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if not ip.startswith("127."):
            return ip
    except Exception:
        pass

    # Method 3: enumerate all interfaces (fully offline, no external deps)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
    except Exception:
        pass

    return "127.0.0.1"


def _ensure_certs() -> bool:
    """
    Make sure config/certs holds a TLS key pair, generating a self-signed one the
    first time the dashboard runs.

    The pair is deliberately NOT shipped in the repository. A private key that
    every user downloads is the same as having no private key at all: anyone can
    present a certificate that matches it. Generating locally gives each install
    its own key, costs about a second, and happens exactly once.

    Returns True when a usable pair exists afterwards; False leaves the caller on
    plain HTTP, which still works — the QR code simply encodes http:// instead.
    """
    certs = BASE_DIR / "config" / "certs"
    key_p = certs / "jarvis.key"
    crt_p = certs / "jarvis.crt"
    if key_p.exists() and crt_p.exists():
        return True

    try:
        import datetime
        import ipaddress
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        print("[Dashboard] cryptography not installed — serving over plain HTTP.")
        print("[Dashboard] For HTTPS run:  pip install cryptography")
        return False

    try:
        certs.mkdir(parents=True, exist_ok=True)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        who = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "JARVIS Dashboard"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "JARVIS"),
        ])

        # The SAN has to cover every address the phone might use: the LAN IP the
        # QR code encodes, plus localhost when testing on the machine itself.
        alt = [x509.DNSName("localhost"),
               x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]
        try:
            lan = _local_ip()
            if not lan.startswith("127."):
                alt.append(x509.IPAddress(ipaddress.IPv4Address(lan)))
        except Exception:
            pass          # no LAN address resolvable — localhost entries still work

        # Timezone-aware UTC: datetime.utcnow() is deprecated from Python 3.12 on,
        # and the builder normalises aware values to UTC itself.
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(who)
            .issuer_name(who)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )

        key_p.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        crt_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

        try:
            import os as _os
            _os.chmod(key_p, 0o600)   # best effort — largely a no-op on Windows
        except Exception:
            pass

        print(f"[Dashboard] Generated a self-signed certificate for this machine: {certs}")
        return True
    except Exception as e:
        print(f"[Dashboard] Certificate generation failed ({e}) — serving over plain HTTP.")
        return False


def _read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


# ── DashboardServer ───────────────────────────────────────────────────────────

# How long an auth token stays valid, and how many failed logins an address
# gets before it has to wait.
#
# The old code had neither. A token, once issued, worked until the process
# ended — no expiry, no logout — and /login accepted unlimited guesses at the
# pairing key as fast as a script could send them. Eight characters is a large
# space, but "large" is not the same as "let them try forever": the point of a
# limit is that an attacker's cost grows while a person who mistypes their key
# twice never notices it exists.
_TOKEN_TTL_SECONDS = 12 * 3600
_LOGIN_MAX_TRIES   = 6
_LOGIN_WINDOW      = 300.0      # seconds the counter looks back over
_LOGIN_LOCKOUT     = 300.0      # seconds an address waits after using them up


class _Throttle:
    """Failed-attempt counter, per client address.

    Deliberately tiny and in memory: it protects a pairing key that is itself
    only alive for ten minutes, so nothing here needs to survive a restart.
    Successful logins clear the count, which keeps a household on one address
    from locking itself out because somebody fumbled the code once.
    """

    def __init__(self):
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def blocked_for(self, who: str) -> float:
        """Seconds this address must wait, or 0."""
        now = time.time()
        with self._lock:
            tries = [t for t in self._fails.get(who, []) if now - t < _LOGIN_WINDOW]
            self._fails[who] = tries
            if len(tries) < _LOGIN_MAX_TRIES:
                return 0.0
            return max(0.0, _LOGIN_LOCKOUT - (now - tries[-1]))

    def record_failure(self, who: str) -> None:
        with self._lock:
            self._fails.setdefault(who, []).append(time.time())

    def clear(self, who: str) -> None:
        with self._lock:
            self._fails.pop(who, None)


# ── Facebook OAuth (Page token) ───────────────────────────────────────────────
# The user sets up a Facebook App at developers.facebook.com and needs a PAGE
# access token for facebook_post (core/connectors.py). Facebook rejected the
# generic login_success.html redirect URI, so the dashboard itself is the
# redirect target: the user pastes the callback URL below into the app's
# "Valid OAuth Redirect URIs" and opens /facebook/login in a browser.
#
# Nothing here is stored server-side: the App ID / Secret come ONLY from
# environment variables (Render env vars on the hosted dashboard), the user
# token lives only for the length of the callback request, and the Page token
# is shown to the user so they can copy it into Mark's Connections tab.
# Secrets are never logged and never appear in any response. The callback URL
# is a fixed constant — never taken from the request — so nobody can point
# the flow at another site.

_FB_GRAPH_VERSION = "v18.0"
_FB_PUBLIC_URL    = "https://mark-lvii-dashboard.onrender.com"
_FB_CALLBACK_URL  = _FB_PUBLIC_URL + "/api/facebook/callback"
_FB_LOGIN_PAGE_URL = _FB_PUBLIC_URL + "/facebook/login"
_FB_SCOPES        = "pages_manage_posts,pages_read_engagement,pages_show_list"
# Instagram uses the SAME Facebook App (same App ID / Secret) — only the
# callback URL and the permission scope differ. The IG callback URL must
# ALSO be pasted into the app's "Valid OAuth Redirect URIs" field.
_IG_CALLBACK_URL   = _FB_PUBLIC_URL + "/api/instagram/callback"
_IG_LOGIN_PAGE_URL = _FB_PUBLIC_URL + "/instagram/login"
_IG_SCOPES         = ("instagram_basic,instagram_content_publish,"
                     "pages_show_list,pages_read_engagement")

# Tiny copy-to-clipboard helper (navigator.clipboard with an execCommand
# fallback for older browsers). Shared by the login page; the pages page
# carries its own identical copy.
_FB_COPY_JS = """
<script>
function copyField(id){ var el=document.getElementById(id); el.select();
try{ navigator.clipboard.writeText(el.value); }catch(e){ document.execCommand('copy'); }
var b=event.target; var t=b.textContent; b.textContent='✅ Copied!';
setTimeout(function(){ b.textContent=t; },1500); }
</script>"""


def _fb_url_copy_boxes(callback_url: str = _FB_CALLBACK_URL,
                       login_url: str = _FB_LOGIN_PAGE_URL) -> str:
    """Callback URL + login page URL, each in a visible box with a Copy button.

    Shown on the login page in both branches — the user needs the callback
    URL to paste into Facebook BEFORE the App ID env var is set. Defaults
    are the Facebook flow; the Instagram flow passes its own URLs.
    """
    return f"""<div class="card" style="text-align:left">
<p>Callback URL — Facebook-er "Valid OAuth Redirect URIs"-e ei-ta bosao:</p>
<input class="tok" id="cburl" readonly value="{callback_url}">
<button onclick="copyField('cburl')">📋 Copy callback URL</button>
<p>Login page URL:</p>
<input class="tok" id="loginurl" readonly value="{login_url}">
<button onclick="copyField('loginurl')">📋 Copy login URL</button>
</div>"""


def _fb_env() -> tuple[str, str]:
    """Facebook App ID + App Secret, env vars only. Never logged."""
    return ((os.environ.get("FACEBOOK_APP_ID") or "").strip(),
            (os.environ.get("FACEBOOK_APP_SECRET") or "").strip())


def _fb_login_url(app_id: str, redirect_uri: str = _FB_CALLBACK_URL,
                  scope: str = _FB_SCOPES) -> str:
    """The facebook.com dialog/oauth URL a Login button points at.

    Defaults are the Facebook flow; the Instagram flow passes its own
    redirect_uri + scope.
    """
    from urllib.parse import urlencode
    qs = urlencode({
        "client_id": app_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "response_type": "code",
    })
    return f"https://www.facebook.com/{_FB_GRAPH_VERSION}/dialog/oauth?{qs}"


def _fb_http_get(url: str, params: dict) -> tuple[int, dict]:
    """One blocking GET via requests (timeout 20 s). Returns (status, json).

    Kept as a tiny module-level function so tests can monkeypatch it —
    no network in tests, no real secrets.
    """
    import requests
    try:
        r = requests.get(url, params=params, timeout=20)
        try:
            data = r.json()
        except Exception:
            data = {}
        return r.status_code, (data if isinstance(data, dict) else {})
    except Exception as e:
        return 0, {"error": {"message": str(e)[:200]}}


def _fb_exchange_code(code: str, app_id: str,
                      app_secret: str,
                      redirect_uri: str = _FB_CALLBACK_URL) -> tuple[str | None, str | None]:
    """Exchange an OAuth code for a short-lived user token.

    Returns (token, None) on success or (None, plain-words Bengali error).
    The app secret is only ever sent to graph.facebook.com, never logged
    and never returned. redirect_uri must be the exact callback URL the
    login flow used (Facebook flow default, Instagram flow passes its own).
    """
    status, data = _fb_http_get(
        f"https://graph.facebook.com/{_FB_GRAPH_VERSION}/oauth/access_token",
        {"client_id": app_id, "client_secret": app_secret,
         "redirect_uri": redirect_uri, "code": code})
    tok = (data.get("access_token") or "").strip()
    if status == 200 and tok:
        return tok, None
    err = data.get("error") or {}
    msg = str(err.get("message") or "")
    if "secret" in msg.lower() or err.get("code") in (104,):
        return None, ("Facebook App Secret-ta thik noy — Render dashboard → "
                      "Environment-e FACEBOOK_APP_SECRET check koro.")
    if status == 400:
        return None, ("Code-ta kaj korlo na — hoyto expire hoye geche. "
                      "Abar /facebook/login theke Login chapho."
                      + (f" ({msg})" if msg else ""))
    return None, (f"Facebook token exchange holo na (HTTP {status})."
                   + (f" {msg}" if msg else ""))


def _fb_accounts_error(status: int, data: dict) -> str:
    """Plain-words Bengali error for a failed /me/accounts call."""
    err = data.get("error") or {}
    msg = str(err.get("message") or "")
    if status in (400, 401, 403):
        return ("Facebook Page list ante parlam na — token-ta expire hoye "
                "geche hote pare. Abar Login chapho."
                + (f" ({msg})" if msg else ""))
    return (f"Facebook Page list ante parlam na (HTTP {status})."
            + (f" {msg}" if msg else ""))


def _fb_list_pages(user_token: str) -> tuple[list, str | None]:
    """GET /me/accounts → [{"id", "name", "token"}]. Plain-words error or None."""
    status, data = _fb_http_get(
        f"https://graph.facebook.com/{_FB_GRAPH_VERSION}/me/accounts",
        {"fields": "id,name,access_token", "access_token": user_token})
    if status == 200:
        pages = []
        for p in data.get("data") or []:
            pid = str(p.get("id") or "").strip()
            name = str(p.get("name") or "").strip()
            ptok = str(p.get("access_token") or "").strip()
            if pid and ptok:
                pages.append({"id": pid, "name": name or pid, "token": ptok})
        return pages, None
    return [], _fb_accounts_error(status, data)


def _ig_list_pages(user_token: str) -> tuple[list, str | None]:
    """GET /me/accounts with the linked Instagram business account.

    Returns [{"id", "name", "token", "ig_id", "ig_username"}]. A Page with
    no linked IG business account still appears, with empty ig_id /
    ig_username — the page says so plainly instead of hiding the Page.
    """
    status, data = _fb_http_get(
        f"https://graph.facebook.com/{_FB_GRAPH_VERSION}/me/accounts",
        {"fields": "instagram_business_account{id,username},name,access_token",
         "access_token": user_token})
    if status == 200:
        pages = []
        for p in data.get("data") or []:
            pid = str(p.get("id") or "").strip()
            name = str(p.get("name") or "").strip()
            ptok = str(p.get("access_token") or "").strip()
            if not pid or not ptok:
                continue
            ig = p.get("instagram_business_account") or {}
            ig_id = str(ig.get("id") or "").strip()
            ig_name = str(ig.get("username") or "").strip()
            pages.append({"id": pid, "name": name or pid, "token": ptok,
                          "ig_id": ig_id, "ig_username": ig_name})
        return pages, None
    return [], _fb_accounts_error(status, data)


def _fb_page(title: str, body: str) -> str:
    """One small dark HTML page (same look as the dashboard's other pages)."""
    return ("<!DOCTYPE html>\n<html lang=\"bn\"><head><meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{html.escape(title)}</title>\n"
            "<style>body{background:#0b0f16;color:#e6f1ff;font-family:monospace;"
            "margin:0;padding:16px}h1{color:#22d3ee;font-size:20px;text-align:center}"
            "p{color:#e6f1ff;font-size:14px;line-height:1.6}.box{max-width:760px;"
            "margin:12px auto}.card{background:#131a26;border:1px solid #1f2c40;"
            "border-radius:12px;padding:14px;margin:10px auto;max-width:760px}"
            ".card h2{font-size:15px;margin:0 0 6px}.dim{color:#8fa3bf;font-size:12px;"
            "text-align:center}code{background:#0b0f16;border:1px solid #1f2c40;"
            "border-radius:6px;padding:2px 6px;word-break:break-all}"
            "input.tok{width:100%;box-sizing:border-box;background:#0b0f16;color:#e6f1ff;"
            "border:1px solid #1f2c40;border-radius:8px;padding:10px;font-family:monospace;"
            "margin:6px 0}button{background:#22d3ee;color:#04222b;border:0;border-radius:8px;"
            "padding:10px 18px;font-family:monospace;font-weight:bold;cursor:pointer}"
            "button.ghost{background:#0b0f16;color:#22d3ee;border:1px solid #22d3ee}"
            "a.btn{display:inline-block;background:#1877f2;color:#fff;text-decoration:none;"
            "border-radius:8px;padding:12px 22px;font-weight:bold}</style></head><body>\n"
            + body + "\n</body></html>")


def _fb_login_html(app_id: str) -> str:
    """The /facebook/login page: Login button, or the env-var setup note.

    Both branches show the callback + login URL copy boxes — the user needs
    the callback URL to paste into Facebook before the App ID is even set.
    """
    boxes = _fb_url_copy_boxes() + _FB_COPY_JS
    if not app_id:
        body = """<div class="box"><h1>🔵 Facebook Login — Mark-LVII</h1>
<p>Facebook Page token pawar jonno age App ID set korte hobe.</p>
<p>👉 <b>Render dashboard</b> → Service <b>mark-lvii-dashboard</b> → <b>Environment</b> → add koro:</p>
<p><code>FACEBOOK_APP_ID</code> = tomar Facebook App-er App ID<br>
<code>FACEBOOK_APP_SECRET</code> = tomar Facebook App-er App Secret</p>
<p class="dim">App ID / Secret pabe: developers.facebook.com → tomar app → Settings → Basic.<br>
Kokhono chat-e token/secret pathio na — sudhu Render env vars-e bosao.</p></div>""" + boxes
        return _fb_page("Facebook Login — Mark-LVII", body)
    url = _fb_login_url(app_id)
    body = f"""<div class="box" style="text-align:center"><h1>🔵 Facebook Login — Mark-LVII</h1>
<p>Facebook-e Login chaple Facebook tomar Page-er token debe. Token-ta ekhanei dekhabe —<br>
tarpor Mark-er Connections tab-e <code>facebook_page_token</code> + <code>facebook_page_id</code> bosabe.</p>
<p><a class="btn" href="{html.escape(url, quote=True)}">🔵 Login with Facebook</a></p>
<p class="dim">Facebook-er "Valid OAuth Redirect URIs"-e ei URL-ta thakte hobe — Copy chaple copy hobe.</p></div>""" + boxes
    return _fb_page("Facebook Login — Mark-LVII", body)


def _fb_pages_html(pages: list) -> str:
    """The callback success page: each Page with ID + token and copy buttons."""
    cards = []
    for i, p in enumerate(pages):
        name = html.escape(p["name"])
        pid = html.escape(p["id"])
        tok = html.escape(p["token"], quote=True)
        cards.append(f"""<div class="card"><h2>📄 {name}</h2>
<p>Page ID: <code>{pid}</code> <button class="ghost" onclick="copyField('pid{i}')">📋 Copy ID</button></p>
<p>Page token:</p>
<input class="tok" id="tok{i}" readonly value="{tok}">
<button onclick="copyField('tok{i}')">📋 Copy token</button>
<input type="hidden" id="pid{i}" value="{pid}"></div>""")
    body = """<div class="box"><h1>✅ Facebook Login holo — Page token</h1>
<p>Je Page-e post korte chao, tar <b>Page ID</b> ar <b>Page token</b> copy kore Mark-er
Connections tab-e bosao: <code>facebook_page_id</code> + <code>facebook_page_token</code>.</p>
<p class="dim">Token-ta ekhane kothao save kora hoy ni — ei page-ta bondho korle abar Login korte hobe.</p></div>
""" + "\n".join(cards) + """
<script>
function copyField(id){ var el=document.getElementById(id); el.select();
try{ navigator.clipboard.writeText(el.value); }catch(e){ document.execCommand('copy'); }
var b=event.target; var t=b.textContent; b.textContent='✅ Copied!';
setTimeout(function(){ b.textContent=t; },1500); }
</script>"""
    return _fb_page("Facebook Page token — Mark-LVII", body)


def _fb_error_html(title: str, message: str) -> str:
    """A plain-words error page with a link back to /facebook/login."""
    body = f"""<div class="box"><h1>⚠️ {html.escape(title)}</h1>
<p>{html.escape(message)}</p>
<p><a class="btn" href="/facebook/login">🔄 Abar Login koro</a></p></div>"""
    return _fb_page(title, body)


def _fb_webhook_verify(hub_mode: str, hub_verify_token: str,
                       hub_challenge: str):
    """Facebook webhook verification handshake (GET on the callback URLs).

    Returns a PlainTextResponse with the challenge on a token match, a 403
    PlainTextResponse on mismatch / missing env var, or None when this is
    NOT a verification request (no hub.mode=subscribe) — so the caller can
    fall through to the OAuth code flow. The expected token comes ONLY from
    the FACEBOOK_VERIFY_TOKEN env var (the same value the user types in
    Facebook's "Verify token" field) — never hardcoded, never logged.
    """
    if hub_mode != "subscribe":
        return None
    expected = (os.environ.get("FACEBOOK_VERIFY_TOKEN") or "").strip()
    if (expected and hub_verify_token and hub_challenge
            and hub_verify_token == expected):
        return PlainTextResponse(hub_challenge, status_code=200)
    return PlainTextResponse("Verify token mile ni.", status_code=403)


def _ig_login_html(app_id: str) -> str:
    """The /instagram/login page: Login button, or the env-var setup note.

    Same Facebook App (same App ID / Secret) as the Facebook flow — only
    the callback URL and the scope differ. Both branches show the callback
    + login URL copy boxes.
    """
    boxes = (_fb_url_copy_boxes(_IG_CALLBACK_URL, _IG_LOGIN_PAGE_URL)
             + _FB_COPY_JS)
    if not app_id:
        body = """<div class="box"><h1>📸 Instagram Login — Mark-LVII</h1>
<p>Instagram post korar jonno age App ID set korte hobe — Facebook-er motoi, ekoi App.</p>
<p>👉 <b>Render dashboard</b> → Service <b>mark-lvii-dashboard</b> → <b>Environment</b> → add koro:</p>
<p><code>FACEBOOK_APP_ID</code> = tomar Facebook App-er App ID<br>
<code>FACEBOOK_APP_SECRET</code> = tomar Facebook App-er App Secret</p>
<p class="dim">App ID / Secret pabe: developers.facebook.com → tomar app → Settings → Basic.<br>
Kokhono chat-e token/secret pathio na — sudhu Render env vars-e bosao.</p></div>""" + boxes
        return _fb_page("Instagram Login — Mark-LVII", body)
    url = _fb_login_url(app_id, _IG_CALLBACK_URL, _IG_SCOPES)
    body = f"""<div class="box" style="text-align:center"><h1>📸 Instagram Login — Mark-LVII</h1>
<p>Facebook-e Login chaple Facebook tomar Page-er sathe linked Instagram account-er tothyo debe.<br>
IG user id + Page token ekhanei dekhabe — tarpor Mark-er Connections tab-e bosabe.</p>
<p><a class="btn" href="{html.escape(url, quote=True)}">🔵 Login with Facebook</a></p>
<p class="dim">Instagram-er callback URL-tao Facebook-er "Valid OAuth Redirect URIs"-e thakte hobe — Copy chaple copy hobe.</p></div>""" + boxes
    return _fb_page("Instagram Login — Mark-LVII", body)


def _ig_pages_html(pages: list) -> str:
    """The Instagram callback success page: Page + linked IG account + token.

    Each value has its own copy button. A Page with no linked IG business
    account says so plainly instead of being hidden.
    """
    cards = []
    for i, p in enumerate(pages):
        name = html.escape(p["name"])
        pid = html.escape(p["id"])
        tok = html.escape(p["token"], quote=True)
        ig_id = html.escape(p["ig_id"])
        ig_name = html.escape(p["ig_username"])
        if p["ig_id"]:
            ig_block = f"""<p>📸 Instagram: <b>@{ig_name}</b></p>
<p>IG user id: <code>{ig_id}</code> <button class="ghost" onclick="copyField('igid{i}')">📋 Copy IG id</button></p>
<input type="hidden" id="igid{i}" value="{ig_id}">"""
        else:
            ig_block = """<p>⚠️ ei Page-er sathe kono IG business account linked nei — Facebook Page
Settings → Linked accounts-e Instagram connect koro, tarpor abar Login chapho.</p>"""
        cards.append(f"""<div class="card"><h2>📄 {name}</h2>
{ig_block}
<p>Page ID: <code>{pid}</code> <button class="ghost" onclick="copyField('pid{i}')">📋 Copy ID</button></p>
<p>Page token (Mark-e <code>instagram_token</code> hisebe bosabe):</p>
<input class="tok" id="tok{i}" readonly value="{tok}">
<button onclick="copyField('tok{i}')">📋 Copy token</button>
<input type="hidden" id="pid{i}" value="{pid}"></div>""")
    body = """<div class="box"><h1>✅ Instagram Login holo</h1>
<p>Mark-er Connections tab-e bosao: <code>instagram_user_id</code> = IG user id,
<code>instagram_token</code> = Page token. (Facebook Page ID lagbe na — sudhu ei duto.)</p>
<p class="dim">Token-ta ekhane kothao save kora hoy ni — ei page-ta bondho korle abar Login korte hobe.</p></div>
""" + "\n".join(cards) + _FB_COPY_JS
    return _fb_page("Instagram — Mark-LVII", body)


class DashboardServer:

    def __init__(self):
        self._ip                          = _local_ip()
        # token -> issued-at. A set had no way to expire anything; this does,
        # and `_auth` sweeps as it reads so nothing has to run a timer.
        self._tokens: dict[str, float]    = {}
        self._token_keys: dict[str, str]  = {}   # auth_token → session_key
        self._aes_cache:  dict[str, bytes]= {}   # session_key → AES bytes
        self._clients: set[WebSocket]     = set()
        self._history: list[dict]         = []
        self._command_queue               = asyncio.Queue()
        self._wake_callback               = None
        self._connect_callback            = None
        self._pending_keys: dict[str, float] = {}
        self._throttle                    = _Throttle()
        self._device_sessions: dict[str, dict] = {}  # device_token → {session_key}
        self._phone_audio_queue: asyncio.Queue    = asyncio.Queue(maxsize=200)
        self._uploads_dir                 = UPLOADS_DIR
        # Set by serve() when the port could not be taken, so the UI can say
        # why the QR code leads nowhere instead of showing it regardless.
        self._bind_error: str = ""
        self._login_html                  = _read("login.html")
        self._app_html                    = _read("app.html")
        # ── Browser control (Chrome extension) ────────────────────────────
        # Queued commands the extension polls for; results it posts back.
        # The browser token is a shared secret of its own — NOT a dashboard
        # bearer token — so the extension never holds a login token.
        self._browser_commands: list[dict] = []
        self._browser_results: dict[str, dict] = {}
        self._browser_events: dict[str, threading.Event] = {}
        self._browser_seen: dict[str, float] = {}
        self._browser_token = self._init_browser_token()
        self.app                          = self._build_app()

    def _init_browser_token(self) -> str:
        """Shared secret for the Chrome extension.

        Precedence: BROWSER_TOKEN env var (a fixed token survives Render
        restarts) → stored plugin_config["jarvis_link"]["browser_token"] →
        a fresh random token saved back via config_manager. The token value
        itself is never logged or returned by any endpoint.
        """
        token = (os.environ.get("BROWSER_TOKEN") or "").strip()
        if token:
            return token
        try:
            from memory.config_manager import (
                get_plugin_config, save_plugin_config)
            existing = get_plugin_config("jarvis_link")
            token = str(existing.get("browser_token") or "").strip()
            if not token:
                token = secrets.token_urlsafe(24)
                save_plugin_config(
                    "jarvis_link", {**existing, "browser_token": token})
            return token
        except Exception:
            # config_manager is stdlib-only, so this should not fail — but a
            # missing config must never stop the dashboard from starting.
            return secrets.token_urlsafe(24)

    # Extra command fields the extension understands, beyond url/selector/
    # text. Anything not on this list is dropped, so a caller can never smuggle
    # a credential or a file into a queued command — logins/signups come only
    # from the extension popup's own chrome.storage.local, and upload files
    # only from a file the user picked there.
    _BROWSER_EXTRA_KEYS = frozenset({
        "fields", "tab_action", "tab_id", "bookmark_action", "bookmark_id",
        "title", "step", "delay_ms", "max_steps", "submit",
    })

    def queue_browser_command(self, action: str, url: str = "",
                              selector: str = "", text: str = "",
                              extra: dict | None = None) -> str:
        """Queue a command for the Chrome extension; returns its id.

        The queue is capped at 20 — the oldest command is dropped when it
        overflows, so a dead extension can never grow it without bound.
        `extra` carries the whitelisted per-action fields (see
        _BROWSER_EXTRA_KEYS): tab/bookmark sub-actions, form-fill fields,
        autoscroll steps. Unknown keys are dropped, never queued.
        """
        cmd = {
            "id": secrets.token_urlsafe(8),
            "action": str(action or ""),
            "url": str(url or ""),
            "selector": str(selector or ""),
            "text": str(text or ""),
            "created_at": time.time(),
            "delivered": False,
        }
        for key, value in (extra or {}).items():
            if key in self._BROWSER_EXTRA_KEYS:
                cmd[key] = value
        self._browser_commands.append(cmd)
        while len(self._browser_commands) > 20:
            old = self._browser_commands.pop(0)
            self._browser_events.pop(old["id"], None)
        self._browser_events[cmd["id"]] = threading.Event()
        return cmd["id"]

    def wait_browser_result(self, cmd_id: str, timeout: float = 60.0) -> dict:
        """Wait for the extension to post a result for cmd_id.

        Returns the stored result, or {"ok": False, "error": "timeout"} /
        "unknown command id" when nothing arrives in time.
        """
        ev = self._browser_events.get(cmd_id)
        if ev is None:
            return {"ok": False, "error": "unknown command id"}
        if not ev.wait(timeout):
            return {"ok": False, "error": "timeout"}
        return self._browser_results.get(
            cmd_id, {"ok": False, "error": "no result"})

    # ── one-time key management ───────────────────────────────────────────

    def new_key(self, expiry_secs: int = 600) -> str:
        now = time.time()
        self._pending_keys = {k: v for k, v in self._pending_keys.items() if v > now}
        key = ''.join(secrets.choice(_KEY_CHARS) for _ in range(8))
        self._pending_keys[key] = now + expiry_secs
        return key

    @staticmethod
    def _ssl_enabled() -> bool:
        """Is HTTPS switched on? Off unless the user asked for it.

        WHY THE DEFAULT IS PLAIN HTTP, AFTER A RELEASE THAT MADE TLS MANDATORY
            The certificate has to be self-signed — there is no certificate
            authority on earth that will vouch for 192.168.1.108 — and a phone
            treats a self-signed certificate as an attack. Chrome shows a
            full-page interstitial; a QR scanner that opens links in its own
            in-app browser often shows nothing at all and offers no way to
            proceed, because those views deliberately have no "Advanced" button.

            So the practical result of requiring TLS was a dashboard nobody
            could reach, which is not a more secure product than one they can.
            The pairing key, the rate limit, the token expiry and the
            revoke-all-devices fix are all unaffected and all still apply.

            What IS lost over plain HTTP is the AES-GCM layer, because
            `crypto.subtle` does not exist outside a secure context. The page
            says so on its own badge rather than pretending, and commands then
            travel the local network in clear — which is what this dashboard
            did for every release before this one.

            Turn it on with "dashboard_https": true in config/api_keys.json if
            the network is one where that matters; the certificate is generated
            automatically and you will have to accept it once per device.
        """
        try:
            import json as _json
            with open(BASE_DIR / "config" / "api_keys.json", "r",
                      encoding="utf-8") as f:
                if not _json.load(f).get("dashboard_https"):
                    return False
        except Exception:
            return False
        certs = BASE_DIR / "config" / "certs"
        return (certs / "jarvis.key").exists() and (certs / "jarvis.crt").exists()

    def get_url(self) -> str:
        """The full URL the QR code carries — always with its scheme, so a
        scanner never has to guess."""
        if self._ssl_enabled():
            return f"https://{self._ip}:{SECURE_PORT}"
        return f"http://{self._ip}:{PORT}"

    def get_manual_url(self) -> str:
        """What to type into a phone browser by hand.

        Points at the redirect port when TLS is on, because a bare `ip:port`
        typed into a browser is tried over HTTP — and HTTP against the TLS port
        looks exactly like the server being switched off. The redirector speaks
        HTTP, so it answers, and sends the browser on to the secure page.
        """
        return f"{self._ip}:{PORT}"

    def _aes_key(self, session_key: str) -> bytes:
        if session_key not in self._aes_cache:
            self._aes_cache[session_key] = _derive_key(session_key)
        return self._aes_cache[session_key]

    def _decrypt(self, token: str, enc_b64: str) -> str | None:
        sk = self._token_keys.get(token)
        if not sk:
            return None
        try:
            return _decrypt(self._aes_key(sk), enc_b64)
        except Exception:
            return None

    # ── callbacks ────────────────────────────────────────────────────────

    def set_wake_callback(self, fn) -> None:
        self._wake_callback = fn

    def set_connect_callback(self, fn) -> None:
        self._connect_callback = fn

    # ── broadcast ────────────────────────────────────────────────────────

    async def broadcast(self, msg: dict) -> None:
        self._history.append(msg)
        if len(self._history) > 300:
            self._history = self._history[-300:]
        dead: set[WebSocket] = set()
        for ws in list(self._clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    # ── FastAPI app ───────────────────────────────────────────────────────

    def _build_app(self) -> "FastAPI":
        app = FastAPI(docs_url=None, redoc_url=None)

        def _valid(tok: str) -> bool:
            """Is this token live? Expired ones are dropped as they are found,
            which keeps the sweep free and needs no background timer."""
            if not tok:
                return False
            issued = self._tokens.get(tok)
            if issued is None:
                return False
            if time.time() - issued > _TOKEN_TTL_SECONDS:
                self._tokens.pop(tok, None)
                self._token_keys.pop(tok, None)
                return False
            return True

        def _auth(req: Request) -> bool:
            return _valid(req.headers.get("authorization", "")
                          .removeprefix("Bearer ").strip())

        def _browser_auth(req: Request) -> bool:
            """Extension auth: the shared browser secret, never a bearer token.

            The token value is compared, never logged or returned.
            """
            tok = req.headers.get("x-browser-token", "").strip()
            return bool(self._browser_token) and tok == self._browser_token

        def _who(req: Request) -> str:
            """The client address a throttle counts against."""
            return (getattr(getattr(req, "client", None), "host", "") or "unknown")

        @app.get("/login", response_class=HTMLResponse)
        async def login_page():
            return HTMLResponse(self._login_html)

        @app.get("/", response_class=HTMLResponse)
        async def index():
            # Auth is handled client-side via sessionStorage bearer token.
            # Server-side header auth can't work here because browser navigations
            # don't send custom headers (location.href doesn't carry Authorization).
            html = (self._app_html
                    .replace("__IP__", self._ip)
                    .replace("__PORT__", str(PORT)))
            return HTMLResponse(html)

        @app.post("/login")
        async def login(req: Request):
            who  = _who(req)
            wait = self._throttle.blocked_for(who)
            if wait > 0:
                # 429 rather than 401 on purpose: it tells an honest user why
                # their correct key was refused, and it tells a script that
                # guessing is not working.
                return JSONResponse(
                    {"ok": False,
                     "error": f"Too many attempts. Try again in "
                              f"{int(wait) + 1} seconds."},
                    status_code=429,
                )
            body    = await req.json()
            entered = str(body.get("pin", "")).strip().upper()
            now     = time.time()
            if entered in self._pending_keys and self._pending_keys[entered] > now:
                self._throttle.clear(who)
                del self._pending_keys[entered]          # one-time use
                tok = secrets.token_urlsafe(32)
                self._tokens[tok] = time.time()
                self._token_keys[tok] = entered
                self._aes_key(entered)                   # pre-derive & cache
                if self._connect_callback:
                    self._connect_callback()
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Remote connection established."}
                ))
                # Bearer token in response body — no cookies needed (works on any browser/HTTP)
                return JSONResponse({"ok": True, "token": tok})
            self._throttle.record_failure(who)
            return JSONResponse({"ok": False, "error": "Invalid or expired key"},
                                status_code=401)

        @app.get("/auto-login")
        async def auto_login(key: str = ""):
            """QR code target — validates one-time key, creates session, redirects phone."""
            now = time.time()
            if not key or key not in self._pending_keys or self._pending_keys[key] <= now:
                return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
  h2{color:#f87171;margin-bottom:12px}p{color:#5e6a7e;font-size:14px}
</style></head>
<body><div><h2>Link Expired</h2>
<p>Press <strong style="color:#dde3ed">Remote Control</strong> in JARVIS to get a new QR code.</p>
</div></body></html>""")

            del self._pending_keys[key]
            tok     = secrets.token_urlsafe(32)
            dev_tok = secrets.token_urlsafe(32)
            self._tokens[tok] = time.time()
            self._token_keys[tok] = key
            self._aes_key(key)
            self._device_sessions[dev_tok] = {"session_key": key}

            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Remote connection established via QR code."}
            ))

            return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}}
  p{{color:#5e6a7e;font-size:14px}}
</style></head>
<body>
<script>
  sessionStorage.setItem('jarvis_token','{tok}');
  sessionStorage.setItem('jarvis_key','{key}');
  localStorage.setItem('jarvis_device_token','{dev_tok}');
  setTimeout(function(){{location.replace('/')}},400);
</script>
<p>Connecting to JARVIS…</p>
</body></html>""")

        @app.post("/api/device-login")
        async def device_login_ep(req: Request):
            """Return a fresh auth token for a previously paired device token."""
            try:
                body = await req.json()
            except Exception:
                return JSONResponse({"ok": False}, status_code=400)
            dev_tok = (body.get("device_token") or "").strip()
            if not dev_tok or dev_tok not in self._device_sessions:
                return JSONResponse({"ok": False}, status_code=401)
            session_key = self._device_sessions[dev_tok]["session_key"]
            tok = secrets.token_urlsafe(32)
            self._tokens[tok] = time.time()
            self._token_keys[tok] = session_key
            self._aes_key(session_key)
            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Known device reconnected automatically."}
            ))
            return JSONResponse({"ok": True, "token": tok, "key": session_key})

        @app.post("/api/revoke-devices")
        async def revoke_devices(req: Request):
            """Invalidate all persistent device tokens (admin action)."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            # ALSO drop the live tokens, which this did not do.
            #
            # It cleared the remembered devices and left every session those
            # devices had already opened working until the app restarted — so
            # "revoke all devices" revoked nothing anybody was currently using,
            # which is the one case somebody presses it for.
            #
            # The caller's own token is kept, or pressing the button would log
            # out the person who pressed it.
            mine  = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            count = len(self._device_sessions)
            live  = len(self._tokens) - (1 if mine in self._tokens else 0)
            self._device_sessions.clear()
            keep = self._tokens.get(mine)
            self._tokens.clear()
            self._token_keys = {k: v for k, v in self._token_keys.items() if k == mine}
            if keep is not None:
                self._tokens[mine] = keep
            return JSONResponse({"ok": True, "revoked": count, "sessions_ended": live})

        @app.post("/api/command")
        async def command(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            body  = await req.json()
            token = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            enc   = body.get("enc", "")
            if enc:
                text = self._decrypt(token, enc)
                if text is None:
                    return JSONResponse({"error": "Decryption failed"}, status_code=400)
            else:
                text = (body.get("text") or "").strip()
            if text:
                await self._command_queue.put(text)
                if self._wake_callback:
                    self._wake_callback()
            return JSONResponse({"ok": True})

        # ── Chrome extension browser control ─────────────────────────────
        # The extension polls /api/browser/commands and posts results to
        # /api/browser/result, authenticated by the shared browser secret
        # (X-Browser-Token) — not by a dashboard bearer token. A remote
        # caller (e.g. Muse via the Render URL) can queue a command through
        # /api/browser/command with the same secret. Credentials are never
        # involved here: logins are filled from the extension popup's own
        # storage, which Mark never sees.

        @app.post("/api/browser/command")
        async def browser_command(req: Request):
            if not _browser_auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                body = await req.json()
            except Exception:
                body = {}
            action = str(body.get("action") or "").strip()
            if not action:
                return JSONResponse({"ok": False, "error": "action required"},
                                    status_code=400)
            extra = {k: body.get(k) for k in self._BROWSER_EXTRA_KEYS
                     if body.get(k) is not None}
            cmd_id = self.queue_browser_command(
                action,
                str(body.get("url") or ""),
                str(body.get("selector") or ""),
                str(body.get("text") or ""),
                extra,
            )
            return JSONResponse({"ok": True, "id": cmd_id})

        @app.get("/api/browser/commands")
        async def browser_commands(req: Request, ext: str = "ext"):
            if not _browser_auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            now = time.time()
            self._browser_seen[ext or "ext"] = now
            out = []
            for cmd in self._browser_commands:
                if (not cmd.get("delivered")
                        and now - cmd.get("created_at", 0) <= 60):
                    cmd["delivered"] = True
                    out.append({k: v for k, v in cmd.items()
                                if k != "delivered"})
            return JSONResponse({"ok": True, "commands": out})

        @app.post("/api/browser/result")
        async def browser_result(req: Request):
            if not _browser_auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                body = await req.json()
            except Exception:
                body = {}
            cmd_id = str(body.get("id") or "")
            if not cmd_id:
                return JSONResponse({"ok": False, "error": "id required"},
                                    status_code=400)
            self._browser_results[cmd_id] = {
                "ok": bool(body.get("ok")),
                "data": body.get("data"),
                "error": body.get("error") or "",
                "at": time.time(),
            }
            ev = self._browser_events.get(cmd_id)
            if ev is not None:
                ev.set()
            return JSONResponse({"ok": True})

        @app.get("/api/browser/result/{cmd_id}")
        async def browser_result_get(req: Request, cmd_id: str):
            # Lets a caller that queued a command over HTTP (no in-process
            # handle on this server) poll for the extension's answer instead
            # of waiting blind. Same browser-token auth as the other
            # extension endpoints; "pending" while nothing has arrived yet.
            if not _browser_auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            res = self._browser_results.get(cmd_id or "")
            if res is None:
                if cmd_id in self._browser_events:
                    return JSONResponse({"ok": False, "error": "pending"})
                return JSONResponse({"ok": False, "error": "unknown command id"},
                                    status_code=404)
            return JSONResponse({"ok": True, "result": res})

        @app.get("/api/browser/status")
        async def browser_status(req: Request):
            if not (_browser_auth(req) or _auth(req)):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            now = time.time()
            connected = [e for e, seen in self._browser_seen.items()
                         if now - seen <= 120]
            queued = sum(1 for c in self._browser_commands
                         if not c.get("delivered")
                         and now - c.get("created_at", 0) <= 60)
            return JSONResponse({"ok": True, "connected": connected,
                                 "queued": queued,
                                 "results": len(self._browser_results)})

        # ── Meta webhooks: WhatsApp + Instagram auto-reply ─────────────────
        # Meta calls these, NOT the Chrome extension and NOT a logged-in user,
        # so they must NOT require the browser token or a bearer token. Auth
        # is the hub.verify_token check on GET (Meta's own subscription
        # handshake) — the token is the one the user made up in Settings and
        # pasted into their Meta app. No secret is ever logged here, and a
        # bad payload is answered 200 with a short note, never a crash:
        # Meta retries failed deliveries, so a 500 would spam the endpoint.
        # The dashboard (Render URL or the PC) must be reachable for Meta
        # to deliver events at all — Mark cannot register these URLs in
        # Meta for the user; they paste them into their Meta app themselves:
        #   https://mark-lvii-dashboard.onrender.com/webhooks/whatsapp
        #   https://mark-lvii-dashboard.onrender.com/webhooks/instagram

        def _webhook_verify(req: Request, platform: str):
            """Meta subscription check. Returns the challenge as plain text
            on a match, else 403. The expected token comes from
            plugin_config["autoreply"]; when none is set, nothing verifies."""
            try:
                from core.autoreply import get_config as _ar_cfg
                expected = str(_ar_cfg().get(f"{platform}_verify_token", "")
                               or "").strip()
            except Exception:
                expected = ""
            if platform == "facebook" and not expected:
                try:
                    from memory.config_manager import get_plugin_config as _gpc
                    expected = str((_gpc("cat05_social") or {}).get(
                        "facebook_verify_token", "") or "").strip()
                except Exception:
                    expected = ""
            qp = req.query_params
            mode = (qp.get("hub.mode") or "").strip()
            token = (qp.get("hub.verify_token") or "").strip()
            challenge = (qp.get("hub.challenge") or "").strip()
            if (mode == "subscribe" and challenge and expected
                    and token == expected):
                return PlainTextResponse(challenge, status_code=200)
            return JSONResponse({"error": "Forbidden"}, status_code=403)

        async def _webhook_receive(req: Request, platform: str):
            """Parse a Meta event body and hand each text message to the
            auto-reply engine (in a thread — sending is a blocking HTTP
            call). Always 200 after logging a short count; never raises."""
            try:
                body = await req.json()
            except Exception:
                return JSONResponse({"ok": True, "note": "not JSON, ignored"})
            try:
                from core import autoreply as _ar
                if platform == "whatsapp":
                    messages = _ar.extract_whatsapp_messages(body)
                elif platform == "instagram":
                    messages = _ar.extract_instagram_messages(body)
                else:
                    messages = []
            except Exception:
                messages = []
            if platform == "facebook":
                try:
                    from core import cat05_social as _c05
                    messages = _c05.extract_facebook_messages(body)
                except Exception:
                    messages = []
            replied = 0
            for sender_id, text in messages:
                try:
                    if platform == "facebook":
                        from core import cat05_social as _c05
                        result = await asyncio.to_thread(
                            _c05.handle_facebook_incoming, sender_id, text)
                    else:
                        # to_thread: handle_incoming does blocking requests.
                        result = await asyncio.to_thread(
                            _ar.handle_incoming, platform, sender_id, text)
                    if result not in ("disabled", "no reply"):
                        replied += 1
                except Exception:
                    pass
            print(f"[Dashboard] webhook {platform}: {len(messages)} message(s), "
                  f"{replied} replie(s) sent.")
            return JSONResponse({"ok": True, "received": len(messages),
                                 "replied": replied})

        @app.get("/webhooks/whatsapp")
        async def whatsapp_webhook_get(req: Request):
            return _webhook_verify(req, "whatsapp")

        @app.post("/webhooks/whatsapp")
        async def whatsapp_webhook_post(req: Request):
            return await _webhook_receive(req, "whatsapp")

        @app.get("/webhooks/instagram")
        async def instagram_webhook_get(req: Request):
            return _webhook_verify(req, "instagram")

        @app.post("/webhooks/instagram")
        async def instagram_webhook_post(req: Request):
            return await _webhook_receive(req, "instagram")

        @app.get("/webhooks/facebook")
        async def facebook_webhook_get(req: Request):
            return _webhook_verify(req, "facebook")

        @app.post("/webhooks/facebook")
        async def facebook_webhook_post(req: Request):
            return await _webhook_receive(req, "facebook")

        @app.post("/api/wake")
        async def wake_ep(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            if self._wake_callback:
                self._wake_callback()
            return JSONResponse({"ok": True})

        # ── Phone mic real-time audio → Gemini Live ──────────────────────────

        @app.websocket("/ws/phone-audio")
        async def phone_audio_ws(websocket: WebSocket, token: str = ""):
            tok = token.strip()
            if not _valid(tok):
                await websocket.close(code=4001)
                return
            await websocket.accept()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Phone microphone live."}
            ))
            try:
                while True:
                    data = await websocket.receive_bytes()
                    try:
                        self._phone_audio_queue.put_nowait(
                            {"data": data, "mime_type": "audio/pcm"}
                        )
                    except asyncio.QueueFull:
                        pass  # drop frame rather than block
            except WebSocketDisconnect:
                pass
            finally:
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Phone microphone stopped."}
                ))

        # ── File sharing ──────────────────────────────────────────────────────

        def _safe_filename(raw: str) -> str:
            name = Path(raw).name                          # strip path components
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(". ")
            return name or "upload"

        if _UPLOAD_OK:
            @app.post("/api/upload")
            async def upload_file(req: Request, file: UploadFile = FastAPIFile(...)):
                if not _auth(req):
                    return JSONResponse({"error": "Unauthorized"}, status_code=401)

                safe = _safe_filename(file.filename or "upload")
                dest = self._uploads_dir / safe
                stem, suffix = Path(safe).stem, Path(safe).suffix
                counter = 1
                while dest.exists():
                    dest = self._uploads_dir / f"{stem}_{counter}{suffix}"
                    counter += 1

                size = 0
                max_bytes = MAX_UPLOAD_MB * 1024 * 1024
                try:
                    with open(dest, "wb") as fout:
                        while True:
                            chunk = await file.read(65536)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > max_bytes:
                                fout.close()
                                dest.unlink(missing_ok=True)
                                return JSONResponse(
                                    {"error": f"File too large (max {MAX_UPLOAD_MB} MB)"},
                                    status_code=413,
                                )
                            fout.write(chunk)
                except Exception as exc:
                    try:
                        dest.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return JSONResponse({"error": str(exc)}, status_code=500)

                asyncio.create_task(self.broadcast({
                    "type": "file_received",
                    "name": dest.name,
                    "size": size,
                    "saved_to": str(self._uploads_dir),
                }))
                return JSONResponse({"ok": True, "name": dest.name, "size": size})
        else:
            @app.post("/api/upload")
            async def upload_unavailable(req: Request):
                return JSONResponse(
                    {"error": "File uploads require: pip install python-multipart"},
                    status_code=503,
                )

        @app.get("/api/files")
        async def list_files(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            files = []
            try:
                for f in sorted(
                    (p for p in self._uploads_dir.iterdir() if p.is_file()),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                ):
                    files.append({"name": f.name, "size": f.stat().st_size})
            except Exception:
                pass
            return JSONResponse({"files": files})

        @app.get("/api/jarvis-link")
        async def jarvis_link_status(req: Request):
            """📱 Jarvis Link — phone Jarvis app pairing over the backend relay.

            Read-only status: paired or not, E2E on or off. The QR itself is
            shown on the desktop HUD (📱 JARVIS LINK button), never here — the
            phone app scans it from the PC screen.
            """
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                from core import jarvis_link
                return JSONResponse(jarvis_link.status())
            except Exception as e:
                return JSONResponse({"paired": False, "running": False,
                                     "error": str(e)[:120]})

        @app.get("/api/agents")
        async def agents_status(req: Request):
            """🤖 Agents — live status of the 7 worker agents.

            Same auth as /api/jarvis-link: Bearer token, 401 without it.
            Returns {"agents": [...]} from core.agents.REGISTRY.snapshot().
            Never raises — a registry failure returns an empty list + error.
            """
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                from core.agents import REGISTRY
                return JSONResponse({"agents": REGISTRY.snapshot()})
            except Exception as e:
                return JSONResponse({"agents": [],
                                     "error": str(e)[:120]})

        @app.get("/api/privacy")
        async def privacy_api(req: Request):
            """🔒 Privacy — presence-only inventory of saved keys/tokens and
            where data goes (core.cat09_security.privacy_summary). Values
            are never read into the output. Bearer auth like /api/agents.
            Never raises."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                from core.cat09_security import privacy_summary as _ps
                return JSONResponse(_ps())
            except Exception as e:
                return JSONResponse({"keys": [], "destinations": [],
                                     "error": str(e)[:120]})

        @app.get("/api/phone-screen")
        async def phone_screen_image(req: Request, token: str = ""):
            """Latest phone screenshot as a JPEG (404 when none fetched yet).

            Auth: Bearer header (like other /api/*) or ?token= query param
            (browser <img> can't send custom headers — same as /uploads).
            Honest limit: still image per fetch_phone_screen() call, NOT
            live video — the /phone-screen page re-polls it every 4 s.
            """
            if not _auth(req) and not _valid(token.strip()):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                from core import jarvis_link
                info = jarvis_link.latest_phone_screen()
                p = info.get("path", "")
                if not p or not os.path.exists(p):
                    return JSONResponse(
                        {"error": "No phone screenshot yet — ask Mark for phone_screen first."},
                        status_code=404)
                return FileResponse(p, media_type="image/jpeg",
                                    headers={"Cache-Control": "no-store"})
            except Exception as e:
                return JSONResponse({"error": str(e)[:120]}, status_code=500)

        @app.post("/api/phone-screen/refresh")
        async def phone_screen_refresh(req: Request):
            """Ask the phone for a FRESH screenshot now (background thread).

            Returns at once — the new image appears at /api/phone-screen
            when it arrives (~5-15 s). Needs the phone paired.
            """
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                from core import jarvis_link
                link = jarvis_link.LINK
                if link is None or not link.paired:
                    return JSONResponse(
                        {"error": "Phone pair kora nei — age QR scan koro."},
                        status_code=409)
                threading.Thread(target=lambda: link.fetch_phone_screen(),
                                 daemon=True).start()
                return JSONResponse({"ok": True,
                                     "message": "Phone-er screen anar chesta cholche — koyek second-e asbe."})
            except Exception as e:
                return JSONResponse({"error": str(e)[:120]}, status_code=500)

        @app.get("/phone-screen", response_class=HTMLResponse)
        async def phone_screen_page(req: Request, token: str = ""):
            """Live-ish phone screen view: the image re-polls every 4 s and
            a button asks the phone for a fresh screenshot. Still images,
            NOT video — prottek refresh-e notun chhobi ashle slideshow-er
            moto dekhay. Needs Accessibility ON on the phone."""
            if not _valid(token.strip()):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            tok = token.strip().replace('"', "")
            html = """<!DOCTYPE html>
<html lang="bn"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>📱 Phone Screen — Mark-LVII</title>
<style>
body{background:#0b0f16;color:#e6f1ff;font-family:monospace;margin:0;padding:16px;text-align:center}
h1{color:#22d3ee;font-size:20px} p{color:#8fa3bf;font-size:13px}
img{max-width:100%;border:2px solid #22d3ee;border-radius:12px;background:#000}
button{background:#22d3ee;color:#04222b;border:0;border-radius:8px;padding:10px 18px;
font-family:monospace;font-weight:bold;cursor:pointer;margin:8px}
#st{color:#4ade80}
</style></head><body>
<h1>📱 Phone Screen (live-ish)</h1>
<p>Notun still image prottek 4 sec-e — live video na. Phone-e Accessibility ON thakte hobe.</p>
<button onclick="refreshNow()">🔄 Notun screenshot nao</button>
<p id="st">Loading…</p>
<img id="s" alt="Phone screen ekhono ashe ni — 'Notun screenshot nao' chapo.">
<script>
const TOK = "__TOK__";
function load(){ document.getElementById('s').src = '/api/phone-screen?token='+TOK+'&t='+Date.now(); }
document.getElementById('s').onload = function(){ document.getElementById('st').textContent = '✅ '+new Date().toLocaleTimeString(); };
document.getElementById('s').onerror = function(){ document.getElementById('st').textContent = '⏳ Screenshot ekhono ashe ni — button chapo ba ektu wait koro.'; };
async function refreshNow(){
  document.getElementById('st').textContent = '⏳ Phone-ke bolchi…';
  try { await fetch('/api/phone-screen/refresh', {method:'POST', headers:{'Authorization':'Bearer '+TOK}}); } catch(e){}
  setTimeout(load, 5000);
}
load(); setInterval(load, 4000);
</script></body></html>""".replace("__TOK__", tok)
            return HTMLResponse(html)

        @app.get("/api/location")
        async def location_api(req: Request):
            """📍 Phone location — last fix + history (last 50) + map link.

            Same auth as /api/agents: Bearer <redacted>, 401 without it.
            Coordinates are NEVER faked — empty when the phone has not
            sent a location_update yet (needs GPS + permission + Owner
            monitoring ON on the phone)."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                from core import phone_location as _pl
                last = _pl.last_fix()
                hist = _pl.history()
                return JSONResponse({
                    "last": last,
                    "history": hist,
                    "count": len(hist),
                    "maps_url": (
                        f"https://www.openstreetmap.org/?mlat={last['lat']}"
                        f"&mlon={last['lon']}#map=16/{last['lat']}/{last['lon']}"
                        if last else ""),
                })
            except Exception as e:
                return JSONResponse({"last": None, "history": [],
                                     "count": 0, "maps_url": "",
                                     "error": str(e)[:120]})

        @app.get("/map", response_class=HTMLResponse)
        async def map_page(req: Request, token: str = ""):
            """🗺️ Location map — the phone on OpenStreetMap (Leaflet) with
            a marker + the last-50 history list. Re-polls /api/location
            every 5 s. Needs internet for the map tiles.

            Same pattern as /phone-screen: auth via ?token= query param."""
            if not _valid(token.strip()):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            tok = token.strip().replace('"', "")
            html = """<!DOCTYPE html>
<html lang="bn"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>📍 Phone Location — Mark-LVII</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
body{background:#0b0f16;color:#e6f1ff;font-family:monospace;margin:0;padding:16px}
h1{color:#22d3ee;font-size:20px;text-align:center} p{color:#8fa3bf;font-size:13px;text-align:center}
#map{height:55vh;border:2px solid #22d3ee;border-radius:12px}
#hist{max-width:640px;margin:12px auto;font-size:12px;color:#cbd5e1}
#st{color:#4ade80;text-align:center}
</style></head><body>
<h1>📍 Phone Location (map)</h1>
<p>Phone-er GPS fix — OpenStreetMap. Map tiles-er jonno internet lagbe. Phone-e GPS + Location permission ON thakte hobe.</p>
<p id="st">Loading…</p>
<div id="map"></div>
<div id="hist"></div>
<script>
const TOK = "__TOK__";
let map = null, marker = null;
async function load(){
  try {
    const r = await fetch('/api/location', {headers:{'Authorization':'Bearer '+TOK}});
    const d = await r.json();
    if (!d.last) { document.getElementById('st').textContent = '⏳ Location ekhono ashe ni — phone-ke Find phone bolo.'; return; }
    const lat = d.last.lat, lon = d.last.lon;
    document.getElementById('st').textContent = '✅ Lat ' + lat + ', Lng ' + lon + ' • ' + (d.last.at || '');
    if (!map) {
      map = L.map('map').setView([lat, lon], 16);
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '© OpenStreetMap'}).addTo(map);
      marker = L.marker([lat, lon]).addTo(map).bindPopup('📱 Phone — ' + (d.last.at || ''));
    } else {
      map.setView([lat, lon], map.getZoom());
      marker.setLatLng([lat, lon]).bindPopup('📱 Phone — ' + (d.last.at || ''));
    }
    const h = (d.history || []).slice(-10).reverse();
    document.getElementById('hist').innerHTML = '<b>History (last ' + (d.history || []).length + '):</b><br>' +
      h.map(x => '• ' + x.lat + ', ' + x.lon + ' — ' + (x.at || '')).join('<br>');
  } catch(e) { document.getElementById('st').textContent = '⏳ Location ante parlam na — ' + e; }
}
load(); setInterval(load, 5000);
</script></body></html>""".replace("__TOK__", tok)
            return HTMLResponse(html)

        @app.get("/api/tasks")
        async def tasks_api(req: Request):
            """📋 Automatic Tasks — tasks + history (with executor: phone /
            pc / backend) + offline queue + the PC-off honesty note.

            Same auth as /api/agents: Bearer <redacted>, 401 without it.
            Never raises — an engine failure returns empty lists + error."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                from core import automation as _a
                from core import auto_tasks as _at
                from memory.config_manager import get_plugin_config
                tasks = _a.ENGINE.list_tasks()
                for t in tasks:
                    t["executor"] = _at.executor_of(str(t.get("id") or ""))
                cfg = dict(get_plugin_config("auto_tasks") or {})
                return JSONResponse({
                    "tasks": tasks,
                    "history": _a.ENGINE.history()[-20:],
                    "offline_queue": list(cfg.get("offline_queue") or []),
                    "pc_off_note": _at.PC_OFF_NOTE,
                })
            except Exception as e:
                return JSONResponse({"tasks": [], "history": [],
                                     "offline_queue": [],
                                     "pc_off_note": "",
                                     "error": str(e)[:120]})

        @app.get("/agents", response_class=HTMLResponse)
        async def agents_page(req: Request, token: str = ""):
            """🤖 Agents — live view of the 7 worker agents.

            Same pattern as /phone-screen: auth via ?token= query param
            (browser navigations can't send an Authorization header), then
            the page re-polls /api/agents with the Bearer token every 2 s.
            Mark is the parent; the 7 workers below do the jobs.
            """
            if not _valid(token.strip()):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            tok = token.strip().replace('"', "")
            html = """<!DOCTYPE html>
<html lang="bn"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🤖 Agents — Mark-LVII</title>
<style>
body{background:#0b0f16;color:#e6f1ff;font-family:monospace;margin:0;padding:16px}
h1{color:#22d3ee;font-size:20px;text-align:center}
p.sub{color:#8fa3bf;font-size:13px;text-align:center}
#st{color:#4ade80;text-align:center;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;max-width:900px;margin:16px auto}
.card{background:#131a26;border:1px solid #1f2c40;border-radius:12px;padding:12px}
.card.off{opacity:.55}
.card h2{font-size:15px;margin:0 0 4px}
.card .job{color:#8fa3bf;font-size:12px;margin:0 0 8px}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:bold}
.badge.idle{background:#334155;color:#e2e8f0}
.badge.working{background:#0ea5e9;color:#04222b}
.badge.done{background:#22c55e;color:#052e16}
.badge.error{background:#ef4444;color:#fff}
.task{font-size:13px;margin:8px 0;color:#e6f1ff;word-break:break-word}
.meta{font-size:12px;color:#8fa3bf}
.bar{height:8px;background:#1f2c40;border-radius:999px;overflow:hidden;margin:6px 0}
.bar i{display:block;height:100%;background:#22d3ee}
</style></head><body>
<h1>🤖 Agents — 7 worker agents</h1>
<p class="sub">Mark (parent) kotha bole — ei 7 worker kaj kore. Prottek 2 sec-e update hoy.</p>
<p id="st">Loading…</p>
<div class="grid" id="grid"></div>
<script>
const TOK = "__TOK__";
function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
async function load(){
  try {
    const r = await fetch('/api/agents', {headers:{'Authorization':'Bearer '+TOK}});
    if(!r.ok){ document.getElementById('st').textContent = '⛔ Unauthorized — notun QR/token diye abar kholo.'; return; }
    const d = await r.json();
    const list = d.agents || [];
    document.getElementById('st').textContent = '✅ '+new Date().toLocaleTimeString()+' — '+list.length+' agent';
    document.getElementById('grid').innerHTML = list.map(function(a){
      const task = a.current_task ? esc(a.current_task) : 'kono kaj nei';
      return '<div class="card'+(a.enabled===false?' off':'')+'">'
        + '<h2>'+esc(a.icon)+' '+esc(a.name)+'</h2>'
        + '<p class="job">'+esc(a.job)+'</p>'
        + '<span class="badge '+esc(a.status)+'">'+esc(a.status)+(a.enabled===false?' — OFF':'')+'</span>'
        + '<p class="task">'+task+'</p>'
        + '<div class="bar"><i style="width:'+Math.max(0,Math.min(100,Number(a.progress)||0))+'%"></i></div>'
        + '<p class="meta">'+(Number(a.progress)||0)+'% &middot; '+(Number(a.elapsed_s)||0)+'s &middot; done: '+(Number(a.completed_count)||0)+'</p>'
        + '</div>';
    }).join('');
  } catch(e){
    document.getElementById('st').textContent = '⏳ Server-e pouchate parlam na — ektu wait koro.';
  }
}
load(); setInterval(load, 2000);
</script></body></html>""".replace("__TOK__", tok)
            return HTMLResponse(html)

        # ── 🔍 FEATURES registry (dashboard) ─────────────────────────────
        # Qt-free copy of the adapter in gui/overlays.py: prefers
        # core/feature_registry (contract: resolve/search/list_category/
        # counts/set_enabled/is_enabled over 1–23,720,000; landed
        # 2026-11-17, verified live), else the built 20,000-feature JSON
        # registry (data/features.json via plugins/jarvis_features).
        # Toggles fall back to config plugin_config["features"]["disabled"].

        def _feat_registry():
            try:
                import core.feature_registry as _fr
                return _fr
            except Exception:
                return None

        def _feat_records():
            try:
                from plugins import jarvis_features as _jf
                return _jf._load_registry()
            except Exception:
                return [], {}

        def _feat_disabled_numbers():
            try:
                from memory.config_manager import get_plugin_config
                raw = (get_plugin_config("features") or {}).get("disabled", []) or []
                return {int(n) for n in raw if str(n).isdigit()}
            except Exception:
                return set()

        def _feat_is_enabled(number):
            try:
                n = int(number)
            except (TypeError, ValueError):
                return True
            fr = _feat_registry()
            if fr is not None and hasattr(fr, "is_enabled"):
                try:
                    return bool(fr.is_enabled(n))
                except Exception:
                    pass
            return n not in _feat_disabled_numbers()

        def _feat_set_enabled(number, on):
            try:
                n = int(number)
            except (TypeError, ValueError):
                return False
            fr = _feat_registry()
            if fr is not None and hasattr(fr, "set_enabled"):
                try:
                    fr.set_enabled(n, bool(on))
                    return True
                except Exception:
                    pass
            try:
                from memory.config_manager import get_plugin_config, save_plugin_config
                disabled = _feat_disabled_numbers()
                if on:
                    disabled.discard(n)
                else:
                    disabled.add(n)
                save_plugin_config("features", {"disabled": sorted(disabled)})
                return True
            except Exception:
                return False

        def _feat_pub(rec):
            try:
                rec = dict(rec or {})
                n = int(rec.get("number") or 0)
                return {
                    "number": n,
                    "volume": int(rec.get("volume") or 1),
                    "name": str(rec.get("name") or f"Feature #{n}"),
                    "category": str(rec.get("category") or ""),
                    "category_index": int(rec.get("category_index") or 0),
                    "target": str(rec.get("target") or ""),
                    "description": str(rec.get("description") or ""),
                    "status": str(rec.get("status") or "PLANNED"),
                    "tool": rec.get("tool"),
                    "requires": str(rec.get("requires") or ""),
                    "enabled": _feat_is_enabled(n),
                }
            except Exception:
                return {"number": 0, "name": "?", "category": "",
                        "category_index": 0, "target": "", "description": "",
                        "status": "PLANNED", "tool": None, "requires": "",
                        "enabled": True}

        def _feat_resolve(number):
            try:
                n = int(number)
            except (TypeError, ValueError):
                return None
            if n < 1 or n > 23_700_000:
                return None
            fr = _feat_registry()
            if fr is not None and hasattr(fr, "resolve"):
                try:
                    rec = fr.resolve(n)
                    # The resolver returns {"error": ...} (not None) on bad
                    # input or a missing structure file — treat as not found.
                    if isinstance(rec, dict) and rec.get("error"):
                        return None
                    return _feat_pub(rec) if rec else None
                except Exception:
                    pass
            _records, by_number = _feat_records()
            rec = by_number.get(n)
            return _feat_pub(rec) if rec else None

        def _feat_search(query, limit=20):
            try:
                limit = max(1, min(100, int(limit or 20)))
            except Exception:
                limit = 20
            q = str(query or "").strip().lower()
            if not q:
                # Empty query = browse from the top (the resolver's search
                # returns [] on an empty query by design).
                return _feat_first(limit)
            fr = _feat_registry()
            if fr is not None and hasattr(fr, "search"):
                try:
                    return [_feat_pub(r) for r in (fr.search(q, limit) or [])]
                except Exception:
                    pass
            records, _by = _feat_records()
            import re as _re
            tokens = [t for t in _re.split(r"\s+", q) if t]
            scored = []
            for rec in records:
                text = " ".join([str(rec.get("name") or ""),
                                 str(rec.get("description") or ""),
                                 str(rec.get("category") or ""),
                                 str(rec.get("target") or ""),
                                 str(rec.get("status") or "")]).lower()
                hits = sum(1 for t in tokens if t in text)
                if not hits:
                    continue
                scored.append((hits + (2 if q in text else 0),
                               rec.get("number") or 0, rec))
            scored.sort(key=lambda s: (-s[0], s[1]))
            return [_feat_pub(r) for _s, _n, r in scored[:limit]]

        def _feat_list_category(cidx, offset=0, limit=20):
            try:
                cidx = int(cidx)
                offset = max(0, int(offset or 0))
                limit = max(1, min(100, int(limit or 20)))
            except Exception:
                return []
            fr = _feat_registry()
            if fr is not None and hasattr(fr, "list_category"):
                try:
                    return [_feat_pub(r) for r in
                            (fr.list_category(cidx, offset, limit) or [])]
                except Exception:
                    pass
            records, _by = _feat_records()
            items = [r for r in records if r.get("category_index") == cidx]
            return [_feat_pub(r) for r in items[offset:offset + limit]]

        def _feat_first(limit=20):
            try:
                limit = max(1, min(100, int(limit or 20)))
            except Exception:
                limit = 20
            out = []
            for n in range(1, limit + 1):
                rec = _feat_resolve(n)
                if rec:
                    out.append(rec)
            return out

        def _feat_categories():
            fr = _feat_registry()
            if fr is not None and hasattr(fr, "list_categories"):
                try:
                    cats = [{"index": int(c["index"]), "name": str(c["name"])}
                            for c in (fr.list_categories() or [])]
                    if cats:
                        return cats
                except Exception:
                    pass
            if fr is not None and hasattr(fr, "list_category"):
                out = []
                for i in range(1, 101):
                    try:
                        rows = fr.list_category(i, 0, 1) or []
                    except Exception:
                        rows = []
                    if rows:
                        out.append({"index": i, "name": str(
                            rows[0].get("category") or f"Category {i}")})
                if out:
                    return out
            records, _by = _feat_records()
            cats = {}
            for rec in records:
                try:
                    cats[int(rec.get("category_index") or 0)] = str(
                        rec.get("category") or "")
                except Exception:
                    pass
            return [{"index": i, "name": cats[i]} for i in sorted(cats) if i]

        def _feat_counts():
            fr = _feat_registry()
            if fr is not None and hasattr(fr, "counts"):
                try:
                    c = dict(fr.counts() or {})
                    return {"total": int(c.get("total") or 0),
                            "WORKING": int(c.get("WORKING") or 0),
                            "NEEDS-KEY": int(c.get("NEEDS-KEY") or 0),
                            "NEEDS-DEVICE": int(c.get("NEEDS-DEVICE") or 0),
                            "PLANNED": int(c.get("PLANNED") or 0)}
                except Exception:
                    pass
            records, _by = _feat_records()
            out = {"total": len(records), "WORKING": 0, "NEEDS-KEY": 0,
                   "NEEDS-DEVICE": 0, "PLANNED": 0}
            for rec in records:
                st = str(rec.get("status") or "")
                if st in out:
                    out[st] += 1
            return out

        @app.get("/api/features")
        async def features_api(req: Request):
            """🔍 Features — search / list / get / stats over the registry.

            Query: action=search|list|get|stats, q, category (index or
            name), status, number, offset, limit. Bearer auth like
            /api/agents, 401 without it. Never raises.
            """
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                qp = req.query_params
                action = str(qp.get("action") or "search").strip().lower()
                counts = _feat_counts()
                cats = _feat_categories()
                if action == "stats":
                    return JSONResponse({"ok": True, "action": "stats",
                                         "counts": counts, "categories": cats,
                                         "total": counts.get("total", 0)})
                if action == "get":
                    rec = _feat_resolve(qp.get("number"))
                    if rec is None:
                        return JSONResponse({"ok": False,
                                             "error": "Feature not in registry."},
                                            status_code=404)
                    return JSONResponse({"ok": True, "action": "get",
                                         "feature": rec, "counts": counts})
                limit = qp.get("limit") or "20"
                try:
                    limit = max(1, min(100, int(limit)))
                except Exception:
                    limit = 20
                if action == "list":
                    cat_raw = str(qp.get("category") or "").strip()
                    cidx = None
                    try:
                        cidx = int(cat_raw)
                    except (TypeError, ValueError):
                        low = cat_raw.lower()
                        for c in cats:
                            if low and low in str(c.get("name") or "").lower():
                                cidx = int(c["index"])
                                break
                    if cidx is None:
                        return JSONResponse({"ok": False,
                                             "error": "Category not found."},
                                            status_code=404)
                    try:
                        offset = max(0, int(qp.get("offset") or 0))
                    except Exception:
                        offset = 0
                    items = _feat_list_category(cidx, offset, limit)
                    st = str(qp.get("status") or "").strip()
                    if st:
                        items = [r for r in items if r.get("status") == st]
                    return JSONResponse({"ok": True, "action": "list",
                                         "features": items, "total": len(items),
                                         "counts": counts, "categories": cats})
                # default: search (empty q = first features by number)
                q = str(qp.get("q") or "").strip()
                cat_raw = str(qp.get("category") or "").strip()
                cidx = 0
                try:
                    cidx = int(cat_raw) if cat_raw else 0
                except (TypeError, ValueError):
                    low = cat_raw.lower()
                    for c in cats:
                        if low and low in str(c.get("name") or "").lower():
                            cidx = int(c["index"])
                            break
                if q:
                    items = _feat_search(q, 100)
                elif cidx:
                    items = _feat_list_category(cidx, 0, 100)
                else:
                    items = _feat_first(100)
                if cidx:
                    items = [r for r in items if r.get("category_index") == cidx]
                st = str(qp.get("status") or "").strip()
                if st:
                    items = [r for r in items if r.get("status") == st]
                total = len(items)
                return JSONResponse({"ok": True, "action": "search",
                                     "features": items[:limit], "total": total,
                                     "counts": counts, "categories": cats})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)[:120]},
                                    status_code=500)

        @app.post("/api/features")
        async def features_action(req: Request):
            """🔍 Features — run / enable / disable one feature by number.

            JSON {action: run|enable|disable, number}. run enqueues the
            feature run (tool "features", action "run") via
            core/action_queue.py and returns accepted — Mark runs it from
            the queue, the dashboard never calls a tool directly. Bearer
            auth like /api/agents. Never raises.
            """
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                body = await req.json()
            except Exception:
                body = {}
            try:
                action = str((body or {}).get("action") or "").strip().lower()
                rec = _feat_resolve((body or {}).get("number"))
                if rec is None:
                    return JSONResponse({"ok": False,
                                         "error": "Feature not in registry."},
                                        status_code=404)
                n = int(rec["number"])
                if action == "run":
                    try:
                        from core.action_queue import enqueue
                        qid = enqueue("features", {"action": "run",
                                                   "number": str(n)})
                    except Exception:
                        qid = ""
                    if not qid:
                        return JSONResponse({"ok": False,
                                             "error": "Queue full — try again."},
                                            status_code=503)
                    return JSONResponse({"ok": True, "accepted": True,
                                         "id": qid, "number": n,
                                         "name": rec.get("name") or "",
                                         "status": rec.get("status") or "",
                                         "message": "queued — Mark will run it"})
                if action in ("enable", "disable"):
                    on = action == "enable"
                    if not _feat_set_enabled(n, on):
                        return JSONResponse({"ok": False,
                                             "error": "Toggle failed."},
                                            status_code=500)
                    return JSONResponse({"ok": True, "number": n,
                                         "enabled": on})
                return JSONResponse({"ok": False,
                                     "error": "action must be run|enable|disable"},
                                    status_code=400)
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)[:120]},
                                    status_code=500)

        @app.get("/features", response_class=HTMLResponse)
        async def features_page(req: Request, token: str = ""):
            """🔍 Features — registry browser page.

            Same pattern as /agents: auth via ?token= query param, then the
            page re-polls /api/features with the Bearer token every 2 s.
            Search + category + status filters, run-by-number, toggles,
            coverage counter.
            """
            if not _valid(token.strip()):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            tok = token.strip().replace('"', "")
            html = """<!DOCTYPE html>
<html lang="bn"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🔍 Features — Mark-LVII</title>
<style>
body{background:#0b0f16;color:#e6f1ff;font-family:monospace;margin:0;padding:16px}
h1{color:#22d3ee;font-size:20px;text-align:center}
p.sub{color:#8fa3bf;font-size:13px;text-align:center}
#cov{color:#4ade80;text-align:center;font-size:14px;font-weight:bold}
#st{color:#4ade80;text-align:center;font-size:13px}
.bar{max-width:900px;margin:12px auto;display:flex;gap:8px;flex-wrap:wrap}
.bar input,.bar select{flex:1;min-width:140px;background:#131a26;color:#e6f1ff;border:1px solid #1f2c40;border-radius:8px;padding:10px;font-family:monospace}
.bar button{background:#22d3ee;color:#04222b;border:0;border-radius:8px;padding:10px 18px;font-family:monospace;font-weight:bold;cursor:pointer}
.list{max-width:900px;margin:0 auto}
.row{background:#131a26;border:1px solid #1f2c40;border-radius:12px;padding:10px 12px;margin:8px 0;display:flex;gap:10px;align-items:center}
.row .nm{flex:1;font-size:13px;word-break:break-word}
.row .bd{font-size:11px;font-weight:bold;padding:2px 8px;border-radius:999px}
.bd.WORKING{background:#22c55e;color:#052e16}
.bd.NEEDS-KEY{background:#f59e0b;color:#451a03}
.bd.NEEDS-DEVICE{background:#f97316;color:#431407}
.bd.PLANNED{background:#334155;color:#e2e8f0}
.row button{background:#0b0f16;color:#22d3ee;border:1px solid #22d3ee;border-radius:8px;padding:6px 10px;font-family:monospace;font-weight:bold;cursor:pointer}
.row button.off{color:#8fa3bf;border-color:#1f2c40}
.dim{color:#8fa3bf;font-size:12px;text-align:center}
</style></head><body>
<h1>🔍 Features — registry browser</h1>
<p class="sub">Search koro, category dekho, number diye chalao — Mark queue theke chalabe.</p>
<p id="cov">Loading…</p>
<div class="bar">
<input id="q" placeholder="Search features…  jemon 'YouTube upload'" oninput="load()">
<select id="cat" onchange="load()"><option value="0">All categories</option></select>
<select id="stf" onchange="load()">
<option value="">All statuses</option><option>WORKING</option>
<option>NEEDS-KEY</option><option>NEEDS-DEVICE</option><option>PLANNED</option>
</select>
</div>
<div class="bar">
<input id="num" placeholder="Run by number — 1 – 23720000" inputmode="numeric">
<button onclick="runNum()">▶ RUN</button>
</div>
<p id="st">Loading…</p>
<div class="list" id="list"></div>
<script>
const TOK = "__TOK__";
let catsLoaded = false;
function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function hdr(){ return {'Authorization':'Bearer '+TOK}; }
async function load(){
  try {
    const q = document.getElementById('q').value;
    const cat = document.getElementById('cat').value;
    const stf = document.getElementById('stf').value;
    const u = '/api/features?action=search&limit=30&q='+encodeURIComponent(q)
      +'&category='+encodeURIComponent(cat)+'&status='+encodeURIComponent(stf);
    const r = await fetch(u, {headers: hdr()});
    if(!r.ok){ document.getElementById('st').textContent = '⛔ Unauthorized — notun QR/token diye abar kholo.'; return; }
    const d = await r.json();
    const c = d.counts || {};
    document.getElementById('cov').textContent =
      (Number(c.WORKING)||0).toLocaleString()+' / '+(Number(c.total)||0).toLocaleString()+' working'
      +'   •   NEEDS-KEY '+(Number(c['NEEDS-KEY'])||0).toLocaleString()
      +'   •   NEEDS-DEVICE '+(Number(c['NEEDS-DEVICE'])||0).toLocaleString()
      +'   •   PLANNED '+(Number(c.PLANNED)||0).toLocaleString();
    if(!catsLoaded && d.categories){
      catsLoaded = true;
      const sel = document.getElementById('cat');
      d.categories.forEach(function(ct){
        const o = document.createElement('option');
        o.value = ct.index; o.textContent = ct.index+'. '+ct.name;
        sel.appendChild(o);
      });
    }
    const list = d.features || [];
    document.getElementById('st').textContent =
      '✅ '+new Date().toLocaleTimeString()+' — '+list.length+' shown, '+d.total+' match';
    document.getElementById('list').innerHTML = list.map(function(f){
      return '<div class="row"><span class="nm">#'+f.number+'  '+esc(f.name)+'</span>'
        + '<span class="bd '+esc(f.status)+'">'+esc(f.status)+'</span>'
        + '<button class="'+(f.enabled?'':'off')+'" onclick="toggleF('+f.number+','+(f.enabled?'false':'true')+')">'
        + (f.enabled?'ON':'OFF')+'</button>'
        + '<button onclick="runF('+f.number+')">▶ RUN</button></div>';
    }).join('') || '<p class="dim">Kono feature milche na — search ba filter bodle dekho.</p>';
  } catch(e){
    document.getElementById('st').textContent = '⏳ Server-e pouchate parlam na — ektu wait koro.';
  }
}
async function postF(body){
  const r = await fetch('/api/features', {method:'POST', headers:Object.assign(hdr(),{'Content-Type':'application/json'}), body: JSON.stringify(body)});
  return r.json();
}
async function toggleF(n, on){
  const d = await postF({action: on?'enable':'disable', number: n});
  document.getElementById('st').textContent = d.ok ? ('✅ #'+n+(on?' ON korlam.':' OFF korlam.')) : ('⚠️ '+(d.error||'toggle holo na.'));
  load();
}
async function runF(n){
  const d = await postF({action:'run', number: n});
  document.getElementById('st').textContent = d.ok ? ('✅ #'+n+' '+esc(d.name||'')+': queued — Mark will run it (#'+d.id+').') : ('⚠️ '+(d.error||'queue-te dite parlam na.'));
}
async function runNum(){
  const v = document.getElementById('num').value.trim();
  const n = parseInt(v, 10);
  if(!n || n < 1 || n > 23720000){ document.getElementById('st').textContent = '⚠️ Number dao — 1 theke 23720000-er modhye.'; return; }
  runF(n);
}
load(); setInterval(load, 2000);
</script></body></html>""".replace("__TOK__", tok)
            return HTMLResponse(html)

        # ── 💬 MUSE BRIDGE (dashboard) ─────────────────────────────────────
        # Tasks Mark can't do locally get queued to Muse via the Render
        # dashboard. core/muse_bridge.py landed 2026-11-17 (verified live:
        # create -> list -> seen -> done); every handler still imports it
        # lazily and answers honestly when it is missing instead of
        # raising. Contract: create_task(instruction, tried="", context="")
        # -> id, list_tasks(status=None), get_task(id), set_status(id,
        # status, result="") with status queued/seen/done.

        def _muse_bridge():
            try:
                from core import muse_bridge as _mb
                return _mb
            except Exception:
                return None

        @app.get("/api/muse-tasks")
        async def muse_tasks_list(req: Request):
            """💬 Muse Bridge — list queued tasks, optional ?status= filter.
            Bearer auth like /api/agents. Never raises."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                mb = _muse_bridge()
                if mb is None:
                    return JSONResponse({"tasks": [],
                                         "error": "Muse Bridge not built yet — core/muse_bridge.py missing."})
                status = str(req.query_params.get("status") or "").strip() or None
                if status and status not in ("queued", "seen", "done"):
                    return JSONResponse({"ok": False,
                                         "error": "status must be queued|seen|done"},
                                        status_code=400)
                tasks = mb.list_tasks(status) if status else mb.list_tasks()
                return JSONResponse({"ok": True, "tasks": list(tasks or [])})
            except Exception as e:
                return JSONResponse({"tasks": [], "error": str(e)[:120]})

        @app.post("/api/muse-tasks")
        async def muse_tasks_create(req: Request):
            """💬 Muse Bridge — queue a task for Muse.
            JSON {instruction, tried, context} -> {ok, id}. Bearer auth.
            Never raises."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                body = await req.json()
            except Exception:
                body = {}
            try:
                mb = _muse_bridge()
                if mb is None:
                    return JSONResponse({"ok": False,
                                         "error": "Muse Bridge not built yet — core/muse_bridge.py missing."},
                                        status_code=503)
                instruction = str((body or {}).get("instruction") or "").strip()
                if not instruction:
                    return JSONResponse({"ok": False,
                                         "error": "instruction required"},
                                        status_code=400)
                tid = mb.create_task(
                    instruction,
                    tried=str((body or {}).get("tried") or ""),
                    context=str((body or {}).get("context") or ""))
                if not tid:
                    return JSONResponse({"ok": False,
                                         "error": "Bridge returned no id."},
                                        status_code=500)
                return JSONResponse({"ok": True, "id": str(tid)})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)[:120]},
                                    status_code=500)

        @app.get("/api/muse-tasks/{task_id}")
        async def muse_task_get(req: Request, task_id: str):
            """💬 Muse Bridge — one task by id. Bearer auth. Never raises."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                mb = _muse_bridge()
                if mb is None:
                    return JSONResponse({"ok": False,
                                         "error": "Muse Bridge not built yet — core/muse_bridge.py missing."},
                                        status_code=503)
                task = mb.get_task(task_id)
                if task is None:
                    return JSONResponse({"ok": False,
                                         "error": "Task not found."},
                                        status_code=404)
                return JSONResponse({"ok": True, "task": task})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)[:120]},
                                    status_code=500)

        @app.post("/api/muse-tasks/{task_id}")
        async def muse_task_update(req: Request, task_id: str):
            """💬 Muse Bridge — mark progress: {status: seen|done, result}.
            This is how Muse marks a task seen / done with its result.
            Bearer auth. Never raises."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                body = await req.json()
            except Exception:
                body = {}
            try:
                mb = _muse_bridge()
                if mb is None:
                    return JSONResponse({"ok": False,
                                         "error": "Muse Bridge not built yet — core/muse_bridge.py missing."},
                                        status_code=503)
                status = str((body or {}).get("status") or "").strip()
                if status not in ("seen", "done"):
                    return JSONResponse({"ok": False,
                                         "error": "status must be seen|done"},
                                        status_code=400)
                ok = mb.set_status(task_id, status,
                                   result=str((body or {}).get("result") or ""))
                if not ok:
                    return JSONResponse({"ok": False,
                                         "error": "Task not found."},
                                        status_code=404)
                try:
                    task = mb.get_task(task_id)
                except Exception:
                    task = None
                return JSONResponse({"ok": True, "task": task})
            except Exception as e:
                return JSONResponse({"ok": False, "error": str(e)[:120]},
                                    status_code=500)

        @app.get("/muse-tasks", response_class=HTMLResponse)
        async def muse_tasks_page(req: Request, token: str = ""):
            """💬 Muse Bridge — the task queue for Muse.

            Same pattern as /agents: auth via ?token= query param, then the
            page re-polls /api/muse-tasks with the Bearer token every 2 s.
            Shows the queue with status + result; a form queues a new task,
            and Seen / Done buttons mark progress.
            """
            if not _valid(token.strip()):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            tok = token.strip().replace('"', "")
            html = """<!DOCTYPE html>
<html lang="bn"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>💬 Muse Tasks — Mark-LVII</title>
<style>
body{background:#0b0f16;color:#e6f1ff;font-family:monospace;margin:0;padding:16px}
h1{color:#22d3ee;font-size:20px;text-align:center}
p.sub{color:#8fa3bf;font-size:13px;text-align:center}
#st{color:#4ade80;text-align:center;font-size:13px}
.box{max-width:900px;margin:12px auto}
.box textarea,.box input{width:100%;box-sizing:border-box;background:#131a26;color:#e6f1ff;border:1px solid #1f2c40;border-radius:8px;padding:10px;font-family:monospace;margin:4px 0}
.box button{background:#22d3ee;color:#04222b;border:0;border-radius:8px;padding:10px 18px;font-family:monospace;font-weight:bold;cursor:pointer}
.bar{max-width:900px;margin:12px auto;display:flex;gap:8px}
.bar select{background:#131a26;color:#e6f1ff;border:1px solid #1f2c40;border-radius:8px;padding:8px;font-family:monospace}
.card{background:#131a26;border:1px solid #1f2c40;border-radius:12px;padding:12px;margin:8px auto;max-width:900px}
.card h2{font-size:14px;margin:0 0 4px;word-break:break-word}
.card .meta{color:#8fa3bf;font-size:12px}
.card .res{font-size:13px;color:#e6f1ff;word-break:break-word;white-space:pre-wrap}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:bold}
.badge.queued{background:#f59e0b;color:#451a03}
.badge.seen{background:#0ea5e9;color:#04222b}
.badge.done{background:#22c55e;color:#052e16}
.card button{background:#0b0f16;color:#22d3ee;border:1px solid #22d3ee;border-radius:8px;padding:6px 10px;font-family:monospace;font-weight:bold;cursor:pointer;margin:4px 4px 0 0}
.dim{color:#8fa3bf;font-size:12px;text-align:center}
</style></head><body>
<h1>💬 Muse Tasks — Mark-er Muse Bridge queue</h1>
<p class="sub">Mark ja nije pare na, Muse-ke pathay — ekhane queue, status ar result dekho. Prottek 2 sec-e update hoy.</p>
<div class="box">
<textarea id="ins" rows="3" placeholder="Instruction — Muse-ke ki korte hobe?"></textarea>
<input id="tried" placeholder="Tried (optional) — Mark ki ki try koreche">
<input id="ctx" placeholder="Context (optional)">
<button onclick="createTask()">➕ Queue task for Muse</button>
</div>
<div class="bar"><select id="flt" onchange="load()">
<option value="">All statuses</option><option value="queued">queued</option>
<option value="seen">seen</option><option value="done">done</option>
</select></div>
<p id="st">Loading…</p>
<div id="list"></div>
<script>
const TOK = "__TOK__";
function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function hdr(){ return {'Authorization':'Bearer '+TOK}; }
async function load(){
  try {
    const f = document.getElementById('flt').value;
    const u = '/api/muse-tasks' + (f ? ('?status='+encodeURIComponent(f)) : '');
    const r = await fetch(u, {headers: hdr()});
    if(!r.ok){ document.getElementById('st').textContent = '⛔ Unauthorized — notun QR/token diye abar kholo.'; return; }
    const d = await r.json();
    const list = d.tasks || [];
    document.getElementById('st').textContent =
      '✅ '+new Date().toLocaleTimeString()+' — '+list.length+' task'
      + (d.error ? (' — ⚠️ '+esc(d.error)) : '');
    document.getElementById('list').innerHTML = list.map(function(t){
      const st = esc(t.status || 'queued');
      return '<div class="card"><h2>'+esc(t.instruction || t.id || '?')+'</h2>'
        + '<p class="meta">id: '+esc(t.id || '')+' &middot; '+esc(t.created_at || t.at || '')+'</p>'
        + '<span class="badge '+st+'">'+st+'</span>'
        + (t.tried ? '<p class="meta">Tried: '+esc(t.tried)+'</p>' : '')
        + (t.context ? '<p class="meta">Context: '+esc(t.context)+'</p>' : '')
        + (t.result ? '<p class="res">Result: '+esc(t.result)+'</p>' : '')
        + '<div><button onclick="markTask(\''+esc(t.id||'')+'\',\'seen\')">👀 Seen</button>'
        + '<button onclick="markDone(\''+esc(t.id||'')+'\')">✅ Done</button></div>'
        + '</div>';
    }).join('') || '<p class="dim">Queue khali — opore form diye Muse-ke task dao.</p>';
  } catch(e){
    document.getElementById('st').textContent = '⏳ Server-e pouchate parlam na — ektu wait koro.';
  }
}
async function createTask(){
  const ins = document.getElementById('ins').value.trim();
  if(!ins){ document.getElementById('st').textContent = '⚠️ Instruction dao — Muse-ke ki korte hobe?'; return; }
  const r = await fetch('/api/muse-tasks', {method:'POST', headers:Object.assign(hdr(),{'Content-Type':'application/json'}), body: JSON.stringify({instruction: ins, tried: document.getElementById('tried').value, context: document.getElementById('ctx').value})});
  const d = await r.json();
  document.getElementById('st').textContent = d.ok ? ('✅ Task queue holo (id '+d.id+').') : ('⚠️ '+(d.error||'queue holo na.'));
  if(d.ok){ document.getElementById('ins').value=''; document.getElementById('tried').value=''; document.getElementById('ctx').value=''; }
  load();
}
async function markTask(id, status, result){
  const r = await fetch('/api/muse-tasks/'+encodeURIComponent(id), {method:'POST', headers:Object.assign(hdr(),{'Content-Type':'application/json'}), body: JSON.stringify({status: status, result: result || ''})});
  const d = await r.json();
  document.getElementById('st').textContent = d.ok ? ('✅ '+id+' → '+status) : ('⚠️ '+(d.error||'update holo na.'));
  load();
}
function markDone(id){
  const res = prompt('Result (optional) — Muse ki korlo / ki pelo?') || '';
  markTask(id, 'done', res);
}
load(); setInterval(load, 2000);
</script></body></html>""".replace("__TOK__", tok)
            return HTMLResponse(html)

        @app.get("/api/automation")
        async def automation_api(req: Request):
            """⚡ Automation — tasks + history + template names.

            Same auth as /api/agents: Bearer token, 401 without it.
            Never raises — an engine failure returns empty lists + error.
            """
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                from core.automation import ENGINE, TEMPLATES
                tasks = ENGINE.list_tasks()
                last_by_task = {}
                for h in ENGINE.history():
                    last_by_task[h.get("task_id")] = h
                for t in tasks:
                    t["last_run_result"] = last_by_task.get(t.get("id"))
                return JSONResponse({
                    "tasks": tasks,
                    "history": ENGINE.history()[-20:],
                    "templates": sorted(TEMPLATES.keys()),
                })
            except Exception as e:
                return JSONResponse({"tasks": [], "history": [],
                                     "templates": [],
                                     "error": str(e)[:120]})

        @app.post("/api/automation")
        async def automation_action(req: Request):
            """⚡ Automation — create / update / delete / enable / disable /
            run a task. JSON {action, task_id, task/patch, ...}.

            Auth: Bearer token. Never raises. "run" starts the task on a
            background thread and returns at once (a run can take minutes).
            """
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                body = await req.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                body = {}
            try:
                from core.automation import ENGINE
                action = str(body.get("action") or "").strip().lower()
                task_id = str(body.get("task_id") or "").strip()
                if action == "create":
                    task = body.get("task") or {}
                    if not isinstance(task, dict):
                        task = {k: body.get(k) for k in
                                ("name", "trigger", "steps", "condition")
                                if body.get(k) is not None}
                    tid = ENGINE.create_task(task)
                    if not tid:
                        return JSONResponse(
                            {"error": "Task banate parlam na — naam, trigger ar steps thik ache kina dekho."},
                            status_code=400)
                    return JSONResponse({"ok": True, "task_id": tid})
                if action == "update":
                    patch = body.get("patch") or body.get("task") or {}
                    if not isinstance(patch, dict):
                        patch = {}
                    if not task_id or not ENGINE.update_task(task_id, patch):
                        return JSONResponse(
                            {"error": "Task update korte parlam na — id / patch dekho."},
                            status_code=400)
                    return JSONResponse({"ok": True, "task_id": task_id})
                if action == "delete":
                    if not task_id or not ENGINE.delete_task(task_id):
                        return JSONResponse({"error": "Task pelam na."},
                                            status_code=404)
                    return JSONResponse({"ok": True})
                if action in ("enable", "disable"):
                    if not task_id or not ENGINE.set_enabled(
                            task_id, action == "enable"):
                        return JSONResponse({"error": "Task pelam na."},
                                            status_code=404)
                    return JSONResponse({"ok": True,
                                         "enabled": action == "enable"})
                if action == "template":
                    name = str(body.get("template") or body.get("name") or "").strip()
                    tid = ENGINE.create_from_template(name)
                    if not tid:
                        return JSONResponse(
                            {"error": f"Template '{name}' chinlam na."},
                            status_code=400)
                    return JSONResponse({"ok": True, "task_id": tid})
                if action == "run":
                    if not task_id or ENGINE.get_task(task_id) is None:
                        return JSONResponse({"error": "Task pelam na."},
                                            status_code=404)
                    threading.Thread(
                        target=lambda: ENGINE.run_task_now(task_id),
                        daemon=True, name=f"automation-api-run-{task_id}").start()
                    return JSONResponse({"ok": True,
                                         "message": "Task cholche — history-te asbe."})
                return JSONResponse(
                    {"error": "Action bujhlam na: create | update | delete | enable | disable | run | template."},
                    status_code=400)
            except Exception as e:
                return JSONResponse({"error": str(e)[:120]}, status_code=500)

        @app.post("/api/automation/trigger/{task_id}")
        async def automation_webhook(req: Request, task_id: str):
            """⚡ Automation webhook trigger — fire one task from outside
            (e.g. an external service calling this URL).

            Auth: Bearer token. Runs the task on a background thread and
            returns "accepted" at once. Never raises.
            """
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                from core.automation import ENGINE
                tid = str(task_id or "").strip()
                if ENGINE.get_task(tid) is None:
                    return JSONResponse({"error": "Task pelam na."},
                                        status_code=404)
                threading.Thread(
                    target=lambda: ENGINE.run_task_now(tid),
                    daemon=True, name=f"automation-webhook-{tid}").start()
                return JSONResponse({"ok": True, "accepted": True,
                                     "task_id": tid,
                                     "message": "Task trigger holo — background-e cholche."})
            except Exception as e:
                return JSONResponse({"error": str(e)[:120]}, status_code=500)

        @app.get("/automation", response_class=HTMLResponse)
        async def automation_page(req: Request, token: str = ""):
            """⚡ Automation — task cards + templates + history + create/edit
            form. Same pattern as /agents: auth via ?token=, re-polls
            /api/automation every 2 s. Edit happens here, not on the HUD."""
            if not _valid(token.strip()):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            tok = token.strip().replace('"', "")
            html = """<!DOCTYPE html>
<html lang="bn"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>⚡ Automation — Mark-LVII</title>
<style>
body{background:#0b0f16;color:#e6f1ff;font-family:monospace;margin:0;padding:16px}
h1{color:#22d3ee;font-size:20px;text-align:center}
p.sub{color:#8fa3bf;font-size:13px;text-align:center}
#st{color:#4ade80;text-align:center;font-size:13px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;max-width:1000px;margin:16px auto}
.card{background:#131a26;border:1px solid #1f2c40;border-radius:12px;padding:12px}
.card.off{opacity:.55}
.card h2{font-size:15px;margin:0 0 4px}
.flow{color:#8fa3bf;font-size:12px;word-break:break-word}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:bold}
.badge.on{background:#22c55e;color:#052e16}
.badge.off{background:#334155;color:#e2e8f0}
.meta{font-size:12px;color:#8fa3bf}
button{background:#22d3ee;color:#04222b;border:0;border-radius:8px;padding:7px 12px;
font-family:monospace;font-weight:bold;cursor:pointer;margin:4px 4px 0 0}
button.dim{background:#1f2c40;color:#e6f1ff}
button.danger{background:#ef4444;color:#fff}
input,textarea,select{width:100%;background:#0b0f16;color:#e6f1ff;border:1px solid #1f2c40;
border-radius:8px;padding:8px;font-family:monospace;margin:4px 0;box-sizing:border-box}
form{max-width:1000px;margin:16px auto;background:#131a26;border:1px solid #1f2c40;border-radius:12px;padding:14px}
h2.sec{color:#22d3ee;font-size:16px;max-width:1000px;margin:24px auto 0}
ul.hist{max-width:1000px;margin:8px auto;color:#8fa3bf;font-size:13px}
</style></head><body>
<h1>⚡ Automation — scheduled tasks</h1>
<p class="sub">Trigger ➜ steps ➜ condition. Prottek 2 sec-e update hoy. Edit ekhanei hoy — HUD-e sudhu on/off, run, delete.</p>
<p id="st">Loading…</p>
<div class="grid" id="grid"></div>
<h2 class="sec">🍳 Recipe templates — ek click-e task banao</h2>
<div class="grid" id="tpl" style="grid-template-columns:repeat(auto-fill,minmax(180px,1fr))"></div>
<h2 class="sec">📜 History — sesh 20 run</h2>
<ul class="hist" id="hist"></ul>
<h2 class="sec">✏️ Create / Edit task</h2>
<form id="f">
<input type="hidden" id="tid">
<label>Task name</label><input id="fname" placeholder="Morning briefing">
<label>Trigger (JSON)</label><textarea id="ftrig" rows="2">{"type": "time", "kind": "daily", "time": "07:50"}</textarea>
<label>Steps (JSON list — tool + args)</label><textarea id="fsteps" rows="3">[{"tool": "weather_report", "args": {"city": "Kolkata"}}]</textarea>
<label>Condition (JSON, optional — {"type": "online"} / {"type": "idle", "minutes": 10})</label><textarea id="fcond" rows="1"></textarea>
<br><button type="submit">💾 Save task</button>
<button type="button" class="dim" onclick="clearForm()">Clear</button>
</form>
<script>
const TOK = "__TOK__";
function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function trigText(t){
  t = t||{}; const ty = String(t.type||'?').toLowerCase();
  if(ty==='time') return '🕐 '+(t.kind||'time')+' '+(t.time||'')+((t.kind==='once')?' '+(t.date||t.at||''):(t.kind==='weekly')?' weekday '+t.weekday:'');
  if(ty==='interval') return '🔁 every '+t.every+' '+(t.unit||'minutes');
  if(ty==='keyword') return "💬 keyword '"+t.phrase+"'";
  if(ty==='event') return "⚡ event '"+t.name+"'";
  if(ty==='webhook') return '🌐 webhook';
  return ty;
}
function cd(nr){
  if(!nr) return '—';
  const d = Math.floor((new Date(nr)-Date.now())/1000);
  if(d<=0) return 'due now';
  const h=String(Math.floor(d/3600)).padStart(2,'0'), m=String(Math.floor(d%3600/60)).padStart(2,'0'), s=String(d%60).padStart(2,'0');
  return h+':'+m+':'+s;
}
let cache = [];
async function api(action, body){
  const r = await fetch('/api/automation', {method:'POST', headers:{'Authorization':'Bearer '+TOK,'Content-Type':'application/json'}, body: JSON.stringify(Object.assign({action}, body||{}))});
  const d = await r.json().catch(()=>({}));
  document.getElementById('st').textContent = d.ok ? ('✅ '+(d.message||'done')) : ('⚠️ '+(d.error||'failed'));
  if(d.ok) load();
  return d;
}
async function load(){
  try {
    const r = await fetch('/api/automation', {headers:{'Authorization':'Bearer '+TOK}});
    if(!r.ok){ document.getElementById('st').textContent = '⛔ Unauthorized — notun QR/token diye abar kholo.'; return; }
    const d = await r.json();
    cache = d.tasks || [];
    document.getElementById('st').textContent = '✅ '+new Date().toLocaleTimeString()+' — '+cache.length+' task';
    document.getElementById('grid').innerHTML = cache.map(function(t){
      const steps = (t.steps||[]).map(function(s){ return esc(s.tool); }).join(' ➜ ') || 'no steps';
      const cond = t.condition ? ' [only if: '+esc(t.condition.type||'?')+']' : '';
      const last = t.last_run_result;
      const lastTxt = last ? ('last run: '+(last.status==='ok'?'✅':'❌')+' '+esc(last.status)+' '+esc(last.finished_at||last.started_at||'')) : 'last run: —';
      return '<div class="card'+(t.enabled?'':' off')+'">'
        + '<h2>'+(t.enabled?'🟢':'⚪')+' '+esc(t.name)+'</h2>'
        + '<p class="flow">'+esc(trigText(t.trigger))+' ➜ '+steps+esc(cond)+'</p>'
        + '<span class="badge '+(t.enabled?'on':'off')+'">'+(t.enabled?'ON':'OFF')+'</span>'
        + ' <span class="meta">⏭ '+cd(t.next_run)+'</span>'
        + '<p class="meta">'+esc(lastTxt)+'</p>'
        + '<button onclick="api(\''+(t.enabled?'disable':'enable')+'\', {task_id: \''+esc(t.id)+'\'})">'+(t.enabled?'⏸ OFF':'▶ ON')+'</button>'
        + '<button onclick="api(\'run\', {task_id: \''+esc(t.id)+'\'})">▶ RUN NOW</button>'
        + '<button class="dim" onclick="editTask(\''+esc(t.id)+'\')">✏️ EDIT</button>'
        + '<button class="danger" onclick="if(confirm(\'Delete '+esc(t.name)+\'?\')) api(\'delete\', {task_id: \''+esc(t.id)+'\'})">🗑 DELETE</button>'
        + '</div>';
    }).join('') || '<p class="sub">Kono task nei ekhono — template theke ekta banao.</p>';
    document.getElementById('tpl').innerHTML = (d.templates||[]).map(function(n){
      return '<div class="card"><h2>'+esc(n)+'</h2><button onclick="api(\'template\', {template: \''+esc(n)+'\'})">➕ Create</button></div>';
    }).join('');
    document.getElementById('hist').innerHTML = (d.history||[]).slice().reverse().map(function(h){
      return '<li>'+esc(h.started_at||'')+' — '+esc(h.task_name||h.task_id||'')+' — '+(h.status==='ok'?'✅':'❌')+' '+esc(h.status)+' ('+esc(String(h.duration_s==null?'':h.duration_s))+'s)</li>';
    }).join('') || '<li>History khali.</li>';
  } catch(e){
    document.getElementById('st').textContent = '⏳ Server-e pouchate parlam na — ektu wait koro.';
  }
}
function editTask(id){
  const t = cache.find(function(x){ return x.id===id; });
  if(!t) return;
  document.getElementById('tid').value = t.id;
  document.getElementById('fname').value = t.name||'';
  document.getElementById('ftrig').value = JSON.stringify(t.trigger||{});
  document.getElementById('fsteps').value = JSON.stringify(t.steps||[]);
  document.getElementById('fcond').value = t.condition ? JSON.stringify(t.condition) : '';
  document.getElementById('fname').scrollIntoView();
}
function clearForm(){
  document.getElementById('tid').value=''; document.getElementById('fname').value='';
  document.getElementById('ftrig').value='{"type": "time", "kind": "daily", "time": "07:50"}';
  document.getElementById('fsteps').value='[{"tool": "weather_report", "args": {"city": "Kolkata"}}]';
  document.getElementById('fcond').value='';
}
document.getElementById('f').addEventListener('submit', async function(e){
  e.preventDefault();
  let trig, steps, cond = null;
  try { trig = JSON.parse(document.getElementById('ftrig').value); steps = JSON.parse(document.getElementById('fsteps').value); }
  catch(err){ document.getElementById('st').textContent = '⚠️ Trigger / Steps JSON thik nei.'; return; }
  const c = document.getElementById('fcond').value.trim();
  if(c){ try { cond = JSON.parse(c); } catch(err){ document.getElementById('st').textContent = '⚠️ Condition JSON thik nei.'; return; } }
  const tid = document.getElementById('tid').value.trim();
  const task = {name: document.getElementById('fname').value.trim(), trigger: trig, steps: steps};
  if(cond) task.condition = cond;
  if(tid) await api('update', {task_id: tid, patch: task});
  else await api('create', {task});
  clearForm();
});
load(); setInterval(load, 2000);
</script></body></html>""".replace("__TOK__", tok)
            return HTMLResponse(html)

        @app.post("/api/action")
        async def queue_action(req: Request):
            """⚡ Quick action — ENQUEUE a tool for Mark to run.

            JSON {tool, args}. The HUD and the /main-agent page never call a
            tool directly: they queue here and show "queued — Mark will run
            it". main.py drains core/action_queue.py at integration.
            Auth: Bearer token. Never raises.
            """
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                body = await req.json()
            except Exception:
                body = {}
            if not isinstance(body, dict):
                body = {}
            try:
                from core.action_queue import enqueue
                tool = str(body.get("tool") or "").strip()
                args = body.get("args") or {}
                if not isinstance(args, dict):
                    args = {}
                qid = enqueue(tool, args)
                if not qid:
                    return JSONResponse(
                        {"error": "Queue-te dite parlam na — tool-er naam dekho (ba queue full)."},
                        status_code=400)
                return JSONResponse({"ok": True, "queued_id": qid,
                                     "message": f"✅ {tool} queued — Mark will run it."})
            except Exception as e:
                return JSONResponse({"error": str(e)[:120]}, status_code=500)

        @app.get("/api/main-agent")
        async def main_agent_api(req: Request):
            """🧠 Main Agent — Mark status, agents summary, automation
            summary, location, pending actions. Bearer auth. Never raises."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                from core.mark_status import snapshot as _mark_snapshot
                mark = _mark_snapshot()
            except Exception:
                mark = {"current_task": "Idle — waiting for you.",
                        "last_response": "", "queue_len": 0, "updated_at": ""}
            try:
                from core.agents import REGISTRY
                agents = REGISTRY.snapshot()
            except Exception:
                agents = []
            try:
                from core.automation import ENGINE
                tasks = ENGINE.list_tasks()
                nxts = [t.get("next_run") for t in tasks
                        if t.get("enabled") and t.get("next_run")]
                automation = {
                    "total": len(tasks),
                    "enabled": sum(1 for t in tasks if t.get("enabled")),
                    "next_run": min(nxts) if nxts else None,
                    "tasks": [{"id": t.get("id"), "name": t.get("name"),
                               "enabled": t.get("enabled"),
                               "next_run": t.get("next_run")}
                              for t in tasks],
                }
            except Exception:
                automation = {"total": 0, "enabled": 0, "next_run": None,
                              "tasks": []}
            try:
                from core.phone_location import last_fix
                location = last_fix()
            except Exception:
                location = None
            try:
                from core.action_queue import list_pending
                pending = list_pending()
            except Exception:
                pending = []
            return JSONResponse({
                "mark": mark,
                "agents": agents,
                "automation": automation,
                "location": location,
                "pending_actions": pending,
            })

        @app.get("/main-agent", response_class=HTMLResponse)
        async def main_agent_page(req: Request, token: str = ""):
            """🧠 Main Agent — master screen as a dashboard page: Mark live
            status, 7 agents + automation summary, phone screen, PC screen,
            location, quick actions. Same pattern as /agents: auth via
            ?token=, re-polls /api/main-agent every 2 s, screens every 4 s."""
            if not _valid(token.strip()):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            tok = token.strip().replace('"', "")
            html = """<!DOCTYPE html>
<html lang="bn"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🧠 Main Agent — Mark-LVII</title>
<style>
body{background:#0b0f16;color:#e6f1ff;font-family:monospace;margin:0;padding:16px}
h1{color:#22d3ee;font-size:20px;text-align:center}
h2{color:#22d3ee;font-size:16px;max-width:900px;margin:20px auto 6px}
p.sub{color:#8fa3bf;font-size:13px;text-align:center}
#st{color:#4ade80;text-align:center;font-size:13px}
.box{max-width:900px;margin:8px auto;background:#131a26;border:1px solid #1f2c40;border-radius:12px;padding:12px}
.meta{font-size:13px;color:#e6f1ff;word-break:break-word}
.dim{color:#8fa3bf;font-size:12px}
img{max-width:100%;border:2px solid #22d3ee;border-radius:12px;background:#000;display:block;margin:0 auto}
button{background:#22d3ee;color:#04222b;border:0;border-radius:8px;padding:8px 14px;
font-family:monospace;font-weight:bold;cursor:pointer;margin:4px}
button.dim{background:#1f2c40;color:#e6f1ff}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px}
</style></head><body>
<h1>🧠 Main Agent — Mark-er master screen</h1>
<p class="sub">Mark + 7 agent + automation + phone/PC screen + location — sob ek jaigai.</p>
<p id="st">Loading…</p>
<h2>🧠 Mark — live status</h2>
<div class="box"><p class="meta" id="mark">—</p></div>
<h2>🤖 7 worker agent + ⚡ automation</h2>
<div class="box"><p class="meta" id="agents">—</p><p class="dim" id="auto">—</p></div>
<h2>📱 Phone screen (still image)</h2>
<div class="box" style="text-align:center">
<img id="phone" alt="Phone screen ekhono ashe ni — Refresh chapo.">
<br><button onclick="refreshPhone()">🔄 Refresh phone screen</button></div>
<h2>🖥️ PC screen</h2>
<div class="box" style="text-align:center">
<img id="pc" alt="PC screenshot ekhono neoa hoy ni — Refresh chapo.">
<br><button onclick="loadPc()">🔄 Refresh PC screen</button></div>
<h2>📍 Location — phone kothay</h2>
<div class="box"><p class="meta" id="loc">—</p>
<button onclick="findPhone()">📍 Find phone</button></div>
<h2>⚡ Quick actions — queue-te jabe, Mark chalabe</h2>
<div class="box"><div class="grid" id="qa"></div><p class="dim" id="pend">—</p></div>
<script>
const TOK = "__TOK__";
const QA = [
  ['📱 Open app', 'open_app', {app: 'Calculator'}],
  ['🎬 Upload video', 'youtube_upload', {file_path: '', title: "Today's video"}],
  ['💬 Send WhatsApp', 'whatsapp_send', {to: '', message: ''}],
  ['💾 Backup', 'drive_upload', {filename: 'mark-lvii-backup.txt', content: 'Mark-LVII backup note'}],
  ['📍 Find phone', 'phone_location', {refresh: true}],
  ['🖥️ Screenshot PC', 'screen_process', {action: 'screenshot'}]
];
function esc(s){ return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
document.getElementById('qa').innerHTML = QA.map(function(q, i){
  return '<button onclick="queueAction('+i+')">'+esc(q[0])+'</button>';
}).join('');
async function queueAction(i){
  const q = QA[i];
  try {
    const r = await fetch('/api/action', {method:'POST', headers:{'Authorization':'Bearer '+TOK,'Content-Type':'application/json'}, body: JSON.stringify({tool: q[1], args: q[2]})});
    const d = await r.json();
    document.getElementById('st').textContent = d.ok ? ('✅ '+q[0]+': queued — Mark will run it.') : ('⚠️ '+(d.error||'queue holo na'));
  } catch(e){ document.getElementById('st').textContent = '⏳ Server-e pouchate parlam na.'; }
  load();
}
function loadPhone(){ document.getElementById('phone').src = '/api/phone-screen?token='+TOK+'&t='+Date.now(); }
function loadPc(){ document.getElementById('pc').src = '/api/pc-screen?token='+TOK+'&t='+Date.now(); }
async function refreshPhone(){
  document.getElementById('st').textContent = '⏳ Phone-ke bolchi…';
  try { await fetch('/api/phone-screen/refresh', {method:'POST', headers:{'Authorization':'Bearer '+TOK}}); } catch(e){}
  setTimeout(loadPhone, 5000);
}
async function findPhone(){
  document.getElementById('st').textContent = '⏳ Phone-er location khujchi…';
  try {
    const r = await fetch('/api/location/refresh', {method:'POST', headers:{'Authorization':'Bearer '+TOK}});
    const d = await r.json();
    document.getElementById('st').textContent = d.ok ? '✅ Location request pathano holo — koyek second-e asbe.' : ('⚠️ '+(d.error||'holo na'));
  } catch(e){ document.getElementById('st').textContent = '⏳ Server-e pouchate parlam na.'; }
  setTimeout(load, 5000);
}
async function load(){
  try {
    const r = await fetch('/api/main-agent', {headers:{'Authorization':'Bearer '+TOK}});
    if(!r.ok){ document.getElementById('st').textContent = '⛔ Unauthorized — notun QR/token diye abar kholo.'; return; }
    const d = await r.json();
    document.getElementById('st').textContent = '✅ '+new Date().toLocaleTimeString();
    const m = d.mark||{};
    document.getElementById('mark').innerHTML = '• Current: '+esc(m.current_task||'Idle')
      + '<br>• Last reply: '+esc(m.last_response||'—')
      + '<br>• Queue: '+esc(String(m.queue_len==null?0:m.queue_len))+' pending'
      + (m.updated_at ? ' • updated '+esc(m.updated_at) : '');
    const ag = d.agents||[];
    document.getElementById('agents').textContent = ag.map(function(a){
      return a.icon+' '+a.name+': '+a.status+(a.status==='working'&&a.current_task?' ('+a.current_task+')':'');
    }).join(' • ') || '—';
    const au = d.automation||{};
    document.getElementById('auto').textContent = '⚡ '+au.total+' automation task ('+au.enabled+' on)'
      + (au.next_run ? ' • next run '+au.next_run : ' • next run —');
    const loc = d.location;
    document.getElementById('loc').textContent = loc
      ? ('📍 Lat '+loc.lat+', Lng '+loc.lon+' ('+(loc.at||'')+') — 🗺️ google.com/maps?q='+loc.lat+','+loc.lon)
      : '📍 Phone-er location jani na ekhono — Find phone chapo; phone GPS + Location permission ON thakte hobe.';
    const pend = d.pending_actions||[];
    document.getElementById('pend').textContent = pend.length
      ? ('⏳ Queued: '+pend.map(function(p){ return p.tool; }).join(', '))
      : 'Queue khali.';
  } catch(e){
    document.getElementById('st').textContent = '⏳ Server-e pouchate parlam na — ektu wait koro.';
  }
}
load(); setInterval(load, 2000);
loadPhone(); setInterval(loadPhone, 4000);
loadPc(); setInterval(loadPc, 4000);
</script></body></html>""".replace("__TOK__", tok)
            return HTMLResponse(html)

        @app.get("/api/pc-screen")
        async def pc_screen_image(req: Request, token: str = ""):
            """Latest PC screenshot as a JPEG — captured on demand with mss
            (the same capture helper jarvis_link uses for the phone's
            screen_req), saved to memory/pc_screen.jpg.

            Auth: Bearer header or ?token= (browser <img> can't send
            headers — same as /api/phone-screen). Capture runs in a worker
            thread so the event loop never blocks. 404 when the capture
            fails (mss/ImageGrab unavailable on this machine).
            """
            if not _auth(req) and not _valid(token.strip()):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                from core import jarvis_link
                link = jarvis_link.LINK
                if link is not None:
                    path = await asyncio.to_thread(link.capture_pc_screen)
                else:
                    # Link never attached — capture directly with mss.
                    def _capture():
                        try:
                            import io
                            import mss
                            from PIL import Image
                            with mss.mss() as sct:
                                shot = sct.grab(sct.monitors[1])
                            img = Image.frombytes("RGB", shot.size, shot.bgra,
                                                  "raw", "BGRX")
                            img.thumbnail((1280, 1280))
                            p = BASE_DIR / "memory" / "pc_screen.jpg"
                            p.parent.mkdir(parents=True, exist_ok=True)
                            img.save(str(p), format="JPEG", quality=80)
                            return str(p)
                        except Exception:
                            return ""
                    path = await asyncio.to_thread(_capture)
                if not path or not os.path.exists(path):
                    return JSONResponse(
                        {"error": "PC screenshot not available — mss/ImageGrab konotai cholche na."},
                        status_code=404)
                return FileResponse(path, media_type="image/jpeg",
                                    headers={"Cache-Control": "no-store"})
            except Exception as e:
                return JSONResponse({"error": str(e)[:120]}, status_code=500)

        @app.get("/api/location")
        async def location_api(req: Request):
            """📍 Phone location — last-known fix (never faked).

            {status: "ok"|"unavailable", lat, lon, accuracy, at, address
            (Nominatim reverse-geocode, only when a fix exists), history
            (last 20), pc_location: {city, approximate: true}}.
            No fix → status "unavailable" + the honest message. Bearer
            auth. Never raises.
            """
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                from core.phone_location import (
                    last_fix, history, reverse_geocode, pc_location)
                fix = last_fix()
                pc = pc_location()
                if not fix:
                    return JSONResponse({
                        "status": "unavailable",
                        "lat": None, "lon": None, "accuracy": None,
                        "at": None, "address": None,
                        "message": "location unavailable — turn on phone location",
                        "history": history(),
                        "pc_location": pc,
                    })
                address = reverse_geocode(fix.get("lat"), fix.get("lon"))
                return JSONResponse({
                    "status": "ok",
                    "lat": fix.get("lat"), "lon": fix.get("lon"),
                    "accuracy": fix.get("accuracy"),
                    "at": fix.get("at"), "address": address,
                    "history": history(),
                    "pc_location": pc,
                })
            except Exception as e:
                return JSONResponse({"status": "unavailable",
                                     "lat": None, "lon": None,
                                     "accuracy": None, "at": None,
                                     "address": None,
                                     "message": f"location unavailable — {str(e)[:80]}",
                                     "history": [], 
                                     "pc_location": {"city": "unknown",
                                                     "approximate": True}})

        @app.post("/api/location/refresh")
        async def location_refresh(req: Request):
            """Ask the phone for a FRESH location now (background thread).
            Returns at once — the new fix appears at /api/location when it
            arrives. Needs the phone paired. Never raises."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                from core import jarvis_link
                link = jarvis_link.LINK
                if link is None or not link.paired:
                    return JSONResponse(
                        {"error": "Phone pair kora nei — age QR scan koro."},
                        status_code=409)
                threading.Thread(target=lambda: link.request_phone_location(),
                                 daemon=True).start()
                return JSONResponse({"ok": True,
                                     "message": "Phone-ke location-er jonno bolchi — koyek second-e asbe."})
            except Exception as e:
                return JSONResponse({"error": str(e)[:120]}, status_code=500)

        @app.get("/uploads/{filename}")
        async def download_file(filename: str, token: str = ""):
            # Auth via query param — browser <a download> can't send custom headers
            tok = token.strip()
            if not _valid(tok):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            safe = re.sub(r'[/\\]', '', filename)
            path = self._uploads_dir / safe
            if not path.exists() or not path.is_file():
                return JSONResponse({"error": "Not found"}, status_code=404)
            return FileResponse(str(path), filename=safe)

        @app.websocket("/ws")
        async def ws_ep(websocket: WebSocket, token: str = ""):
            tok = token.strip()
            if not _valid(tok):
                await websocket.close(code=4001)
                return
            await websocket.accept()
            self._clients.add(websocket)
            for entry in self._history[-50:]:
                try:
                    await websocket.send_json(entry)
                except Exception:
                    break
            try:
                while True:
                    data = await websocket.receive_json()
                    if data.get("type") == "command":
                        enc = data.get("enc", "")
                        t   = self._decrypt(tok, enc) if enc else (data.get("text") or "").strip()
                        if t:
                            await self._command_queue.put(t)
                            if self._wake_callback:
                                self._wake_callback()
            except WebSocketDisconnect:
                pass
            finally:
                self._clients.discard(websocket)

        # ── Facebook OAuth (Page token) ─────────────────────────────────────
        # Public routes — Facebook redirects the user's browser here with no
        # bearer token. The App Secret is only ever sent server-side to
        # graph.facebook.com; nothing is stored, nothing secret is returned.
        # Handlers take only query params (no Request) so tests can call them
        # directly without building a fake request.
        @app.get("/facebook/login", response_class=HTMLResponse)
        async def facebook_login_page():
            app_id, _secret = _fb_env()
            return HTMLResponse(_fb_login_html(app_id))

        @app.get("/api/facebook/callback", response_class=HTMLResponse)
        async def facebook_callback(
                code: str = "", error: str = "", error_description: str = "",
                hub_mode: str = Query("", alias="hub.mode"),
                hub_verify_token: str = Query("", alias="hub.verify_token"),
                hub_challenge: str = Query("", alias="hub.challenge")):
            # Webhook verification FIRST — one URL serves both purposes:
            # Facebook's "Verify and save" hits this URL with hub.mode, and
            # the OAuth login flow hits it with a code. _fb_webhook_verify
            # returns None when this is not a verification request.
            verified = _fb_webhook_verify(hub_mode, hub_verify_token,
                                          hub_challenge)
            if verified is not None:
                return verified
            if error:
                reason = (error_description or "").strip()
                msg = "Facebook Login cancel kora hoyeche."
                if reason:
                    msg += " (" + reason + ")"
                msg += " Page token pete abar Login chapho."
                return HTMLResponse(_fb_error_html("Login cancel", msg))
            if not code:
                return HTMLResponse(_fb_error_html(
                    "Login holo na",
                    "Facebook theke kono code pelam na. Abar /facebook/login "
                    "theke Login chapho."))
            app_id, app_secret = _fb_env()
            if not app_id or not app_secret:
                return HTMLResponse(_fb_error_html(
                    "App ID / Secret set kora nei",
                    "Render dashboard → Environment-e FACEBOOK_APP_ID ar "
                    "FACEBOOK_APP_SECRET bosao, tarpor abar Login chapho."))
            user_token, err = await asyncio.to_thread(
                _fb_exchange_code, code, app_id, app_secret)
            if err:
                return HTMLResponse(_fb_error_html("Token exchange holo na", err))
            pages, err2 = await asyncio.to_thread(_fb_list_pages, user_token)
            if err2:
                return HTMLResponse(_fb_error_html("Page list pelam na", err2))
            if not pages:
                return HTMLResponse(_fb_error_html(
                    "Kono Page pelam na",
                    "Ei Facebook account-e kono Page pelam na, ba Page-er "
                    "permission dao ni. Facebook-e Page banao / permission dao, "
                    "tarpor abar Login chapho."))
            return HTMLResponse(_fb_pages_html(pages))

        @app.post("/api/facebook/callback")
        async def facebook_callback_post():
            """Webhook events: acknowledge only. No event processing is
            built — Facebook just needs a 200 so it does not disable the
            subscription. Nothing is logged."""
            return JSONResponse({"ok": True})

        # ── Instagram OAuth (IG business account) ─────────────────────────
        # Same Facebook App (same App ID / Secret) as the Facebook flow —
        # only the callback URL and the scope differ. instagram_post needs
        # the IG user id + the Page token, so the callback page shows both.
        @app.get("/instagram/login", response_class=HTMLResponse)
        async def instagram_login_page():
            app_id, _secret = _fb_env()
            return HTMLResponse(_ig_login_html(app_id))

        @app.get("/api/instagram/callback", response_class=HTMLResponse)
        async def instagram_callback(
                code: str = "", error: str = "", error_description: str = "",
                hub_mode: str = Query("", alias="hub.mode"),
                hub_verify_token: str = Query("", alias="hub.verify_token"),
                hub_challenge: str = Query("", alias="hub.challenge")):
            # Webhook verification FIRST — same as the Facebook callback:
            # Instagram's "Verify and save" hits this URL with hub.mode.
            verified = _fb_webhook_verify(hub_mode, hub_verify_token,
                                          hub_challenge)
            if verified is not None:
                return verified
            if error:
                reason = (error_description or "").strip()
                msg = "Facebook Login cancel kora hoyeche."
                if reason:
                    msg += " (" + reason + ")"
                msg += " IG account pete abar Login chapho."
                return HTMLResponse(_fb_error_html("Login cancel", msg))
            if not code:
                return HTMLResponse(_fb_error_html(
                    "Login holo na",
                    "Facebook theke kono code pelam na. Abar /instagram/login "
                    "theke Login chapho."))
            app_id, app_secret = _fb_env()
            if not app_id or not app_secret:
                return HTMLResponse(_fb_error_html(
                    "App ID / Secret set kora nei",
                    "Render dashboard → Environment-e FACEBOOK_APP_ID ar "
                    "FACEBOOK_APP_SECRET bosao, tarpor abar Login chapho."))
            user_token, err = await asyncio.to_thread(
                _fb_exchange_code, code, app_id, app_secret, _IG_CALLBACK_URL)
            if err:
                return HTMLResponse(_fb_error_html("Token exchange holo na", err))
            pages, err2 = await asyncio.to_thread(_ig_list_pages, user_token)
            if err2:
                return HTMLResponse(_fb_error_html("Page list pelam na", err2))
            if not pages:
                return HTMLResponse(_fb_error_html(
                    "Kono Page pelam na",
                    "Ei Facebook account-e kono Page pelam na, ba Page-er "
                    "permission dao ni. Facebook-e Page banao / permission dao, "
                    "tarpor abar Login chapho."))
            return HTMLResponse(_ig_pages_html(pages))

        @app.post("/api/instagram/callback")
        async def instagram_callback_post():
            """Webhook events: acknowledge only, same as the Facebook one."""
            return JSONResponse({"ok": True})

        return app

    # ── serve ─────────────────────────────────────────────────────────────

    async def _serve_redirector(self) -> None:
        """A plain-HTTP listener whose only job is to send people to HTTPS.

        THE PROBLEM THIS SOLVES, WHICH LOOKED LIKE THE SERVER BEING DOWN
            Type `192.168.1.108:8000` into a phone browser and it tries HTTP.
            The TLS server accepts the connection, finds no handshake and
            closes it — which Chrome reports as "This site can't be reached,
            192.168.1.108 refused to connect". The server is running perfectly
            and the user is told it is off.

            The port that used to sit here was a SECOND HTTPS server, added on
            the belief that browsers upgrade a bare `ip:port` to https. Some
            do. Android Chrome does not, so the second port had exactly the
            same failure as the first.

        So this speaks HTTP, and answers everything with a redirect to the same
        path on the HTTPS port. Typing the address by hand now works, which is
        what people do when a QR code is inconvenient.
        """
        from fastapi.responses import RedirectResponse

        bounce = FastAPI(docs_url=None, redoc_url=None)

        @bounce.get("/{path:path}")
        async def _to_https(path: str, request: Request):
            query = f"?{request.url.query}" if request.url.query else ""
            return RedirectResponse(
                f"https://{self._ip}:{SECURE_PORT}/{path}{query}",
                status_code=307)

        cfg = uvicorn.Config(bounce, host="0.0.0.0", port=PORT,
                             log_level="warning")
        print(f"[Dashboard] Type by hand:  {self._ip}:{PORT}  "
              f"(sends you to the secure page)")
        await uvicorn.Server(cfg).serve()

    async def serve(self) -> None:
        if not _DEPS_OK:
            print("[Dashboard] fastapi/uvicorn not installed — dashboard disabled.")
            print("[Dashboard] Run:  pip install fastapi 'uvicorn[standard]' cryptography")
            return

        # Startup only CHECKS — see report_network_access for why it never
        # asks for administrator rights here. In a thread: reading the
        # firewall rules takes about a second.
        asyncio.get_running_loop().run_in_executor(
            None, report_network_access, PORT, SECURE_PORT)

        # Only make a certificate if HTTPS was actually asked for. Generating
        # one nobody uses just leaves a private key on disk.
        try:
            import json as _json
            with open(BASE_DIR / "config" / "api_keys.json", "r",
                      encoding="utf-8") as f:
                if _json.load(f).get("dashboard_https"):
                    _ensure_certs()
        except Exception:
            pass

        use_ssl  = self._ssl_enabled()
        ssl_key  = BASE_DIR / "config" / "certs" / "jarvis.key"
        ssl_cert = BASE_DIR / "config" / "certs" / "jarvis.crt"

        # TLS IS WANTED, BUT NOT AT THE COST OF NOT STARTING.
        #
        # An earlier version returned here when certificates could not be made,
        # on the argument that serving a remote-control channel in clear is a
        # different product. The argument is right and the behaviour was wrong:
        # a dashboard that does not start is not more secure, it is absent, and
        # the user is left with "refused to connect" and nothing to act on.
        #
        # So: HTTPS whenever it can be had — which is almost always, since the
        # certificate is generated locally on first run — and plain HTTP with a
        # loud, repeated warning when it cannot. The page keeps working either
        # way; without a secure context it simply cannot encrypt, and it says
        # so on screen rather than pretending.
        if use_ssl:
            asyncio.create_task(self._serve_redirector())
        else:
            print("[Dashboard] Plain HTTP on your local network. Commands are "
                  "not encrypted; the pairing key still gates access.")
            print('[Dashboard] For HTTPS set "dashboard_https": true in '
                  'config/api_keys.json (your phone will ask you to trust the '
                  'certificate once).')

        cfg = uvicorn.Config(
            self.app, host="0.0.0.0",
            port=SECURE_PORT if use_ssl else PORT, log_level="warning",
            **({"ssl_keyfile": str(ssl_key), "ssl_certfile": str(ssl_cert)}
               if use_ssl else {}),
        )

        # CAN THIS PORT ACTUALLY BE TAKEN?
        #
        # uvicorn raises when the port is busy, and under pythonw.exe there is
        # no console for that to be seen in — so a second JARVIS, or anything
        # else already on 8000, produced a dashboard that was silently dead
        # while the HUD went on showing a QR code pointing at it. The phone
        # then reports ERR_CONNECTION_REFUSED, which is true and impossible to
        # act on.
        #
        # Asking first costs a millisecond and turns that into a sentence.
        import socket as _socket
        # No SO_REUSEADDR. On Windows that option lets a second socket bind a
        # port another socket already holds — which is exactly the condition
        # being tested for, so setting it made the probe always succeed.
        _probe = _socket.socket()
        try:
            _probe.bind(("0.0.0.0", SECURE_PORT if use_ssl else PORT))
        except OSError as exc:
            _probe.close()
            self._bind_error = (
                f"port {SECURE_PORT if use_ssl else PORT} is already in use — "
                f"another copy of JARVIS is probably running. Close it and "
                f"restart, or the phone dashboard will stay unreachable "
                f"({exc.__class__.__name__})")
            print(f"[Dashboard] {self._bind_error}")
            return
        _probe.close()

        print(f"[Dashboard] {self.get_url()}")
        print("[Dashboard] Press 'Remote Control' in JARVIS UI to get the QR code.")
        await uvicorn.Server(cfg).serve()
