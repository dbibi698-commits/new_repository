import functools
import json
import os
import secrets
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# ── DATA PROTECTION — NEVER DELETE ───────────────────────────────────────────
# The user asked that saved data NEVER be lost or deleted. The scheme:
#
#   (a) TIMESTAMPED BACKUPS ON EVERY SAVE: before api_keys.json is replaced,
#       the current VALID, non-empty config is copied to
#       config/backups/config-YYYYMMDD-HHMMSS.json (a "-N" suffix is added if
#       two saves land in the same second). The newest 20 backups are kept;
#       older ones are pruned. Backups are made in _write_config, the single
#       write funnel, so every setter is covered. A corrupt or empty current
#       file is never backed up — there is nothing worth keeping in it.
#   (b) AUTO-RESTORE ON LOAD: if api_keys.json cannot be parsed, or parses to
#       an empty dict, load_api_keys() / _read_for_write() restore the newest
#       VALID backup (newest by mtime; a backup that itself fails to parse is
#       skipped) and log it. Only when NO valid backup exists does the old
#       behaviour apply — the broken file is set aside as
#       api_keys.json.broken-<time> and an empty dict is returned.
#   (c) BULK-CLEAR GUARD: data_protection defaults ON (config key
#       "data_protection"). clear_memories() — the one bulk-clear path that
#       lives in this file — refuses to run without confirm=True while the
#       toggle is ON, and logs the refusal; with confirm=True it clears and
#       logs how many entries went. bulk_clear_guard(action, confirm) is the
#       same check for bulk-clear paths elsewhere (todo / dictation /
#       upload-queue clears in plugins/): call it before deleting, and abort
#       when it returns False. Per-item deletes (one memory, one fact) are
#       NOT guarded — deleting one thing you chose is not a bulk wipe.
#   No code anywhere writes config/api_keys.json directly; everything goes
#   through this file.

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def config_exists() -> bool:
    return CONFIG_FILE.exists()


# ── Reading and writing the file ─────────────────────────────────────────────
# Many threads use this file at once: the interface, the conversation loop,
# plugins polling a server, background tasks. Every setter read the file,
# changed one key and rewrote it IN PLACE, which failed two ways:
#
#   * a reader that arrived mid-write saw half a file, parsed nothing, and
#     treated every setting as unset — wake word off, no key, Gemini mode;
#   * a SETTER that arrived mid-write did the same, then wrote its one key into
#     an otherwise empty dict — erasing every other setting for good.
#
# Writes now go to a temporary file that replaces the real one in a single step,
# so a reader sees the old file or the new one and never half of either, and
# setters in this process take turns.
_lock = threading.RLock()


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _lock:
            return fn(*args, **kwargs)
    return wrapper


BACKUP_KEEP = 20  # newest backups kept in config/backups/; older are pruned


def _backup_dir() -> Path:
    # Computed from CONFIG_DIR at call time (not a module constant) so tests
    # can point CONFIG_DIR at a scratch folder and the backups follow it.
    return CONFIG_DIR / "backups"


def _backup_name() -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    base = f"config-{stamp}.json"
    if not (_backup_dir() / base).exists():
        return base
    n = 1
    while (_backup_dir() / f"config-{stamp}-{n}.json").exists():
        n += 1
    return f"config-{stamp}-{n}.json"


def _backup_config() -> None:
    """Copy the current VALID, non-empty config to config/backups/.

    Called by _write_config before the file is replaced, so every save is
    covered. A corrupt or empty current file is never backed up. Never
    raises — a failed backup must never block the save itself."""
    try:
        if not CONFIG_FILE.exists():
            return
        try:
            current = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(current, dict) or not current:
            return
        d = _backup_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / _backup_name()).write_text(
            json.dumps(current, indent=4), encoding="utf-8")
        _prune_backups()
    except Exception as e:
        print(f"[Config] backup failed: {e}")


def _prune_backups() -> None:
    """Keep the newest BACKUP_KEEP backups (by mtime); delete older ones."""
    try:
        d = _backup_dir()
        if not d.exists():
            return
        files = sorted(
            (p for p in d.glob("config-*.json") if p.is_file()),
            key=lambda p: p.stat().st_mtime)
        if len(files) > BACKUP_KEEP:
            for p in files[:-BACKUP_KEEP]:
                try:
                    p.unlink()
                except OSError:
                    pass
    except Exception:
        pass


