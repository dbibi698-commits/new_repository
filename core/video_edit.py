"""
core/video_edit.py — trim / cut / merge / text / thumbnail / probe for videos.

A thin ffmpeg/ffprobe wrapper. Every function returns (ok, message) and
never raises, so a tool call on a worker thread can hand the result straight
to the user. No Qt anywhere (see AGENTS.md). ffmpeg is run through
subprocess with a timeout; its output is captured, never sent to DEVNULL
unlogged — on failure the message carries ffmpeg's own last line.

Where does ffmpeg come from? ensure_ffmpeg() checks in this order:
  (a) ffmpeg already on PATH (the user's PC may have it, this Linux VM does);
  (b) <Mark folder>/ffmpeg/ffmpeg.exe — a previous on-demand download;
  (c) download the static Windows build from gyan.dev
      (ffmpeg-release-essentials.zip, ~110 MB) into the Mark folder and
      verify it runs. This is ON-DEMAND, on first use, on the user's PC —
      ffmpeg is deliberately NOT bundled into the repo or the EXE, because
      the zip alone would roughly double the installer size.

Honest limits:
  * No ffmpeg, no editing — trim/cut/merge/text/thumbnail all return a
    plain-words message saying to run the download first.
  * drawtext (add_text) needs the fontconfig build that gyan.dev ships;
    if a custom font is ever needed it must be passed as a fontfile.
  * cut() re-encodes (trim filters + concat) so cuts land exactly on the
    requested seconds instead of the nearest keyframe; it is slower than
    trim(), which copies the stream without re-encoding.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

try:
    import urllib.request as _urlrequest
    import urllib.error as _urlerror
except Exception:  # pragma: no cover - stdlib, always present
    _urlrequest = None
    _urlerror = None

_FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
_FFMPEG_DIRNAME = "ffmpeg"          # <Mark folder>/ffmpeg/ffmpeg.exe
_TIMEOUT = 900                      # seconds per ffmpeg run (edits are slow)
_DOWNLOAD_TIMEOUT = 600             # seconds for the ~110 MB zip

_MARK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── ffmpeg location ──────────────────────────────────────────────────────────

def _mark_ffmpeg_exe() -> str:
    """<Mark folder>/ffmpeg/ffmpeg.exe (Windows) or .../ffmpeg/ffmpeg."""
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    return os.path.join(_MARK_DIR, _FFMPEG_DIRNAME, name)


def _mark_ffprobe_exe() -> str:
    name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    return os.path.join(_MARK_DIR, _FFMPEG_DIRNAME, name)


def _runs_ok(exe: str) -> bool:
    """True when `exe -version` exits 0. Never raises."""
    try:
        r = subprocess.run([exe, "-version"], capture_output=True,
                           timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def ensure_ffmpeg() -> tuple[bool, str]:
    """Find ffmpeg, downloading the static Windows build on first use if
    needed. Returns (True, path-to-ffmpeg) or (False, plain-words message).
    Never raises."""
    try:
        on_path = shutil.which("ffmpeg")
        if on_path and _runs_ok(on_path):
            return (True, on_path)
        bundled = _mark_ffmpeg_exe()
        if os.path.isfile(bundled) and _runs_ok(bundled):
            return (True, bundled)
        # (c) On-demand download — Windows static build from gyan.dev.
        if os.name != "nt":
            return (False,
                    "ffmpeg pelam na — PATH-eo nei, Mark folder-eo nei. "
                    "Windows PC-te prothom bar use korle ami gyan.dev theke "
                    "download kore nebo; ei Linux machine-e ffmpeg install "
                    "koro (`sudo apt install ffmpeg`) ba PATH-e rakho.")
        if _urlrequest is None:
            return (False, "Download korte parlam na — urllib nei.")
        folder = os.path.join(_MARK_DIR, _FFMPEG_DIRNAME)
        os.makedirs(folder, exist_ok=True)
        zip_path = os.path.join(tempfile.gettempdir(),
                                "ffmpeg-release-essentials.zip")
        try:
            req = _urlrequest.Request(_FFMPEG_URL,
                                      headers={"User-Agent": "Mark-LVII"})
            with _urlrequest.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp, \
                    open(zip_path, "wb") as f:
                shutil.copyfileobj(resp, f, length=1024 * 1024)
        except Exception as e:
            return (False, f"ffmpeg download holo na (gyan.dev): {e} — "
                           "internet ache kina dekho, ba ffmpeg nije install "
                           "kore PATH-e rakho.")
        try:
            with zipfile.ZipFile(zip_path) as zf:
                exe_member = next(
                    (m for m in zf.namelist()
                     if m.endswith("/bin/ffmpeg.exe")), None)
                if not exe_member:
                    return (False, "ffmpeg zip-er bhitore ffmpeg.exe pelam na.")
                zf.extract(exe_member, folder)
                extracted = os.path.join(folder, exe_member)
                shutil.move(extracted, bundled)
                # Remove the now-empty extracted subfolders.
                shutil.rmtree(os.path.join(folder, exe_member.split("/")[0]),
                              ignore_errors=True)
        except Exception as e:
            return (False, f"ffmpeg zip khulte parlam na: {e}")
        finally:
            try:
                os.remove(zip_path)
            except Exception:
                pass
        if _runs_ok(bundled):
            return (True, bundled)
        return (False, "ffmpeg download holo kintu cholche na — abar try koro, "
                       "ba ffmpeg nije install kore PATH-e rakho.")
    except Exception as e:
        return (False, f"ffmpeg khujte giye problem holo: {e}")


def _ffmpeg_exe() -> str:
    """Path to a working ffmpeg, or '' when ensure_ffmpeg() fails."""
    ok, path = ensure_ffmpeg()
    return path if ok else ""


def _ffprobe_exe() -> str:
    """ffprobe next to ffmpeg when possible, else PATH. '' when none."""
    bundled = _mark_ffprobe_exe()
    if os.path.isfile(bundled) and _runs_ok(bundled):
        return bundled
    found = shutil.which("ffprobe")
    return found or ""


def ffmpeg_status() -> str:
    """Short human-readable status line for Settings / the video panel."""
    ok, path = ensure_ffmpeg()
    if ok:
        return f"✅ ffmpeg ready: {path}"
    return f"⚠️ ffmpeg nei: {path}"


# ── helpers ──────────────────────────────────────────────────────────────────

def _check_input(path) -> str:
    """'' when `path` is an existing file, else why not."""
    path = ("" if path is None else str(path)).strip()
    if not path:
        return "video file-er path dao."
    if not os.path.isfile(path):
        return f"file-ta pelam na: {path}"
    if os.path.getsize(path) == 0:
        return f"file-ta khali (0 bytes): {path}"
    return ""


def _check_output(path) -> str:
    path = ("" if path is None else str(path)).strip()
    if not path:
        return "output file-er path dao."
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        return f"output folder-ta nei: {folder}"
    return ""


def _parse_time(value) -> float | None:
    """Seconds from a number or 'HH:MM:SS[.ms]' / 'MM:SS' string. None if bad."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value or "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    parts = s.split(":")
    if len(parts) not in (2, 3) or not all(p.replace(".", "", 1).isdigit()
                                          for p in parts):
        return None
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return None
    total = 0.0
    for n in nums:
        total = total * 60 + n
    return total