def _valid_backup_files() -> list:
    """Backup files, newest first (by mtime)."""
    d = _backup_dir()
    if not d.exists():
        return []
    return sorted(
        (p for p in d.glob("config-*.json") if p.is_file()),
        key=lambda p: p.stat().st_mtime, reverse=True)


def _read_backup(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and data else None
    except Exception:
        return None


def list_config_backups() -> list:
    """Names of the timestamped backups, newest first."""
    return [p.name for p in _valid_backup_files()]


def _restore_newest_backup() -> dict:
    """Write the newest VALID backup over api_keys.json.

    A backup that itself fails to parse is skipped in favour of the next
    older one. Returns the restored dict, or {} when no valid backup exists.
    Never raises."""
    for path in _valid_backup_files():
        data = _read_backup(path)
        if data is None:
            continue
        try:
            ensure_config_dir()
            tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
            tmp.write_text(json.dumps(data, indent=4), encoding="utf-8")
            os.replace(tmp, CONFIG_FILE)
            print(f"[Config] api_keys.json restored from backup {path.name} "
                  f"- data protection: nothing was lost.")
            return data
        except Exception as e:
            print(f"[Config] restore from {path.name} failed: {e}")
            continue
    return {}


def _write_config(data: dict) -> None:
    ensure_config_dir()
    _backup_config()
    tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=4), encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, CONFIG_FILE)
            return
        except PermissionError:
            # Windows: an antivirus scan or a reader can hold the file for a
            # moment. Worth a short wait, never a lost setting.
            if attempt == 19:
                raise
            time.sleep(0.05)


def _read_for_write() -> dict:
    """The current settings, for a setter to change one of them.

    A file that exists but cannot be parsed is set aside as
    api_keys.json.broken-<time> rather than silently replaced by one key — it
    may be a hand edit with a missing comma, and it still holds the user's key."""
    if not CONFIG_FILE.exists():
        return {}
    last = None
    for _ in range(3):
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError) as e:
            last = e
            time.sleep(0.05)
    restored = _restore_newest_backup()
    if restored:
        return restored
    backup = CONFIG_FILE.with_name(f"{CONFIG_FILE.name}.broken-{int(time.time())}")
    try:
        os.replace(CONFIG_FILE, backup)
        print(f"[Config] api_keys.json could not be read ({last}) - kept as {backup.name}")
    except Exception:
        pass
    return {}

@_locked
def save_api_keys(gemini_api_key: str) -> None:
    ensure_config_dir()

    data = _read_for_write()

    data["gemini_api_key"] = gemini_api_key.strip()
    if data["gemini_api_key"]:
        data.pop("local_only", None)     # a key given is a choice to use Gemini again
    _write_config(data)

def load_api_keys() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    for attempt in range(3):
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if data:
                    return data
                break  # empty dict: an empty config — try to restore below
            return {}
        except Exception as e:
            if attempt == 2:
                # Plain text: an emoji here raised UnicodeEncodeError on a
                # Windows console, turning a failed read into a crash.
                print(f"[Config] Failed to load api_keys.json: {e}")
            else:
                time.sleep(0.05)
    # Corrupt or empty: auto-restore the newest valid backup (never delete).
    # Re-read under the lock first — another thread may have restored it
    # already while this one was retrying.
    with _lock:
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return data
        except Exception:
            pass
        restored = _restore_newest_backup()
        if restored:
            return restored
    return {}

def get_gemini_key() -> str | None:
    return load_api_keys().get("gemini_api_key")

def is_configured() -> bool:
    key = get_gemini_key()
    return bool(key and len(key) > 15)


def get_assistant_name() -> str:
    """Return the configured assistant name, or 'JARVIS' if not set."""
    return load_api_keys().get("assistant_name", "JARVIS") or "JARVIS"


def get_user_name() -> str:
    """Return the configured user name for addressing."""
    return load_api_keys().get("user_name", "")


@_locked
def save_assistant_config(assistant_name: str, user_name: str) -> None:
    """Persist assistant name and user name to config."""
    ensure_config_dir()
    data = _read_for_write()
    data["assistant_name"] = assistant_name.strip() or "JARVIS"
    data["user_name"] = user_name.strip()
    _write_config(data)


# ── Assistant voice ──────────────────────────────────────────────────────────
# Gemini Live prebuilt voices. Names are proper nouns — identical in every
# language, so this list is safe to show verbatim in any locale.
AVAILABLE_VOICES = ["Charon", "Puck", "Kore", "Fenrir", "Aoede"]
DEFAULT_VOICE    = "Charon"


def get_voice() -> str:
    """Return the configured Live voice, falling back to the default if unset
    or if the stored value is not a voice we recognise."""
    v = load_api_keys().get("voice_name", DEFAULT_VOICE) or DEFAULT_VOICE
    return v if v in AVAILABLE_VOICES else DEFAULT_VOICE


@_locked
def save_voice(voice_name: str) -> None:
    """Persist the chosen Live voice. Unknown names collapse to the default so a
    bad value can never reach the API and break the session."""
    ensure_config_dir()
    data = _read_for_write()
    v = (voice_name or "").strip()
    data["voice_name"] = v if v in AVAILABLE_VOICES else DEFAULT_VOICE
    _write_config(data)


def get_wake_word_enabled() -> bool:
    """Whether local wake-word gating is on (assistant sleeps until 'Hey Jarvis')."""
    return load_api_keys().get("wake_word_enabled", False)


@_locked
def save_wake_word_enabled(enabled: bool) -> None:
    ensure_config_dir()
    data = _read_for_write()
    data["wake_word_enabled"] = bool(enabled)
    _write_config(data)


def get_push_to_talk_enabled() -> bool:
    """Hold-a-key-to-speak. When on, the mic is closed unless the chord is held."""
    return load_api_keys().get("push_to_talk_enabled", False)


def save_push_to_talk_enabled(enabled: bool) -> None:
    _save_flag("push_to_talk_enabled", enabled)


HUD_STYLES = ("face", "core")


def get_hud_style() -> str:
    """Which centrepiece the HUD draws: the animated head, or the reactor core.

    Taste, not capability — both render in the same software painter and cost
    about the same. Defaults to the head because that is what MARK LIV shipped
    with; anyone who preferred the older look can switch back in ⚙ and the
    choice survives a restart.
    """
    v = str(load_api_keys().get("hud_style", "face")).strip().lower()
    return v if v in HUD_STYLES else "face"


def save_hud_style(style: str) -> None:
    s = str(style or "").strip().lower()
    _save_flag("hud_style", s if s in HUD_STYLES else "face")


def get_ui_scale() -> float:
    """How much larger than designed the whole interface is drawn, or 0 for
    'work it out from the screen'.

    Read once, before the window exists — Qt only takes a scale factor at
    start-up, so a change here applies on the next launch."""
    try:
        v = float(load_api_keys().get("ui_scale", 0) or 0)
    except (TypeError, ValueError):
        return 0.0
    return min(v, 3.0) if v >= 0.5 else 0.0


def save_ui_scale(scale: float) -> None:
    _save_flag("ui_scale", float(scale or 0))


# ── Live-session tuning ──────────────────────────────────────────────────────
# Everything here is optional and has a working default, so an untouched
# config behaves exactly like a configured one. Each value is also a way out:
# if a future model dislikes one of these, set it back and nothing else changes.

def get_thinking_enabled() -> bool:
    """Whether the Live model may spend tokens thinking before it answers.

    Off by default. A voice assistant is judged on how fast it starts talking,
    and the reasoning that actually needs deliberation in this app is delegated
    to the planning tools, which run on a separate non-Live model.
    """
    return bool(load_api_keys().get("thinking_enabled", False))


def save_thinking_enabled(enabled: bool) -> None:
    _save_flag("thinking_enabled", enabled)