def _fmt_time(seconds: float) -> str:
    return f"{float(seconds):.3f}"


def _run_ffmpeg(argv: list[str]) -> tuple[bool, str]:
    """Run ffmpeg, capture output, return (ok, last-line-or-success-note).
    Never raises. `argv` must start with the ffmpeg exe path."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           timeout=_TIMEOUT)
    except subprocess.TimeoutExpired:
        return (False, "ffmpeg somoy sesh hoye gelo (timeout) — file-ta onek "
                       "boro hote pare, choto kore abar try koro.")
    except FileNotFoundError:
        return (False, "ffmpeg pelam na — age ffmpeg download/install korte hobe.")
    except Exception as e:
        return (False, f"ffmpeg chalate parlam na: {e}")
    if r.returncode == 0:
        return (True, "")
    err = (r.stderr or "").strip().splitlines()
    last = err[-1].strip() if err else "unknown error"
    return (False, f"ffmpeg error: {last[:300]}")


def _run_ffprobe(argv: list[str]):
    """Run ffprobe, return (returncode, stdout). Never raises."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        return (r.returncode, r.stdout or "")
    except Exception:
        return (-1, "")


# ── operations ───────────────────────────────────────────────────────────────

def trim(input_path, start, end, output_path) -> tuple[bool, str]:
    """Keep only start..end of the video (stream copy, no re-encode).
    `start`/`end` are seconds or 'HH:MM:SS'. Returns (ok, message)."""
    try:
        bad = _check_input(input_path)
        if bad:
            return (False, bad)
        bad = _check_output(output_path)
        if bad:
            return (False, bad)
        s, e = _parse_time(start), _parse_time(end)
        if s is None or e is None:
            return (False, "start ar end somoy dao — second (e.g. 10) ba "
                           "HH:MM:SS (e.g. 00:01:30).")
        if s < 0 or e <= s:
            return (False, f"end ({e}) start ({s})-er pore hote hobe.")
        exe = _ffmpeg_exe()
        if not exe:
            return (False, "ffmpeg pelam na — prothom bar use-e ami download "
                           "kore nebo, internet on rekhe abar try koro.")
        argv = [exe, "-y", "-ss", _fmt_time(s), "-to", _fmt_time(e),
                "-i", str(input_path), "-c", "copy", str(output_path)]
        ok, msg = _run_ffmpeg(argv)
        if not ok:
            return (False, f"Trim holo na: {msg}")
        return (True, f"✅ Trim holo: {start}–{end} → {output_path}")
    except Exception as e:
        return (False, f"Trim korte parlam na: {e}")