def get_turn_tuning() -> dict:
    """How eagerly the server decides you have stopped speaking.

    OFF by default, and that default was earned. Cutting turns shorter looks
    like a free speed win and is not: proactive audio has to judge whether an
    utterance was even addressed to the assistant, and a turn clipped early
    gives it less to judge, so it stays quiet — and the reply to your first
    sentence only arrives once your second one has given it enough context.
    That reads as the assistant being a turn behind, which is far worse than
    the fraction of a second the tuning saves.

    Turn it on with "turn_tuning": {"enabled": true} if your own microphone and
    speaking pace suit it. `silence_ms` is the one that is felt: the pause the
    server sits through before accepting your turn is over.
    """
    cfg = load_api_keys().get("turn_tuning")
    cfg = cfg if isinstance(cfg, dict) else {}

    def _int(key, default, lo, hi):
        try:
            return max(lo, min(hi, int(cfg.get(key, default))))
        except (TypeError, ValueError):
            return default

    return {
        "enabled":    bool(cfg.get("enabled", False)),
        "silence_ms": _int("silence_ms", 550, 200, 3000),
        "prefix_ms":  _int("prefix_ms", 150, 0, 1000),
        # "high" = quicker to decide speech has ended.
        "end_sensitivity":   str(cfg.get("end_sensitivity", "high")).lower(),
        "start_sensitivity": str(cfg.get("start_sensitivity", "default")).lower(),
    }


@_locked
def save_turn_tuning(values: dict) -> None:
    ensure_config_dir()
    data = _read_for_write()
    cur = data.get("turn_tuning")
    cur = dict(cur) if isinstance(cur, dict) else {}
    cur.update(values or {})
    data["turn_tuning"] = cur
    _write_config(data)


def get_proactive_audio_enabled() -> bool:
    """Whether the model gets to decide an utterance was not aimed at it and
    stay quiet.

    On by default — it is what stops the assistant answering the room. But it
    is also the first thing to switch off if replies ever seem to arrive a turn
    late: what looks like lag is usually the model having judged your previous
    sentence as not addressed to it, and only changing its mind once the next
    one arrives.
    """
    return bool(load_api_keys().get("proactive_audio", True))


def save_proactive_audio_enabled(enabled: bool) -> None:
    _save_flag("proactive_audio", enabled)


MEDIA_RESOLUTIONS = ("default", "low", "medium", "high")


def get_media_resolution() -> str:
    """How finely the model tokenises the screenshots and camera frames it is
    sent. 'medium' keeps on-screen text readable at a fraction of the tokens a
    full-resolution frame costs; 'low' is cheaper still but starts losing small
    text, which is most of what screen captures are for."""
    v = str(load_api_keys().get("media_resolution", "medium")).strip().lower()
    return v if v in MEDIA_RESOLUTIONS else "medium"


def save_media_resolution(value: str) -> None:
    v = str(value or "").strip().lower()
    _save_flag("media_resolution", v if v in MEDIA_RESOLUTIONS else "medium")


@_locked
def _save_flag(key: str, value) -> None:
    """Read-modify-write one key without disturbing the rest of the config."""
    ensure_config_dir()
    data = _read_for_write()
    data[key] = bool(value) if isinstance(value, bool) else value
    _write_config(data)


def get_brief_enabled() -> bool:
    return load_api_keys().get("morning_brief_enabled", True)


@_locked
def save_brief_enabled(enabled: bool) -> None:
    ensure_config_dir()
    data = _read_for_write()
    data["morning_brief_enabled"] = enabled
    _write_config(data)


# ── Audio devices ────────────────────────────────────────────────────────────
# Stored as device NAMES, not sounddevice indices. Indices shift every time a
# USB device is plugged in or removed, so a saved index silently starts pointing
# at a different microphone. The empty string means "system default", which is
# both the factory setting and what an unresolvable saved device falls back to —
# so unplugging a headset degrades to the built-in speakers instead of crashing.

@_locked
def _patch_config(**fields) -> None:
    """Read-modify-write one or more keys in api_keys.json.

    Every setter in this file open-coded this. Collapsing it here means a new
    setting is one line, and there is one place where a corrupt config file is
    handled instead of nine."""
    ensure_config_dir()
    data = _read_for_write()
    data.update(fields)
    _write_config(data)