def cut(input_path, segments, output_path) -> tuple[bool, str]:
    """Keep only the listed segments, in order, in one output file.
    `segments` is a list of (start, end) pairs or {"start":..,"end":..} dicts
    (seconds or 'HH:MM:SS'). Re-encodes so cuts land exactly on the second.
    Returns (ok, message)."""
    try:
        bad = _check_input(input_path)
        if bad:
            return (False, bad)
        bad = _check_output(output_path)
        if bad:
            return (False, bad)
        segs: list[tuple[float, float]] = []
        for seg in (segments or []):
            if isinstance(seg, dict):
                s, e = _parse_time(seg.get("start")), _parse_time(seg.get("end"))
            else:
                try:
                    s, e = _parse_time(seg[0]), _parse_time(seg[1])
                except Exception:
                    s, e = None, None
            if s is None or e is None or e <= s or s < 0:
                return (False, f"segment-ta thik na: {seg} — prottek-ta "
                               "(start, end) hote hobe, end start-er pore.")
            segs.append((s, e))
        if not segs:
            return (False, "Kon tukro rakhbo — segments dao, e.g. "
                           "[[0, 10], [20, 30]].")
        exe = _ffmpeg_exe()
        if not exe:
            return (False, "ffmpeg pelam na — prothom bar use-e ami download "
                           "kore nebo, internet on rekhe abar try koro.")
        has_audio = False
        try:
            info = probe(input_path)
            has_audio = "audio" in str(info[1]).lower()
        except Exception:
            has_audio = False
        v_parts, a_parts = [], []
        for i, (s, e) in enumerate(segs):
            v_parts.append(f"[0:v]trim=start={_fmt_time(s)}:end={_fmt_time(e)},"
                           f"setpts=PTS-STARTPTS[v{i}]")
            if has_audio:
                a_parts.append(f"[0:a]atrim=start={_fmt_time(s)}:end={_fmt_time(e)},"
                               f"asetpts=PTS-STARTPTS[a{i}]")
        n = len(segs)
        if has_audio:
            filt = (";".join(v_parts + a_parts) + ";" +
                    "".join(f"[v{i}][a{i}]" for i in range(n)) +
                    f"concat=n={n}:v=1:a=1[v][a]")
            argv = [exe, "-y", "-i", str(input_path), "-filter_complex", filt,
                    "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
                    "-c:a", "aac", str(output_path)]
        else:
            filt = (";".join(v_parts) + ";" +
                    "".join(f"[v{i}]" for i in range(n)) +
                    f"concat=n={n}:v=1:a=0[v]")
            argv = [exe, "-y", "-i", str(input_path), "-filter_complex", filt,
                    "-map", "[v]", "-c:v", "libx264", str(output_path)]
        ok, msg = _run_ffmpeg(argv)
        if not ok:
            return (False, f"Cut holo na: {msg}")
        return (True, f"✅ Cut holo: {n}-ta tukro → {output_path}")
    except Exception as e:
        return (False, f"Cut korte parlam na: {e}")


def merge(inputs, output_path) -> tuple[bool, str]:
    """Join several videos end-to-end (same codec/size works best; stream
    copy, no re-encode). `inputs` is a list of file paths.
    Returns (ok, message)."""
    try:
        files = [str(p).strip() for p in (inputs or []) if str(p).strip()]
        if len(files) < 2:
            return (False, "Merge korte ontoto 2-ta video file lagbe.")
        for f in files:
            bad = _check_input(f)
            if bad:
                return (False, bad)
        bad = _check_output(output_path)
        if bad:
            return (False, bad)
        exe = _ffmpeg_exe()
        if not exe:
            return (False, "ffmpeg pelam na — prothom bar use-e ami download "
                           "kore nebo, internet on rekhe abar try koro.")
        list_path = os.path.join(tempfile.gettempdir(),
                                 "mark_merge_list.txt")
        try:
            with open(list_path, "w", encoding="utf-8") as fh:
                for f in files:
                    safe = os.path.abspath(f).replace("'", "'\\''")
                    fh.write(f"file '{safe}'\n")
            argv = [exe, "-y", "-f", "concat", "-safe", "0",
                    "-i", list_path, "-c", "copy", str(output_path)]
            ok, msg = _run_ffmpeg(argv)
        finally:
            try:
                os.remove(list_path)
            except Exception:
                pass
        if not ok:
            return (False, f"Merge holo na: {msg}")
        return (True, f"✅ Merge holo: {len(files)}-ta video → {output_path}")
    except Exception as e:
        return (False, f"Merge korte parlam na: {e}")


def _escape_drawtext(text: str) -> str:
    """Escape the characters drawtext treats specially."""
    return (str(text).replace("\\", "\\\\").replace("'", "\\'")
                   .replace(":", "\\:").replace("%", "\\%"))


def add_text(input_path, text, output_path) -> tuple[bool, str]:
    """Burn `text` onto the video (bottom-centre, white on a dark box).
    Re-encodes. Returns (ok, message)."""
    try:
        bad = _check_input(input_path)
        if bad:
            return (False, bad)
        bad = _check_output(output_path)
        if bad:
            return (False, bad)
        text = ("" if text is None else str(text)).strip()
        if not text:
            return (False, "Ki likhbo — text dao.")
        exe = _ffmpeg_exe()
        if not exe:
            return (False, "ffmpeg pelam na — prothom bar use-e ami download "
                           "kore nebo, internet on rekhe abar try koro.")
        filt = (f"drawtext=text='{_escape_drawtext(text)}':fontsize=48:"
                f"fontcolor=white:x=(w-text_w)/2:y=h-100:"
                f"box=1:boxcolor=black@0.5:boxborderw=12")
        argv = [exe, "-y", "-i", str(input_path), "-vf", filt,
                "-c:a", "copy", str(output_path)]
        ok, msg = _run_ffmpeg(argv)
        if not ok:
            return (False, f"Text bosano gelo na: {msg}")
        return (True, f"✅ Text bosalam: \"{text[:60]}\" → {output_path}")
    except Exception as e:
        return (False, f"Text bosate parlam na: {e}")