def update_config(**fields) -> None:
    """Set one or more top-level settings, leaving every other one as it is.
    For code outside this file that used to rewrite api_keys.json itself."""
    _patch_config(**fields)


def get_input_device() -> str:
    """Microphone device name, or '' for the system default."""
    return (load_api_keys().get("input_device", "") or "").strip()


def save_input_device(name: str) -> None:
    _patch_config(input_device=(name or "").strip())


def get_output_device() -> str:
    """Speaker device name, or '' for the system default."""
    return (load_api_keys().get("output_device", "") or "").strip()


def save_output_device(name: str) -> None:
    _patch_config(output_device=(name or "").strip())


def get_plugin_enabled(plugin_name: str) -> bool:
    """Plugins are enabled by default the moment they're discovered (opt-out model)."""
    return load_api_keys().get("plugins_enabled", {}).get(plugin_name, True)


# ── Per-plugin settings ("tokens" / connection details) ───────────────────────
# Generic store so a plugin can declare its own config fields (PLUGIN_SETTINGS)
# and the settings UI renders + persists them WITHOUT any core edit — keeping the
# drop-in model intact. Values live under plugin_config[<namespace>][<key>].
# A namespace defaults to the plugin name, but a suite of plugins (e.g. the
# several printer plugins) can share ONE namespace.
def get_plugin_config(namespace: str) -> dict:
    """All stored values for a namespace (empty dict if none set yet)."""
    cfg = load_api_keys().get("plugin_config")
    val = cfg.get(namespace) if isinstance(cfg, dict) else None
    return dict(val) if isinstance(val, dict) else {}


def get_plugin_setting(namespace: str, key: str, default=None):
    """A single value from a namespace, or `default` if unset."""
    return get_plugin_config(namespace).get(key, default)


@_locked
def save_plugin_config(namespace: str, values: dict) -> None:
    """Merge `values` into a namespace's stored config (read-modify-write, like
    every other helper here). Only the provided keys are touched."""
    ensure_config_dir()
    data = _read_for_write()
    pc = data.get("plugin_config")
    if not isinstance(pc, dict):
        pc = {}
    cur = pc.get(namespace)
    if not isinstance(cur, dict):
        cur = {}
    cur.update(values)
    pc[namespace] = cur
    data["plugin_config"] = pc
    _write_config(data)


@_locked
def save_plugin_enabled(plugin_name: str, enabled: bool) -> None:
    ensure_config_dir()
    data = _read_for_write()
    plugins_cfg = data.get("plugins_enabled")
    if not isinstance(plugins_cfg, dict):
        plugins_cfg = {}
    plugins_cfg[plugin_name] = enabled
    data["plugins_enabled"] = plugins_cfg
    _write_config(data)

# ── Providers: local STT/LLM/TTS and non-Gemini APIs ─────────────────────────
# Stored here rather than in a file of their own, for the same reason plugin
# settings are: one config to back up, one already in .gitignore, one place a
# user knows to look.
#
# The important property is what happens when nobody has configured anything.
# `get_provider_mode()` returns "gemini" on a config that has never heard of
# providers, and every caller checks that BEFORE importing the providers
# package — so an ordinary install never executes a line of it. This is the
# whole basis of the claim that the folder costs nothing when unused.
PROVIDER_MODE_GEMINI = "gemini"      # the conversation runs on the Live API
PROVIDER_MODE_PIPELINE = "pipeline"  # STT -> LLM -> TTS, assembled from providers


def _upgrade_ids(block: dict) -> dict:
    """Give every catalog service its own id and its own stored settings.

    One provider serves Ollama, OpenAI, MiniMax and a dozen more, and they used
    to share ONE block of settings under "openai_compat" — so the fallback and
    ② THINKING could not be two different services, picking one overwrote the
    other's address, and an API key typed for MiniMax was sent to OpenAI after
    a switch. Each service is now "<provider>@<entry>", e.g.
    "openai_compat@minimax", with settings of its own.

    An older config is converted as it is read, not by a migration step: the
    shared block moves to the service its "catalog" key names (its key belonged
    to that service and nothing else), and every reference to it follows.
    Writing the providers block back persists it; until then nothing on disk
    changes."""
    creds = block.get("creds")
    if not isinstance(creds, dict):
        return block
    creds = dict(creds)
    moved: dict = {}
    for pid, cfg in list(creds.items()):
        if "@" in pid or not isinstance(cfg, dict):
            continue
        eid = str(cfg.get("catalog") or "").strip()
        if not eid:
            continue
        new = f"{pid}@{eid}"
        creds.setdefault(new, dict(cfg))
        del creds[pid]
        moved[pid] = new
    if not moved:
        return block
    block = dict(block)
    block["creds"] = creds
    pipe = block.get("pipeline")
    if isinstance(pipe, dict):
        block["pipeline"] = {k: moved.get(v, v) for k, v in pipe.items()}
    for key in ("sidecar", "coding"):
        if block.get(key) in moved:
            block[key] = moved[block[key]]
    return block