def thumbnail(input_path, at, output_path) -> tuple[bool, str]:
    """Save one frame at `at` seconds (or 'HH:MM:SS') as an image (PNG/JPG
    by the output extension). Returns (ok, message)."""
    try:
        bad = _check_input(input_path)
        if bad:
            return (False, bad)
        bad = _check_output(output_path)
        if bad:
            return (False, bad)
        t = _parse_time(at)
        if t is None or t < 0:
            return (False, "thumbnail-er somoy dao — second (e.g. 5) ba HH:MM:SS.")
        exe = _ffmpeg_exe()
        if not exe:
            return (False, "ffmpeg pelam na — prothom bar use-e ami download "
                           "kore nebo, internet on rekhe abar try koro.")
        argv = [exe, "-y", "-ss", _fmt_time(t), "-i", str(input_path),
                "-vframes", "1", str(output_path)]
        ok, msg = _run_ffmpeg(argv)
        if not ok:
            return (False, f"Thumbnail holo na: {msg}")
        return (True, f"✅ Thumbnail nilam ({at} second-e) → {output_path}")
    except Exception as e:
        return (False, f"Thumbnail nite parlam na: {e}")


def probe(input_path) -> tuple[bool, str]:
    """Duration + resolution + codecs of a video, via ffprobe.
    Returns (ok, message) — e.g. '🎬 clip.mp4 — 42.5s, 1920x1080, "
    "h264 + aac'. Never raises."""
    try:
        bad = _check_input(input_path)
        if bad:
            return (False, bad)
        exe = _ffprobe_exe()
        if not exe:
            # ffprobe missing but ffmpeg present: fall back to ffmpeg -i.
            exe_ff = _ffmpeg_exe()
            if not exe_ff:
                return (False, "ffprobe/ffmpeg pelam na — prothom bar use-e "
                               "ami download kore nebo.")
            try:
                r = subprocess.run([exe_ff, "-hide_banner", "-i", str(input_path)],
                                   capture_output=True, text=True, timeout=60)
            except Exception as e:
                return (False, f"Video-r info pelam na: {e}")
            info = (r.stderr or "")
            dur = re.search(r"Duration: (\d+:\d+:\d+\.\d+)", info)
            res = re.search(r"(\d{2,5}x\d{2,5})", info)
            parts = [os.path.basename(str(input_path))]
            if dur:
                parts.append(f"Duration {dur.group(1)}")
            if res:
                parts.append(res.group(1))
            return (True, "🎬 " + " — ".join(parts))
        rc, out = _run_ffprobe([exe, "-v", "quiet", "-print_format", "json",
                                "-show_format", "-show_streams",
                                str(input_path)])
        if rc != 0 or not out:
            return (False, "Video-r info pelam na — file-ta thik ache kina dekho.")
        try:
            data = json.loads(out)
        except Exception:
            return (False, "Video-r info porte parlam na.")
        fmt = data.get("format") or {}
        duration = fmt.get("duration", "?")
        streams = data.get("streams") or []
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        parts = [f"🎬 {os.path.basename(str(input_path))}",
                 f"{duration}s"]
        if video:
            parts.append(f"{video.get('width', '?')}x{video.get('height', '?')}")
            parts.append(str(video.get("codec_name", "")))
        if audio:
            parts.append("+ audio " + str(audio.get("codec_name", "")))
        return (True, ", ".join(p for p in parts if p))
    except Exception as e:
        return (False, f"Video-r info pelam na: {e}")