def get_providers() -> dict:
    """The whole providers block, or an empty dict."""
    val = load_api_keys().get("providers")
    return _upgrade_ids(dict(val)) if isinstance(val, dict) else {}


def get_provider_mode() -> str:
    """Which engine holds the conversation. Defaults to Gemini Live."""
    mode = str(get_providers().get("mode", "") or "").strip().lower()
    return mode if mode in (PROVIDER_MODE_GEMINI, PROVIDER_MODE_PIPELINE) \
        else PROVIDER_MODE_GEMINI


def get_provider_config(provider_id: str) -> dict:
    """Stored settings for one provider — address, model, key, limits."""
    creds = get_providers().get("creds")
    val = creds.get(provider_id) if isinstance(creds, dict) else None
    return dict(val) if isinstance(val, dict) else {}


def get_pipeline() -> dict:
    """Which provider fills each slot of the pipeline engine."""
    val = get_providers().get("pipeline")
    return dict(val) if isinstance(val, dict) else {}


def get_sidecar_provider() -> str:
    """The provider id used for one-shot calls when Gemini cannot answer them,
    or '' for none.

    Separate from the conversation on purpose: these are different jobs with
    different failure modes. Gemini's Live quota and its text quota are separate
    pools, and on the free tier it is the text pool that runs out first — which
    kills document reading, screen reasoning and code generation while the
    conversation carries on. Being able to point only those at another model,
    without changing the voice at all, is the cheapest useful thing this whole
    folder does.
    """
    return str(get_providers().get("sidecar", "") or "").strip()


@_locked
def _patch_providers(**fields) -> None:
    p = get_providers()
    p.update(fields)
    _patch_config(providers=p)


def save_provider_mode(mode: str) -> None:
    mode = (mode or "").strip().lower()
    _patch_providers(mode=mode if mode in (PROVIDER_MODE_GEMINI,
                                           PROVIDER_MODE_PIPELINE)
                     else PROVIDER_MODE_GEMINI)


@_locked
def save_provider_config(provider_id: str, values: dict) -> None:
    """Merge settings for one provider. Only the given keys are touched, so the
    panel can save one field without reading and rewriting the rest."""
    p = get_providers()
    creds = p.get("creds")
    if not isinstance(creds, dict):
        creds = {}
    cur = creds.get(provider_id)
    cur = dict(cur) if isinstance(cur, dict) else {}
    cur.update(values or {})
    creds[provider_id] = cur
    p["creds"] = creds
    _patch_config(providers=p)


@_locked
def save_pipeline(stt: str = None, llm: str = None, tts: str = None) -> None:
    """Set one or more pipeline slots. `None` leaves a slot alone; '' clears it."""
    p = get_providers()
    pipe = p.get("pipeline")
    pipe = dict(pipe) if isinstance(pipe, dict) else {}
    for slot, value in (("stt", stt), ("llm", llm), ("tts", tts)):
        if value is not None:
            pipe[slot] = str(value).strip()
    p["pipeline"] = pipe
    _patch_config(providers=p)


def save_sidecar_provider(provider_id: str) -> None:
    _patch_providers(sidecar=(provider_id or "").strip())


def get_coding_provider() -> str:
    """The service dev_agent writes code with, or '' to use whatever answers
    background requests.

    Its own setting because coding is the one background job where the model
    matters most and the request is longest — somebody may well want a strong
    coding model there and something cheap and fast for reading the screen."""
    return str(get_providers().get("coding", "") or "").strip()


def save_coding_provider(provider_id: str) -> None:
    _patch_providers(coding=(provider_id or "").strip())


def get_sidecar_first() -> bool:
    """Whether the side-call provider is tried BEFORE Gemini rather than after.

    Off by default: measured in core/gemini.py, the Gemini rungs answer a short
    request in well under a second, and a local model on ordinary hardware does
    not. On means something specific — 'I would rather this stayed on my
    machine, and I accept it being slower' — so it is a choice someone makes,
    never a default they inherit.
    """
    return bool(get_providers().get("sidecar_first", False))


def save_sidecar_first(enabled: bool) -> None:
    _patch_providers(sidecar_first=bool(enabled))


@_locked
def save_providers(mode: str = None, pipeline: dict = None, creds: dict = None,
                   sidecar: str = None, sidecar_first: bool = None,
                   coding: str = None) -> None:
    """Write the whole providers block in ONE file write.

    The settings panel used to call five setters in a row — one per provider's
    credentials, then the mode, then the pipeline, then the two side-call
    keys — and every one of them was a separate read-modify-write of
    api_keys.json. Five reads and five writes of the same file, in sequence,
    while the panel's own APPLY was already triggering a reconnect that makes
    main.py write to it too. Any interleaving loses whichever key was written
    first, and the one people noticed was the mode: set MY OWN SETUP, save,
    reopen, and it says Gemini again.

    `None` leaves a section alone; `creds` is merged per provider so a panel
    that only edited one does not have to send the others.
    """
    ensure_config_dir()
    data = _read_for_write()

    block = data.get("providers")
    block = _upgrade_ids(dict(block)) if isinstance(block, dict) else {}

    if mode is not None:
        m = str(mode).strip().lower()
        block["mode"] = m if m in (PROVIDER_MODE_GEMINI,
                                   PROVIDER_MODE_PIPELINE) else PROVIDER_MODE_GEMINI
    if pipeline is not None:
        current = block.get("pipeline")
        current = dict(current) if isinstance(current, dict) else {}
        current.update({k: str(v or "").strip() for k, v in pipeline.items()})
        block["pipeline"] = current
    if creds is not None:
        store = block.get("creds")
        store = dict(store) if isinstance(store, dict) else {}
        for pid, values in (creds or {}).items():
            one = store.get(pid)
            one = dict(one) if isinstance(one, dict) else {}
            one.update(values or {})
            store[pid] = one
        block["creds"] = store
    if sidecar is not None:
        block["sidecar"] = str(sidecar or "").strip()
    if sidecar_first is not None:
        block["sidecar_first"] = bool(sidecar_first)
    if coding is not None:
        block["coding"] = str(coding or "").strip()

    data["providers"] = block
    _write_config(data)

# ── Quick memories ("memories" list) ─────────────────────────────────────────
# Short things the user asks Jarvis to remember, kept in config under
# "memories" — separate from memory/long_term.json facts (which the Memory
# panel shows). Shown in the Settings Memory box and in the Memory panel's
# "quick memories" section. Never auto-deleted: nothing here prunes, expires
# or caps the list; only a per-item delete, or clear_memories(confirm=True),
# removes anything.
def _memories_from(data: dict) -> list:
    raw = data.get("memories")
    if not isinstance(raw, list):
        return []
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        out.append({
            "id": str(entry.get("id") or ""),
            "text": text,
            "created_at": str(entry.get("created_at") or ""),
        })
    return out


def get_memories() -> list:
    """All saved quick memories, oldest first: {"id", "text", "created_at"}."""
    return _memories_from(load_api_keys())


@_locked
def add_memory(text: str) -> dict | None:
    """Save one quick memory. Returns the stored entry, or None when blank."""
    text = (text or "").strip()
    if not text:
        return None
    entry = {
        "id": f"mem-{int(time.time() * 1000)}-{secrets.token_hex(3)}",
        "text": text[:500],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    data = _read_for_write()
    mems = _memories_from(data)
    mems.append(entry)
    data["memories"] = mems
    _write_config(data)
    return entry


@_locked
def delete_memory(index_or_id) -> bool:
    """Delete ONE quick memory by its id (str) or its position (int).

    Per-item only — this is not a bulk clear, so the data-protection guard
    does not apply. Returns False when nothing matches."""
    data = _read_for_write()
    mems = _memories_from(data)
    target = None
    if isinstance(index_or_id, int) and not isinstance(index_or_id, bool):
        if 0 <= index_or_id < len(mems):
            target = index_or_id
    else:
        want = str(index_or_id or "").strip()
        for i, entry in enumerate(mems):
            if entry.get("id") == want:
                target = i
                break
    if target is None:
        return False
    del mems[target]
    data["memories"] = mems
    _write_config(data)
    return True


def search_memories(query: str) -> list:
    """Quick memories whose text contains `query` (case-insensitive).

    An empty query returns everything, oldest first."""
    q = (query or "").strip().lower()
    mems = get_memories()
    if not q:
        return mems
    return [m for m in mems if q in m["text"].lower()]


# ── Data-protection toggle + bulk-clear guard ────────────────────────────────
def get_data_protection() -> bool:
    """Whether the never-delete guard is on. Default ON."""
    return bool(load_api_keys().get("data_protection", True))


def save_data_protection(enabled: bool) -> None:
    _patch_config(data_protection=bool(enabled))


def bulk_clear_guard(action: str, confirm: bool = False) -> bool:
    """The bulk-clear check, shared by every delete-all path.

    Returns True when the clear may run: either data protection is OFF, or
    the caller passed confirm=True (an explicit human confirmation, never a
    default). Returns False and logs the refusal otherwise — the caller must
    abort and delete nothing. `action` names the thing being cleared, for
    the log line only."""
    if get_data_protection() and not confirm:
        print(f"[Config] Data protection ON — bulk clear of {action} refused "
              f"without confirm=True. Nothing was deleted.")
        return False
    return True


@_locked
def clear_memories(confirm: bool = False) -> bool:
    """Delete ALL quick memories. Guarded by bulk_clear_guard: with data
    protection ON (the default) this returns False and deletes nothing
    unless confirm=True is passed explicitly. Logs how many went."""
    if not bulk_clear_guard("memories", confirm):
        return False
    data = _read_for_write()
    n = len(_memories_from(data))
    data["memories"] = []
    _write_config(data)
    print(f"[Config] clear_memories: {n} memories cleared (confirm=True).")
    return True


# ── Assistant logos ──────────────────────────────────────────────────────────
# 12 changeable logos in assets/logos/, picked in Customize Assistant.
# The choice is a config key, "assistant_logo"; nothing selected ("") means
# the existing look, unchanged.
ASSISTANT_LOGOS = (
    "logo_01_cyan_star.png",
    "logo_02_magenta_diamond.png",
    "logo_03_gold_bolt.png",
    "logo_04_green_hexagon.png",
    "logo_05_violet_crescent.png",
    "logo_06_orange_triangle.png",
    "logo_07_blue_circle.png",
    "logo_08_pink_wave.png",
    "logo_09_teal_eye.png",
    "logo_10_red_crown.png",
    "logo_11_lime_infinity.png",
    "logo_12_indigo_note.png",
)


def _logos_dir() -> Path:
    # Computed at call time so tests can redirect BASE_DIR if they need to.
    return BASE_DIR / "assets" / "logos"


def get_assistant_logo() -> str:
    """The selected logo filename, or "" for the default look."""
    v = str(load_api_keys().get("assistant_logo", "") or "").strip()
    return v if v in ASSISTANT_LOGOS else ""


def save_assistant_logo(name: str) -> bool:
    """Persist the logo choice. "" clears it (back to the default look).
    An unknown filename is rejected and the stored choice is left alone."""
    name = (name or "").strip()
    if name and name not in ASSISTANT_LOGOS:
        return False
    _patch_config(assistant_logo=name)
    return True


def assistant_logo_path(name: str | None = None):
    """Full path of the selected logo (or of `name`), or None when there is
    no selection or the file is missing."""
    n = name if name is not None else get_assistant_logo()
    if not n:
        return None
    p = _logos_dir() / n
    return p if p.is_file() else None
