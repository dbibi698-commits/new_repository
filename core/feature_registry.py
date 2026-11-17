"""core/feature_registry.py — formula-based 23,720,000-feature registry.

Replaces the stored 20,000-record data/features.json (and its generator
data/gen_features.py) with a resolver that computes every feature from its
number. No list is stored anywhere: a 23,720,000-record JSON would be ~3 GB.

Structure (source of truth: ~/workspace/.tmp/gen20000.py for CATEGORIES /
PATTERNS, ~/workspace/.tmp/gen1000000.py for CONTEXTS,
~/workspace/.tmp/gen2000000_ext.py for CONTEXTS2,
~/workspace/.tmp/vol3_spec.py for CONTEXTS3,
~/workspace/.tmp/vol4_spec.py for CONTEXTS4,
~/workspace/.tmp/vol5_spec.py for CONTEXTS5 and
~/workspace/.tmp/vol6_spec.py for CONTEXTS6,
~/workspace/.tmp/vol7_spec_mark.py for CONTEXTS7):
  Volume 1 (numbers 1-1,000,000):
    100 categories x 500 targets x 20 patterns = 1,000,000 features.
    Targets per category: 10 plain + 10 base x 49 contexts = 500.
    targets_for(): first 10 are the plain targets; t >= 10 ->
        base = cat_targets[(t-10)//49], context = CONTEXTS[(t-10)%49],
        target string f"{base} for {ctx}".
    Numbering: number = c*10000 + t*20 + p + 1
        (c 0-based category, t 0..499 target, p 0..19 pattern).
  Volume 2 (numbers 1,000,001-3,000,000):
    100 categories x 1,000 targets x 20 patterns = 2,000,000 features.
    Targets per category: 10 base x 100 NEW contexts = 1,000 (all
    contextual, no plain). Numbering: e = n - 1,000,001;
        c = e // 20000; t = (e % 20000) // 20; p = e % 20;
        target = base_targets[c][t // 100] + " for " + CONTEXTS2[t % 100].
    Each category covers 20,000 numbers in Volume 2.
  Volume 3 (numbers 3,000,001-4,000,000):
    100 categories x 500 targets x 20 patterns = 1,000,000 features.
    Targets per category: 10 base x 50 NEW contexts = 500 (all
    contextual, no plain). Numbering: e = n - 3,000,001;
        c = e // 10000; t = (e % 10000) // 20; p = e % 20;
        target = base_targets[t // 50] + " for " + CONTEXTS3[t % 50].
    Each category covers 10,000 numbers in Volume 3.
  Volume 4 (numbers 4,000,001-4,700,000):
    100 categories x 350 targets x 20 patterns = 700,000 features.
    Targets per category: 10 base x 35 NEW contexts = 350 (all
    contextual, no plain). Numbering: e = n - 4,000,001;
        c = e // 7000; t = (e % 7000) // 20; p = e % 20;
        target = base_targets[t // 35] + " for " + CONTEXTS4[t % 35].
    Each category covers 7,000 numbers in Volume 4.
  Volume 5 (numbers 4,700,001-6,700,000):
    100 categories x 1,000 targets x 20 patterns = 2,000,000 features.
    Targets per category: 10 base x 100 NEW contexts = 1,000 (all
    contextual, no plain). Numbering: e = n - 4,700,001;
        c = e // 20000; t = (e % 20000) // 20; p = e % 20;
        target = base_targets[t // 100] + " for " + CONTEXTS5[t % 100].
    Each category covers 20,000 numbers in Volume 5.
  Volume 6 (numbers 6,700,001-13,700,000):
    100 categories x 3,500 targets x 20 patterns = 7,000,000 features.
    Targets per category: 10 base x 350 NEW contexts = 3,500 (all
    contextual, no plain). Numbering: e = n - 6,700,001;
        c = e // 70000; t = (e % 70000) // 20; p = e % 20;
        target = base_targets[t // 350] + " for " + CONTEXTS6[t % 350].
    Each category covers 70,000 numbers in Volume 6.
  Volume 7 (numbers 13,700,001-23,720,000):
    100 categories x 5,010 targets x 20 patterns = 10,020,000 features.
    Targets per category: 10 base x 500 NEW contexts = 5,000 contextual,
    PLUS the 10 plain base targets LAST (t = 5000..5009).
    Numbering: e = n - 13,700,001; c = e // 100200;
        t = (e % 100200) // 20; p = e % 20;
        t < 5000: target = base_targets[t // 500] + " for " + CONTEXTS7[t % 500];
        t >= 5000: target = base_targets[t - 5000] (plain, no context).
    Each category covers 100,200 numbers in Volume 7.
  Total: 23,720,000. The first 200 numbers of each category are identical
  to the old 20,000-feature registry (same name/description/status/tool,
  except the old JSON's dedup suffixes " Plus" / " Ultra" on 420
  duplicate names — those suffixes are NOT reproduced; resolve by
  number, never by name). Volume 2/3/4/5/6 names may carry the same dedup
  suffixes in their PDFs; the resolver never reproduces them. Volume 7
  names may collide with Volume 1-6 names (187 of the 500 CONTEXTS7
  names already appear in Vols 1-6 contexts); collisions are accepted,
  as in Vol 6 — features resolve by number.

Status + tool mapping — Phase 1 rules ported from data/gen_features.py
(STATUS_RULES). Rules apply per (category_idx, target, pattern):
for t < 10 the rule applies directly; for t >= 10 the BASE target's rule
applies (status/tool/args of the base target's feature). Resolution order
is WORKING -> NEEDS-KEY -> NEEDS-DEVICE -> PLANNED (first match wins).
Conservative by design: WORKING only where the capability exists in
Mark-LVII AND was exercised/verified; when in doubt, PLANNED.

  WORKING (categories 1-10 only): each target in WORKING_MAP maps to the
    tool that implements it. A WORKING target is only WORKING for the CORE
    patterns (Voice control / Live dashboard / Quick actions — every tool
    is voice-invokable, shows on the HUD, and is usable as a quick action)
    plus the per-target `extra` patterns; any other pattern of a working
    target falls through to PLANNED. Deliberately NOT working (kept
    PLANNED despite sounding close): "live voice call" (no live call,
    only voice-message replies via phone_say), "wake-word detection"
    (always-on Gemini Live, not a wake word), "think-before-speaking",
    "girlfriend mode" / "comedy mode" (the 5 shipped moods are friendly /
    playful / caring / serious / boss), "wallpaper changer" /
    "music control" / "photo slideshow" (wanted, not verified).
  NEEDS-KEY: the capability exists as a tool but needs the user's own
    account, token or API key (set in Settings, never in chat). Whole
    categories in NEEDS_KEY_CATEGORIES plus the per-target sets in
    NEEDS_KEY_TARGETS. NEEDS-KEY features keep their owning `tool` so the
    features plugin can dispatch to it and the tool itself reports the
    missing key honestly.
  NEEDS-DEVICE: needs hardware Mark-LVII cannot conjure (drone, 3D
    printer, robot, car/dashcam, smart-home device, printer, projector,
    Bluetooth device, camera hardware, game controller, TV/cast receiver,
    phone sensors or a wearable). Whole categories in
    NEEDS_DEVICE_CATEGORIES plus NEEDS_DEVICE_TARGETS.
  PLANNED: everything else — a real idea, not built yet; no key or device
    would unblock it. This also covers real tools that exist OUTSIDE
    categories 1-10 (e.g. flight_finder, save_memory): Phase 1 only
    verifies and promotes categories 1-10 to WORKING.

The structure itself (CATEGORIES, PATTERNS, CONTEXTS, CONTEXTS2, CONTEXTS3,
CONTEXTS4, CONTEXTS5, CONTEXTS6, CONTEXTS7, COUNTS) lives in data/feature_structure.py,
generated by data/gen_features_1m.py — this module only holds the status
rules. It is stdlib-only, and no function here ever raises on bad input:
resolve() returns an error dict, search() / list_category() return [] and
counts() returns zero counts when the input or the structure is unusable.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

TOTAL = 23_720_000
VOL1_TOTAL = 1_000_000
VOL2_START = 1_000_001
VOL3_START = 3_000_001
VOL4_START = 4_000_001
VOL5_START = 4_700_001
VOL6_START = 6_700_001
VOL7_START = 13_700_001
CATEGORIES_COUNT = 100
VOL1_TARGETS_PER_CATEGORY = 500
VOL2_TARGETS_PER_CATEGORY = 1000
VOL3_TARGETS_PER_CATEGORY = 500
VOL4_TARGETS_PER_CATEGORY = 350
VOL5_TARGETS_PER_CATEGORY = 1000
VOL6_TARGETS_PER_CATEGORY = 3500
VOL7_TARGETS_PER_CATEGORY = 5010
PATTERNS_PER_TARGET = 20
VOL1_FEATURES_PER_CATEGORY = 10_000
VOL2_FEATURES_PER_CATEGORY = 20_000
VOL3_FEATURES_PER_CATEGORY = 10_000
VOL4_FEATURES_PER_CATEGORY = 7_000
VOL5_FEATURES_PER_CATEGORY = 20_000
VOL6_FEATURES_PER_CATEGORY = 70_000
VOL7_FEATURES_PER_CATEGORY = 100_200
FEATURES_PER_CATEGORY = 237_200  # per category across all seven volumes
STATUSES = ("WORKING", "NEEDS-KEY", "NEEDS-DEVICE", "PLANNED")

# Core patterns: true for every working target — any tool is
# voice-invokable, shows its result on the HUD/dashboard, and is usable
# as a quick action.
CORE_PATTERNS = frozenset({
    "Voice control for {t}", "Live dashboard for {t}", "Quick actions for {t}",
})

# ---- Ported Phase 1 tables (from data/gen_features.py) ----
# WORKING_MAP: (category_index 1-based, target) -> owning tool,
# default run args, extra patterns beyond CORE_PATTERNS, evidence note.
_WORKING_MAP = {(1, 'Bengali-English-Hindi mix'): {'tool': None, 'args': {}, 'extra': [], 'note': 'Core Gemini Live voice session speaks Bengali/English/Hindi.'}, (1, 'boss-style talking'): {'tool': 'set_mood', 'args': {'mood': 'boss'}, 'extra': [], 'note': 'Boss-style mood in set_mood; mirror_boss_style setting exists.'}, (1, 'conversation context'): {'tool': None, 'args': {}, 'extra': ['Search & history for {t}'], 'note': 'Live session keeps conversation context (session_memory).'}, (1, 'human-like voice reply'): {'tool': None, 'args': {}, 'extra': [], 'note': 'Core Gemini Live voice — natural tone, not a robot voice.'}, (1, 'long-term memory'): {'tool': 'recall_memory', 'args': {}, 'extra': ['Auto backup for {t}', 'Search & history for {t}'], 'note': 'save_memory/recall_memory inline tools; memory/ persists facts.'}, (1, 'mood engine'): {'tool': 'set_mood', 'args': {'mood': 'friendly'}, 'extra': [], 'note': 'set_mood plugin: friendly/playful/caring/serious/boss (5 moods).'}, (1, 'multi-provider AI'): {'tool': 'provider_status', 'args': {}, 'extra': ['Auto {t}'], 'note': 'provider_status: Gemini default + OpenRouter, automatic fallback.'}, (2, 'YouTube search'): {'tool': 'youtube_search', 'args': {}, 'extra': ['Search & history for {t}'], 'note': 'youtube_search inline tool + YouTube connector search.'}, (2, 'auto form fill'): {'tool': 'browser_control', 'args': {}, 'extra': ['Auto {t}'], 'note': 'browser_control fills forms; Mark never sees website passwords.'}, (2, 'browser file upload'): {'tool': 'browser_control', 'args': {}, 'extra': ['Auto {t}'], 'note': 'Browser upload delivered 2026-11-17 (signup+upload).'}, (2, 'page screenshot'): {'tool': 'browser_control', 'args': {}, 'extra': ['One-click share for {t}'], 'note': 'Extension captures page screenshots; screen_process also exists.'}, (2, 'precise click engine'): {'tool': 'browser_control', 'args': {}, 'extra': ['Auto {t}'], 'note': 'MV3 Chrome extension + browser_control tool; exact-match clicks.'}, (2, 'sign-in automation'): {'tool': 'browser_control', 'args': {}, 'extra': ['Auto {t}'], 'note': 'browser_control signs in with saved login; passwords never exposed.'}, (2, 'sign-up automation'): {'tool': 'browser_control', 'args': {}, 'extra': ['Auto {t}'], 'note': 'Browser signup delivered 2026-11-17 (one-click Render, signup+upload).'}, (3, 'PC power control'): {'tool': 'pc_power', 'args': {}, 'extra': ['Remote control for {t}'], 'note': 'pc_power tool: shutdown/restart/sleep/screen off, confirm-first.'}, (3, 'app launcher'): {'tool': 'open_app', 'args': {}, 'extra': ['Remote control for {t}'], 'note': 'open_app action opens any app by name; app_install via winget.'}, (3, 'clipboard control'): {'tool': 'computer_control', 'args': {}, 'extra': ['Multi-device sync for {t}', 'Remote control for {t}'], 'note': 'computer_control clipboard get/paste; phone<->PC clipboard sync.'}, (3, 'keyboard typing'): {'tool': 'computer_control', 'args': {}, 'extra': ['Remote control for {t}'], 'note': 'computer_control types into any app.'}, (3, 'mouse control'): {'tool': 'computer_control', 'args': {}, 'extra': ['Remote control for {t}'], 'note': 'computer_control moves/clicks/scrolls the cursor.'}, (3, 'screen on/off'): {'tool': 'pc_power', 'args': {}, 'extra': ['Remote control for {t}'], 'note': 'pc_power screen off; screen_on cannot power on a fully-off PC.'}, (3, 'system info dashboard'): {'tool': 'system_status', 'args': {}, 'extra': ['Remote control for {t}'], 'note': 'system_status inline tool: CPU/RAM/disk/battery live.'}, (3, 'volume & brightness'): {'tool': 'computer_settings', 'args': {}, 'extra': ['Remote control for {t}'], 'note': 'computer_settings volume controls; brightness via system settings.'}, (3, 'window manager'): {'tool': 'desktop_control', 'args': {}, 'extra': ['Remote control for {t}'], 'note': 'desktop_control manages windows (resize/arrange/monitors).'}, (4, 'PC screen on phone'): {'tool': None, 'args': {}, 'extra': ['Multi-device sync for {t}', 'Remote control for {t}'], 'note': 'capture_pc_screen in core/jarvis_link; phone sees the PC screen.'}, (4, 'QR pairing'): {'tool': 'jarvis_link_qr', 'args': {}, 'extra': [], 'note': 'QR pairing verified live 2026-11-16 (mark-3fe31ec4, E2E ON).'}, (4, 'any-device remote'): {'tool': None, 'args': {}, 'extra': ['Multi-device sync for {t}', 'Remote control for {t}'], 'note': 'Remote-control QR: any browser controls phone+PC, any internet.'}, (4, 'connected devices panel'): {'tool': None, 'args': {}, 'extra': [], 'note': 'Dashboard remote page shows connected devices + online status.'}, (4, 'file transfer'): {'tool': 'phone_send_file', 'args': {}, 'extra': ['Multi-device sync for {t}', 'One-click share for {t}', 'Remote control for {t}'], 'note': 'phone_send_file: PC -> phone, 2 MB max, delivered.'}, (4, 'find my phone'): {'tool': 'phone_location', 'args': {}, 'extra': ['Alerts & reminders for {t}', 'Remote control for {t}'], 'note': 'phone_location: ring + GPS location from the PC.'}, (4, 'phone app open'): {'tool': 'phone_open_app', 'args': {}, 'extra': ['Remote control for {t}'], 'note': 'phone_open_app opens any phone app by display name.'}, (4, 'phone screen view'): {'tool': 'phone_screen', 'args': {}, 'extra': ['One-click share for {t}', 'Remote control for {t}'], 'note': 'phone_screen tool: still screenshots, auto refresh; needs Accessibility.'}, (4, 'phone touch control'): {'tool': 'phone_command', 'args': {}, 'extra': ['Remote control for {t}'], 'note': 'phone_command drives the phone via Accessibility (tap/swipe/type).'}, (4, 'two-way voice'): {'tool': 'phone_say', 'args': {}, 'extra': ['Multi-device sync for {t}', 'Remote control for {t}'], 'note': "phone_say: Mark's spoken replies reach the phone as WAV (verified)."}, (6, 'smart file search'): {'tool': 'file_controller', 'args': {}, 'extra': ['Search & history for {t}'], 'note': 'file_controller searches the PC by name/type.'}, (7, 'error recovery'): {'tool': None, 'args': {}, 'extra': ['Auto {t}'], 'note': 'Automation retries a failed step once; auto backup + recovery.'}, (7, 'live office panel'): {'tool': 'agents_status', 'args': {}, 'extra': [], 'note': "Live office panel: each agent's status, time, % done."}, (7, 'main agent'): {'tool': None, 'args': {}, 'extra': [], 'note': 'Mark itself is the main agent; every request goes through it.'}, (7, 'morning briefing'): {'tool': 'automation', 'args': {'action': 'template', 'template': 'morning_briefing'}, 'extra': ['AI summary for {t}', 'Alerts & reminders for {t}', 'Smart scheduler for {t}'], 'note': 'morning_briefing template; daily 07:50 IST briefing scheduled.'}, (7, 'parallel task run'): {'tool': 'background_tasks', 'args': {}, 'extra': ['Bulk actions for {t}'], 'note': 'background_tasks runs several jobs at once under worker agents.'}, (7, 'reminder system'): {'tool': 'reminder', 'args': {}, 'extra': ['Alerts & reminders for {t}', 'Smart scheduler for {t}'], 'note': 'reminder action: voice + notification reminders.'}, (7, 'scheduled tasks'): {'tool': 'automation', 'args': {'action': 'list'}, 'extra': ['Alerts & reminders for {t}', 'Smart scheduler for {t}'], 'note': 'automation engine: time/interval/keyword/event triggers.'}, (7, 'task queue'): {'tool': 'background_tasks', 'args': {}, 'extra': ['Bulk actions for {t}'], 'note': 'background_tasks / action queue: jobs run in order.'}, (7, 'worker agents'): {'tool': 'agents_status', 'args': {}, 'extra': ['Bulk actions for {t}'], 'note': 'agents_status: 20 agents (7 workers in the 200-list era, now 20).'}, (8, 'EXE builder'): {'tool': 'build_exe', 'args': {}, 'extra': [], 'note': 'build_exe inline tool (7z SFX installer route, verified).'}, (8, 'bug fixer'): {'tool': 'dev_agent', 'args': {}, 'extra': ['Auto {t}'], 'note': 'dev_agent self-fix/self-improve: reads AGENTS.md, fixes code.'}, (8, 'code runner'): {'tool': 'code_helper', 'args': {}, 'extra': ['Auto {t}'], 'note': 'code_helper runs written code and shows the result.'}, (8, 'code writer'): {'tool': 'code_helper', 'args': {}, 'extra': ['Auto {t}'], 'note': 'code_helper writes code in any language.'}, (8, 'website builder'): {'tool': 'dev_agent', 'args': {}, 'extra': ['Auto {t}'], 'note': 'dev_agent builds websites (dashboard, render hosting).'}, (9, 'E2E encryption'): {'tool': None, 'args': {}, 'extra': [], 'note': 'E2E relay encryption verified live (QR secret, AES-256-GCM).'}, (9, 'activity history'): {'tool': None, 'args': {}, 'extra': [], 'note': 'Backend v2: activity / permissions / history in the dashboard.'}, (9, 'admin ban'): {'tool': None, 'args': {}, 'extra': [], 'note': 'Backend v2: one-click ban user/device from the admin dashboard.'}, (9, 'confirm-first'): {'tool': None, 'args': {}, 'extra': [], 'note': 'core/confirm.py: danger actions (shutdown/delete/payment) ask first.'}, (9, 'key vault'): {'tool': None, 'args': {}, 'extra': ['Privacy lock for {t}'], 'note': 'Keys live only in config/api_keys.json via config_manager.'}, (9, 'monitoring switch'): {'tool': None, 'args': {}, 'extra': [], 'note': 'Owner monitoring switch delivered, OFF by default.'}, (9, 'password guard'): {'tool': None, 'args': {}, 'extra': ['Privacy lock for {t}'], 'note': 'No password storage: browser_control never saves or shows passwords.'}, (9, 'remote feature toggle'): {'tool': None, 'args': {}, 'extra': [], 'note': 'Backend v2: remote feature add/on-off without an app update.'}, (10, 'game player'): {'tool': 'play_game', 'args': {}, 'extra': [], 'note': 'play_game plugin: launches the saved PC/phone game.'}, (10, 'news briefing'): {'tool': 'web_search', 'args': {'query': 'top news today'}, 'extra': ['AI summary for {t}', 'Alerts & reminders for {t}', 'Smart scheduler for {t}'], 'note': "web_search fetches the day's big news; in the morning briefing."}, (10, 'video player'): {'tool': 'video_player', 'args': {}, 'extra': [], 'note': 'video_player action plays video in the HUD.'}, (10, 'weather live'): {'tool': 'weather_report', 'args': {}, 'extra': ['AI summary for {t}', 'Alerts & reminders for {t}', 'Smart scheduler for {t}'], 'note': 'weather_report action; weather is in the daily morning briefing.'}}

# NEEDS_KEY_TARGETS: (category_index, target) -> [owning tool or None,
# what account/key is needed].
_NEEDS_KEY_TARGETS = {(5, 'Facebook posts'): ['facebook_post', 'Facebook Page token'], (5, 'Facebook video'): ['facebook_upload_video', 'Facebook Page token'], (5, 'Instagram Reels'): ['instagram_upload_video', 'Instagram account / API token'], (5, 'Instagram auto-reply'): ['autoreply', 'Instagram account / webhook'], (5, 'Instagram posts'): ['instagram_upload_video', 'Instagram account / API token'], (5, 'WhatsApp auto-reply'): ['autoreply', 'WhatsApp Business number / API'], (5, 'YouTube Shorts'): ['youtube_upload', 'YouTube API key / OAuth'], (5, 'YouTube upload'): ['youtube_upload', 'YouTube API key / OAuth'], (5, 'comment manager'): [None, 'Social account (YouTube / Instagram / Facebook)'], (5, 'cross-posting'): [None, 'Social accounts for each platform'], (6, 'Drive auto-upload'): ['drive_upload', 'Google account / OAuth'], (6, 'Drive connect'): ['drive_list', 'Google account / OAuth'], (6, 'Supabase backup'): [None, 'Supabase project keys'], (6, 'whole storage sync'): [None, 'Supabase project keys'], (8, 'APK builder'): ['build_apk', 'GitHub account + Actions (build_apk needs GitHub Actions)'], (8, 'GitHub push'): ['github_push_file', 'GitHub personal access token'], (8, 'Render deploy'): ['render_deploy', 'Render API key'], (8, 'deploy status'): ['render_status', 'Render API key'], (8, 'iOS packaging'): [None, 'GitHub Actions + Apple developer account'], (10, 'calendar helper'): [None, 'Google Calendar OAuth'], (14, 'live radio'): [None, 'Radio streaming service'], (14, 'lyrics display'): [None, 'Lyrics API key'], (14, 'playlist maker'): [None, 'Spotify / music service account'], (14, 'podcast player'): [None, 'Podcast service account'], (14, 'song identifier'): [None, 'Music recognition API key'], (17, 'cloud saves'): [None, 'Game cloud account'], (19, 'UPI history'): [None, 'Bank / UPI account'], (19, 'crypto prices'): [None, 'Crypto market API key'], (19, 'stock tracker'): [None, 'Stock market API key'], (20, 'coupon finder'): [None, 'Store account / coupon API'], (20, 'deal alerts'): [None, 'Store account / shopping API'], (20, 'order tracker'): [None, 'Store account'], (20, 'price history'): [None, 'Shopping API key'], (20, 'price tracker'): [None, 'Store account / shopping API'], (20, 'return helper'): [None, 'Store account'], (20, 'store compare'): [None, 'Shopping API key'], (20, 'wishlist'): [None, 'Store account'], (21, 'hotel finder'): [None, 'Hotel booking API / account'], (22, 'order tracker'): [None, 'Food-delivery account'], (35, 'download queue'): [None, 'Streaming service account'], (35, 'streaming search'): [None, 'Streaming service account'], (35, 'watch party'): [None, 'Streaming service account'], (36, 'audiobook player'): [None, 'Audiobook service account'], (36, 'ebook library'): [None, 'Ebook store account'], (50, 'e-signature'): [None, 'E-signature service account'], (51, 'listing search'): [None, 'Property listing API'], (51, 'price alerts'): [None, 'Property listing API'], (51, 'valuation'): [None, 'Property valuation API'], (52, 'job alerts'): [None, 'Job-board API / account'], (52, 'salary checker'): [None, 'Job-board / salary API'], (53, 'invoice sender'): [None, 'Payment account'], (53, 'payment reminders'): [None, 'Payment account'], (54, 'event finder'): [None, 'Ticketing / events API'], (54, 'ticket booking'): [None, 'Ticketing account (e.g. Ticketmaster)'], (55, 'donation tracker'): [None, 'Donation platform account'], (55, 'fundraiser page'): [None, 'Donation platform account'], (63, 'download queue'): [None, 'Podcast service account'], (63, 'episode finder'): [None, 'Podcast service account'], (63, 'recommendation engine'): [None, 'Podcast service account'], (63, 'share clips'): [None, 'Podcast service account'], (63, 'subscription manager'): [None, 'Podcast service account'], (68, 'ETA alerts'): [None, 'Carrier API / account'], (68, 'parcel tracker'): [None, 'Carrier API / account'], (86, 'VPN toggle'): [None, 'VPN service account'], (93, 'cloud restore'): [None, 'Cloud backup account'], (99, 'remote login'): [None, 'Remote PC credentials']}

# Whole categories that are account/API-gated (every target NEEDS-KEY).
_NEEDS_KEY_CATEGORIES = [12, 13, 31, 34, 41, 42, 43, 44, 47, 48, 49, 64, 65, 66, 69, 70, 71]

# NEEDS_DEVICE_TARGETS: (category_index, target) -> hardware needed.
_NEEDS_DEVICE_TARGETS = {(15, 'print helper'): 'Printer', (17, 'controller support'): 'Game controller', (18, 'emergency SOS'): 'Phone hardware (SOS needs the phone itself)', (18, 'heart-rate monitor'): 'Phone sensors / wearable', (18, 'sleep tracker'): 'Phone sensors / wearable', (18, 'step tracker'): 'Phone sensors / wearable', (62, 'RAW capture'): 'Camera hardware', (62, 'focus peaking'): 'Camera hardware', (62, 'interval timer'): 'Camera hardware', (62, 'light meter'): 'Camera hardware', (62, 'location tags'): 'Camera hardware', (62, 'manual controls'): 'Camera hardware', (67, 'barcode scanner'): 'Camera (phone camera)', (98, 'audio sync'): 'TV / Chromecast receiver', (98, 'cast to TV'): 'TV / Chromecast receiver', (98, 'device finder'): 'Cast-capable display on the network', (98, 'game cast'): 'TV / Chromecast receiver', (98, 'mirror to PC'): 'Cast receiver on the target display', (98, 'photo cast'): 'TV / Chromecast receiver', (98, 'presentation cast'): 'TV / Chromecast receiver', (98, 'quality switch'): 'TV / Chromecast receiver'}

# Whole categories that are hardware-gated (every target NEEDS-DEVICE).
_NEEDS_DEVICE_CATEGORIES = [25, 26, 27, 28, 29, 30, 87, 88, 89]


# ------------------------------------------------------------------ structure
_STRUCTURE_PATH = Path(__file__).resolve().parent.parent / "data" / "feature_structure.py"
_STRUCTURE = None  # cached module (or False when the file cannot be loaded)


def _structure():
    """data/feature_structure.py, loaded lazily (importing this module must
    never fail just because the generated structure is absent — the
    generator itself imports this module to compute the counts)."""
    global _STRUCTURE
    if _STRUCTURE is not None:
        return _STRUCTURE or None
    try:
        spec = importlib.util.spec_from_file_location(
            "mark_feature_structure", _STRUCTURE_PATH)
        if spec is None or spec.loader is None:
            raise ImportError("could not build import spec")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if not (hasattr(module, "CATEGORIES") and hasattr(module, "PATTERNS")
                and hasattr(module, "CONTEXTS")
                and hasattr(module, "CONTEXTS2")
                and hasattr(module, "CONTEXTS3")
                and hasattr(module, "CONTEXTS4")
                and hasattr(module, "CONTEXTS5")
                and hasattr(module, "CONTEXTS6")
                and hasattr(module, "CONTEXTS7")):
            raise ImportError("feature_structure.py is missing a list")
        _STRUCTURE = module
    except Exception:
        _STRUCTURE = False
    return _STRUCTURE or None


def _categories():
    st = _structure()
    return st.CATEGORIES if st is not None else None


# ------------------------------------------------------------------ status
def _status(category_index, target, pattern_tpl):
    """Resolve one feature's status. Returns (status, tool, args, requires).
    Port of data/gen_features.py::_status — same tables, same order:
    WORKING -> NEEDS-KEY -> NEEDS-DEVICE -> PLANNED (first match wins)."""
    try:
        key = (category_index, target)
        w = _WORKING_MAP.get(key)
        if w is not None and pattern_tpl in (CORE_PATTERNS | set(w["extra"])):
            return "WORKING", w["tool"], dict(w["args"]), ""
        if key in _NEEDS_KEY_TARGETS:
            tool, req = _NEEDS_KEY_TARGETS[key]
            return "NEEDS-KEY", tool, {}, req
        if category_index in _NEEDS_KEY_CATEGORIES:
            return "NEEDS-KEY", None, {}, "Account / API key for this service"
        if key in _NEEDS_DEVICE_TARGETS:
            return "NEEDS-DEVICE", None, {}, _NEEDS_DEVICE_TARGETS[key]
        if category_index in _NEEDS_DEVICE_CATEGORIES:
            return "NEEDS-DEVICE", None, {}, "Matching hardware device"
    except Exception:
        pass
    return "PLANNED", None, {}, "Not built yet"


def _decompose(number):
    """number (1..23720000) -> (volume, category_idx_0, target_idx, pattern_idx).
    Volume 1: number = c*10000 + t*20 + p + 1 (t 0..499).
    Volume 2: e = number - 1000001; c = e // 20000; t = (e % 20000) // 20;
    p = e % 20 (t 0..999).
    Volume 3: e = number - 3000001; c = e // 10000; t = (e % 10000) // 20;
    p = e % 20 (t 0..499).
    Volume 4: e = number - 4000001; c = e // 7000; t = (e % 7000) // 20;
    p = e % 20 (t 0..349).
    Volume 5: e = number - 4700001; c = e // 20000; t = (e % 20000) // 20;
    p = e % 20 (t 0..999).
    Volume 6: e = number - 6700001; c = e // 70000; t = (e % 70000) // 20;
    p = e % 20 (t 0..3499).
    Volume 7: e = number - 13700001; c = e // 100200;
    t = (e % 100200) // 20; p = e % 20 (t 0..5009: 0..4999 contextual,
    5000..5009 plain)."""
    if number <= VOL1_TOTAL:
        n = number - 1
        return 1, n // VOL1_FEATURES_PER_CATEGORY, \
            (n % VOL1_FEATURES_PER_CATEGORY) // PATTERNS_PER_TARGET, \
            n % PATTERNS_PER_TARGET
    if number < VOL3_START:
        e = number - VOL2_START
        return 2, e // VOL2_FEATURES_PER_CATEGORY, \
            (e % VOL2_FEATURES_PER_CATEGORY) // PATTERNS_PER_TARGET, \
            e % PATTERNS_PER_TARGET
    if number < VOL4_START:
        e = number - VOL3_START
        return 3, e // VOL3_FEATURES_PER_CATEGORY, \
            (e % VOL3_FEATURES_PER_CATEGORY) // PATTERNS_PER_TARGET, \
            e % PATTERNS_PER_TARGET
    if number < VOL5_START:
        e = number - VOL4_START
        return 4, e // VOL4_FEATURES_PER_CATEGORY, \
            (e % VOL4_FEATURES_PER_CATEGORY) // PATTERNS_PER_TARGET, \
            e % PATTERNS_PER_TARGET
    if number < VOL6_START:
        e = number - VOL5_START
        return 5, e // VOL5_FEATURES_PER_CATEGORY, \
            (e % VOL5_FEATURES_PER_CATEGORY) // PATTERNS_PER_TARGET, \
            e % PATTERNS_PER_TARGET
    if number < VOL7_START:
        e = number - VOL6_START
        return 6, e // VOL6_FEATURES_PER_CATEGORY, \
            (e % VOL6_FEATURES_PER_CATEGORY) // PATTERNS_PER_TARGET, \
            e % PATTERNS_PER_TARGET
    e = number - VOL7_START
    return 7, e // VOL7_FEATURES_PER_CATEGORY, \
        (e % VOL7_FEATURES_PER_CATEGORY) // PATTERNS_PER_TARGET, \
        e % PATTERNS_PER_TARGET


def _target_parts(cat_targets, contexts, contexts2, contexts3, contexts4,
                  contexts5, contexts6, contexts7, volume, target_idx):
    """target_idx -> (target string, base target, context or None).
    Volume 1 (0..499): first 10 are plain; t >= 10 ->
        base = cat_targets[(t-10)//49], ctx = CONTEXTS[(t-10)%49].
    Volume 2 (0..999): all contextual ->
        base = cat_targets[t//100], ctx = CONTEXTS2[t%100].
    Volume 3 (0..499): all contextual ->
        base = cat_targets[t//50], ctx = CONTEXTS3[t%50].
    Volume 4 (0..349): all contextual ->
        base = cat_targets[t//35], ctx = CONTEXTS4[t%35].
    Volume 5 (0..999): all contextual ->
        base = cat_targets[t//100], ctx = CONTEXTS5[t%100].
    Volume 6 (0..3499): all contextual ->
        base = cat_targets[t//350], ctx = CONTEXTS6[t%350].
    Volume 7 (0..5009): contextual FIRST, plain LAST ->
        t < 5000: base = cat_targets[t//500], ctx = CONTEXTS7[t%500];
        t >= 5000: plain target cat_targets[t-5000], no context."""
    if volume == 7:
        if target_idx < 5000:
            base = cat_targets[target_idx // len(contexts7)]
            ctx = contexts7[target_idx % len(contexts7)]
            return f"{base} for {ctx}", base, ctx
        target = cat_targets[target_idx - 5000]
        return target, target, None
    if volume == 6:
        base = cat_targets[target_idx // len(contexts6)]
        ctx = contexts6[target_idx % len(contexts6)]
        return f"{base} for {ctx}", base, ctx
    if volume == 5:
        base = cat_targets[target_idx // len(contexts5)]
        ctx = contexts5[target_idx % len(contexts5)]
        return f"{base} for {ctx}", base, ctx
    if volume == 4:
        base = cat_targets[target_idx // len(contexts4)]
        ctx = contexts4[target_idx % len(contexts4)]
        return f"{base} for {ctx}", base, ctx
    if volume == 3:
        base = cat_targets[target_idx // len(contexts3)]
        ctx = contexts3[target_idx % len(contexts3)]
        return f"{base} for {ctx}", base, ctx
    if volume == 2:
        base = cat_targets[target_idx // len(contexts2)]
        ctx = contexts2[target_idx % len(contexts2)]
        return f"{base} for {ctx}", base, ctx
    if target_idx < 10:
        target = cat_targets[target_idx]
        return target, target, None
    j = target_idx - 10
    base = cat_targets[j // len(contexts)]
    ctx = contexts[j % len(contexts)]
    return f"{base} for {ctx}", base, ctx


def _record(number, volume, category_idx_0, target_idx, pattern_idx):
    """Build the record dict for one (already validated) number."""
    st = _structure()
    cat, cat_targets = st.CATEGORIES[category_idx_0]
    name_tpl, desc_tpl = st.PATTERNS[pattern_idx]
    target, base_target, context = _target_parts(
        cat_targets, st.CONTEXTS, st.CONTEXTS2, st.CONTEXTS3, st.CONTEXTS4,
        st.CONTEXTS5, st.CONTEXTS6, st.CONTEXTS7, volume, target_idx)
    status, tool, args, requires = _status(
        category_idx_0 + 1, base_target, name_tpl)
    return {
        "number": number,
        "volume": volume,
        "category": cat,
        "category_index": category_idx_0 + 1,
        "target": target,
        "target_index": target_idx,
        "base_target": base_target,
        "context": context,
        "pattern": name_tpl,
        "pattern_index": pattern_idx,
        "name": name_tpl.format(t=target),
        "description": desc_tpl.format(t=target),
        "status": status,
        "tool": tool,
        "args": args,
        "requires": requires,
        "enabled": is_enabled(number),
    }


def _parse_number(value):
    """int 1..TOTAL, or None. Accepts ints and digit strings; never raises."""
    try:
        if isinstance(value, bool):
            return None
        n = int(str(value).strip()) if isinstance(value, str) else int(value)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= TOTAL else None


# ------------------------------------------------------------------ public API
def resolve(number):
    """One feature by number -> record dict. Never raises; on bad input
    (or a missing structure file) returns {"error": ..., "number": ...}."""
    n = _parse_number(number)
    if n is None:
        return {"error": f"Feature number must be 1-{TOTAL}.", "number": number}
    try:
        if _structure() is None:
            return {"error": "Feature registry structure is not built yet "
                             "(data/feature_structure.py missing).",
                    "number": n}
        volume, c, t, p = _decompose(n)
        return _record(n, volume, c, t, p)
    except Exception as exc:
        return {"error": f"Could not resolve feature #{n}: {exc}", "number": n}


def list_categories():
    """[{index (1-based), name, start, end, vol2_start, vol2_end,
    vol3_start, vol3_end, vol4_start, vol4_end, vol5_start, vol5_end,
    vol6_start, vol6_end, vol7_start, vol7_end}] for all 100 categories,
    or [] when the structure is missing. `start`/`end` is the Volume 1
    range (10,000 features); `vol2_start`/`vol2_end` is the Volume 2 range
    (20,000 features); `vol3_start`/`vol3_end` is the Volume 3 range
    (10,000 features); `vol4_start`/`vol4_end` is the Volume 4 range
    (7,000 features); `vol5_start`/`vol5_end` is the Volume 5 range
    (20,000 features); `vol6_start`/`vol6_end` is the Volume 6 range
    (70,000 features); `vol7_start`/`vol7_end` is the Volume 7 range
    (100,200 features). Never raises."""
    try:
        cats = _categories()
        if cats is None:
            return []
        return [{"index": i + 1, "name": cat,
                 "start": i * VOL1_FEATURES_PER_CATEGORY + 1,
                 "end": (i + 1) * VOL1_FEATURES_PER_CATEGORY,
                 "vol2_start": VOL2_START + i * VOL2_FEATURES_PER_CATEGORY,
                 "vol2_end": VOL2_START + (i + 1) * VOL2_FEATURES_PER_CATEGORY - 1,
                 "vol3_start": VOL3_START + i * VOL3_FEATURES_PER_CATEGORY,
                 "vol3_end": VOL3_START + (i + 1) * VOL3_FEATURES_PER_CATEGORY - 1,
                 "vol4_start": VOL4_START + i * VOL4_FEATURES_PER_CATEGORY,
                 "vol4_end": VOL4_START + (i + 1) * VOL4_FEATURES_PER_CATEGORY - 1,
                 "vol5_start": VOL5_START + i * VOL5_FEATURES_PER_CATEGORY,
                 "vol5_end": VOL5_START + (i + 1) * VOL5_FEATURES_PER_CATEGORY - 1,
                 "vol6_start": VOL6_START + i * VOL6_FEATURES_PER_CATEGORY,
                 "vol6_end": VOL6_START + (i + 1) * VOL6_FEATURES_PER_CATEGORY - 1,
                 "vol7_start": VOL7_START + i * VOL7_FEATURES_PER_CATEGORY,
                 "vol7_end": VOL7_START + (i + 1) * VOL7_FEATURES_PER_CATEGORY - 1}
                for i, (cat, _t) in enumerate(cats)]
    except Exception:
        return []


def list_category(cidx, offset=0, limit=20):
    """Records for one category (cidx 1-based), computed directly from
    the numbers — no stored list. offset/limit page within the category's
    combined 237,200 features: offsets 0..9999 are Volume 1, offsets
    10000..29999 are Volume 2, offsets 30000..39999 are Volume 3,
    offsets 40000..46999 are Volume 4, offsets 47000..66999 are
    Volume 5, offsets 67000..136999 are Volume 6, offsets
    137000..237199 are Volume 7. Never raises;
    [] on bad input."""
    try:
        cidx = int(cidx)
        offset = int(offset)
        limit = int(limit)
    except (TypeError, ValueError):
        return []
    if not 1 <= cidx <= CATEGORIES_COUNT or offset < 0 or limit < 1:
        return []
    limit = min(limit, 1000)
    try:
        if _structure() is None:
            return []
        out = []
        v1 = VOL1_FEATURES_PER_CATEGORY
        v2 = VOL2_FEATURES_PER_CATEGORY
        v3 = VOL3_FEATURES_PER_CATEGORY
        v4 = VOL4_FEATURES_PER_CATEGORY
        v5 = VOL5_FEATURES_PER_CATEGORY
        v6 = VOL6_FEATURES_PER_CATEGORY
        for i in range(offset, min(offset + limit, FEATURES_PER_CATEGORY)):
            if i < v1:
                n = (cidx - 1) * v1 + i + 1
            elif i < v1 + v2:
                n = VOL2_START + (cidx - 1) * v2 + (i - v1)
            elif i < v1 + v2 + v3:
                n = VOL3_START + (cidx - 1) * v3 + (i - v1 - v2)
            elif i < v1 + v2 + v3 + v4:
                n = VOL4_START + (cidx - 1) * v4 + (i - v1 - v2 - v3)
            elif i < v1 + v2 + v3 + v4 + v5:
                n = VOL5_START + (cidx - 1) * v5 + (i - v1 - v2 - v3 - v4)
            elif i < v1 + v2 + v3 + v4 + v5 + v6:
                n = VOL6_START + (cidx - 1) * v6 + (i - v1 - v2 - v3 - v4 - v5)
            else:
                n = VOL7_START + (cidx - 1) * VOL7_FEATURES_PER_CATEGORY \
                    + (i - v1 - v2 - v3 - v4 - v5 - v6)
            volume, c, t, p = _decompose(n)
            out.append(_record(n, volume, c, t, p))
        return out
    except Exception:
        return []


def counts():
    """{total, WORKING, NEEDS-KEY, NEEDS-DEVICE, PLANNED} from the baked-in
    COUNTS in data/feature_structure.py (computed by the generator over
    the whole formula space). Never raises."""
    zero = {"total": TOTAL}
    zero.update({s: 0 for s in STATUSES})
    try:
        st = _structure()
        if st is None:
            return zero
        baked = getattr(st, "COUNTS", None)
        if not isinstance(baked, dict):
            return zero
        out = {"total": int(baked.get("total", TOTAL))}
        for s in STATUSES:
            out[s] = int(baked.get(s, 0))
        return out
    except Exception:
        return zero


def category_status_counts(cidx):
    """{status: count} for one category (cidx 1-based), computed from the
    status rule over its 237,200 numbers (10,000 Volume 1 + 20,000 Volume
    2 + 10,000 Volume 3 + 7,000 Volume 4 + 20,000 Volume 5 + 70,000
    Volume 6 + 100,200 Volume 7). Never raises."""
    out = {s: 0 for s in STATUSES}
    try:
        cidx = int(cidx)
        if not 1 <= cidx <= CATEGORIES_COUNT:
            return out
        st = _structure()
        if st is None:
            return out
        _cat, cat_targets = st.CATEGORIES[cidx - 1]
        ctxs = (st.CONTEXTS, st.CONTEXTS2, st.CONTEXTS3,
                st.CONTEXTS4, st.CONTEXTS5, st.CONTEXTS6, st.CONTEXTS7)
        targets_per_vol = (VOL1_TARGETS_PER_CATEGORY,
                           VOL2_TARGETS_PER_CATEGORY,
                           VOL3_TARGETS_PER_CATEGORY,
                           VOL4_TARGETS_PER_CATEGORY,
                           VOL5_TARGETS_PER_CATEGORY,
                           VOL6_TARGETS_PER_CATEGORY,
                           VOL7_TARGETS_PER_CATEGORY)
        for vol in range(1, 8):
            for t in range(targets_per_vol[vol - 1]):
                _target, base, _ctx = _target_parts(
                    cat_targets, ctxs[0], ctxs[1], ctxs[2], ctxs[3],
                    ctxs[4], ctxs[5], ctxs[6], vol, t)
                for name_tpl, _desc in st.PATTERNS:
                    status, _tool, _args, _req = _status(cidx, base, name_tpl)
                    out[status] += 1
        return out
    except Exception:
        return out


# ------------------------------------------------------------------ search
def _tokens(query):
    try:
        return [t for t in re.split(r"[^a-z0-9]+", str(query or "").lower()) if t]
    except Exception:
        return []


def _hits(tokens, text):
    """Number of distinct query tokens appearing (substring) in text."""
    low = text.lower()
    return sum(1 for t in tokens if t in low)


def search(query, limit=10):
    """Matching records, best first. Matches query tokens against the
    category names + the 1000 plain/base target strings + the 20 pattern
    templates (+ descriptions) + the 49 Volume 1 contexts + the 100
    Volume 2 contexts + the 50 Volume 3 contexts + the 35 Volume 4
    contexts + the 100 Volume 5 contexts + the 350 Volume 6 contexts +
    the 500 Volume 7 contexts, then expands matches to numbers
    combinatorially — never enumerates all 23.72M entries. Volume 1
    matches come first, then Volume 2, then Volume 3, then Volume 4,
    then Volume 5, then Volume 6, then Volume 7 matches.
    Never raises; [] on bad/empty query.
    `limit` caps the records returned (default 10)."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    if limit < 1:
        return []
    tokens = _tokens(query)
    if not tokens:
        return []
    try:
        st = _structure()
        if st is None:
            return []
        cats = st.CATEGORIES
        pats = st.PATTERNS
        ctxs = st.CONTEXTS
        ctxs2 = st.CONTEXTS2
        ctxs3 = st.CONTEXTS3
        ctxs4 = st.CONTEXTS4
        ctxs5 = st.CONTEXTS5
        ctxs6 = st.CONTEXTS6
        ctxs7 = st.CONTEXTS7
        cat_hit = [_hits(tokens, cat) for cat, _t in cats]
        tgt_hit = [[_hits(tokens, b) for b in targets] for _cat, targets in cats]
        pat_hit = [_hits(tokens, name_tpl + " " + desc_tpl)
                   for name_tpl, desc_tpl in pats]
        ctx_hit = [_hits(tokens, ctx) for ctx in ctxs]
        ctx2_hit = [_hits(tokens, ctx) for ctx in ctxs2]
        ctx3_hit = [_hits(tokens, ctx) for ctx in ctxs3]
        ctx4_hit = [_hits(tokens, ctx) for ctx in ctxs4]
        ctx5_hit = [_hits(tokens, ctx) for ctx in ctxs5]
        ctx6_hit = [_hits(tokens, ctx) for ctx in ctxs6]
        ctx7_hit = [_hits(tokens, ctx) for ctx in ctxs7]
        any_pat = any(pat_hit)
        any_ctx = (any(ctx_hit) or any(ctx2_hit) or any(ctx3_hit)
                   or any(ctx4_hit) or any(ctx5_hit) or any(ctx6_hit)
                   or any(ctx7_hit))
        # (pair score, first number, c, b) — best pairs first.
        pairs = []
        for c in range(CATEGORIES_COUNT):
            for b in range(10):
                score = 0
                for t in tokens:
                    if t in cats[c][0].lower() or t in cats[c][1][b].lower():
                        score += 1
                if score or any_pat or any_ctx:
                    pairs.append((-score, c * VOL1_FEATURES_PER_CATEGORY + b * PATTERNS_PER_TARGET + 1, c, b))
        pairs.sort()
        out = []
        for _neg, _first, c, b in pairs:
            pair_score = -_neg
            # Volume 1 instances: plain target first, then its 49 context
            # variants (contexts matching the query first).
            instances = [(b, None)] + [
                (10 + b * len(ctxs) + k, k)
                for k in sorted(range(len(ctxs)), key=lambda k: (-ctx_hit[k], k))]
            for t_idx, k in instances:
                ctx_ok = k is not None and ctx_hit[k] > 0
                if not (pair_score or ctx_ok or any_pat):
                    continue
                # Patterns: matching ones first when the pair/context does
                # not already match; otherwise all, best first.
                if pair_score or ctx_ok:
                    pat_order = sorted(range(len(pats)),
                                       key=lambda p: (-pat_hit[p], p))
                else:
                    pat_order = [p for p in sorted(
                        range(len(pats)), key=lambda p: (-pat_hit[p], p))
                        if pat_hit[p]]
                for p in pat_order:
                    out.append(_record(
                        c * VOL1_FEATURES_PER_CATEGORY + t_idx * PATTERNS_PER_TARGET + p + 1,
                        1, c, t_idx, p))
                    if len(out) >= limit:
                        return out
            # Volume 2 instances: 100 contextual variants, no plain
            # target (contexts matching the query first).
            instances2 = [
                (b * len(ctxs2) + k, k)
                for k in sorted(range(len(ctxs2)), key=lambda k: (-ctx2_hit[k], k))]
            for t_idx, k in instances2:
                ctx_ok = ctx2_hit[k] > 0
                if not (pair_score or ctx_ok or any_pat):
                    continue
                if pair_score or ctx_ok:
                    pat_order = sorted(range(len(pats)),
                                       key=lambda p: (-pat_hit[p], p))
                else:
                    pat_order = [p for p in sorted(
                        range(len(pats)), key=lambda p: (-pat_hit[p], p))
                        if pat_hit[p]]
                for p in pat_order:
                    out.append(_record(
                        VOL2_START + c * VOL2_FEATURES_PER_CATEGORY + t_idx * PATTERNS_PER_TARGET + p + 1,
                        2, c, t_idx, p))
                    if len(out) >= limit:
                        return out
            # Volume 3 instances: 50 contextual variants, no plain
            # target (contexts matching the query first).
            instances3 = [
                (b * len(ctxs3) + k, k)
                for k in sorted(range(len(ctxs3)), key=lambda k: (-ctx3_hit[k], k))]
            for t_idx, k in instances3:
                ctx_ok = ctx3_hit[k] > 0
                if not (pair_score or ctx_ok or any_pat):
                    continue
                if pair_score or ctx_ok:
                    pat_order = sorted(range(len(pats)),
                                       key=lambda p: (-pat_hit[p], p))
                else:
                    pat_order = [p for p in sorted(
                        range(len(pats)), key=lambda p: (-pat_hit[p], p))
                        if pat_hit[p]]
                for p in pat_order:
                    out.append(_record(
                        VOL3_START + c * VOL3_FEATURES_PER_CATEGORY + t_idx * PATTERNS_PER_TARGET + p + 1,
                        3, c, t_idx, p))
                    if len(out) >= limit:
                        return out
            # Volume 4 instances: 35 contextual variants, no plain
            # target (contexts matching the query first).
            instances4 = [
                (b * len(ctxs4) + k, k)
                for k in sorted(range(len(ctxs4)), key=lambda k: (-ctx4_hit[k], k))]
            for t_idx, k in instances4:
                ctx_ok = ctx4_hit[k] > 0
                if not (pair_score or ctx_ok or any_pat):
                    continue
                if pair_score or ctx_ok:
                    pat_order = sorted(range(len(pats)),
                                       key=lambda p: (-pat_hit[p], p))
                else:
                    pat_order = [p for p in sorted(
                        range(len(pats)), key=lambda p: (-pat_hit[p], p))
                        if pat_hit[p]]
                for p in pat_order:
                    out.append(_record(
                        VOL4_START + c * VOL4_FEATURES_PER_CATEGORY + t_idx * PATTERNS_PER_TARGET + p + 1,
                        4, c, t_idx, p))
                    if len(out) >= limit:
                        return out
            # Volume 5 instances: 100 contextual variants, no plain
            # target (contexts matching the query first).
            instances5 = [
                (b * len(ctxs5) + k, k)
                for k in sorted(range(len(ctxs5)), key=lambda k: (-ctx5_hit[k], k))]
            for t_idx, k in instances5:
                ctx_ok = ctx5_hit[k] > 0
                if not (pair_score or ctx_ok or any_pat):
                    continue
                if pair_score or ctx_ok:
                    pat_order = sorted(range(len(pats)),
                                       key=lambda p: (-pat_hit[p], p))
                else:
                    pat_order = [p for p in sorted(
                        range(len(pats)), key=lambda p: (-pat_hit[p], p))
                        if pat_hit[p]]
                for p in pat_order:
                    out.append(_record(
                        VOL5_START + c * VOL5_FEATURES_PER_CATEGORY + t_idx * PATTERNS_PER_TARGET + p + 1,
                        5, c, t_idx, p))
                    if len(out) >= limit:
                        return out
            # Volume 6 instances: 350 contextual variants, no plain
            # target (contexts matching the query first).
            instances6 = [
                (b * len(ctxs6) + k, k)
                for k in sorted(range(len(ctxs6)), key=lambda k: (-ctx6_hit[k], k))]
            for t_idx, k in instances6:
                ctx_ok = ctx6_hit[k] > 0
                if not (pair_score or ctx_ok or any_pat):
                    continue
                if pair_score or ctx_ok:
                    pat_order = sorted(range(len(pats)),
                                       key=lambda p: (-pat_hit[p], p))
                else:
                    pat_order = [p for p in sorted(
                        range(len(pats)), key=lambda p: (-pat_hit[p], p))
                        if pat_hit[p]]
                for p in pat_order:
                    out.append(_record(
                        VOL6_START + c * VOL6_FEATURES_PER_CATEGORY + t_idx * PATTERNS_PER_TARGET + p + 1,
                        6, c, t_idx, p))
                    if len(out) >= limit:
                        return out
            # Volume 7 instances: 500 contextual variants first, then
            # the plain target last (contexts matching the query first).
            instances7 = [
                (b * len(ctxs7) + k, k)
                for k in sorted(range(len(ctxs7)), key=lambda k: (-ctx7_hit[k], k))]
            instances7.append((5000 + b, None))
            for t_idx, k in instances7:
                ctx_ok = k is not None and ctx7_hit[k] > 0
                if not (pair_score or ctx_ok or any_pat):
                    continue
                if pair_score or ctx_ok:
                    pat_order = sorted(range(len(pats)),
                                       key=lambda p: (-pat_hit[p], p))
                else:
                    pat_order = [p for p in sorted(
                        range(len(pats)), key=lambda p: (-pat_hit[p], p))
                        if pat_hit[p]]
                for p in pat_order:
                    out.append(_record(
                        VOL7_START + c * VOL7_FEATURES_PER_CATEGORY + t_idx * PATTERNS_PER_TARGET + p + 1,
                        7, c, t_idx, p))
                    if len(out) >= limit:
                        return out
        return out
    except Exception:
        return []


def search_total(query):
    """How many features search(query) would match in total, computed
    combinatorially over the axes (no enumeration). Never raises."""
    tokens = _tokens(query)
    if not tokens:
        return 0
    try:
        st = _structure()
        if st is None:
            return 0
        cats = st.CATEGORIES
        pats = st.PATTERNS
        ctxs = st.CONTEXTS
        ctxs2 = st.CONTEXTS2
        ctxs3 = st.CONTEXTS3
        ctxs4 = st.CONTEXTS4
        ctxs5 = st.CONTEXTS5
        ctxs6 = st.CONTEXTS6
        ctxs7 = st.CONTEXTS7
        pat_hit = [_hits(tokens, name_tpl + " " + desc_tpl)
                   for name_tpl, desc_tpl in pats]
        n_pat_hits = sum(1 for h in pat_hit if h)
        ctx_hit = [_hits(tokens, ctx) for ctx in ctxs]
        ctx2_hit = [_hits(tokens, ctx) for ctx in ctxs2]
        ctx3_hit = [_hits(tokens, ctx) for ctx in ctxs3]
        ctx4_hit = [_hits(tokens, ctx) for ctx in ctxs4]
        ctx5_hit = [_hits(tokens, ctx) for ctx in ctxs5]
        ctx6_hit = [_hits(tokens, ctx) for ctx in ctxs6]
        ctx7_hit = [_hits(tokens, ctx) for ctx in ctxs7]
        total = 0
        for c in range(CATEGORIES_COUNT):
            cat_low = cats[c][0].lower()
            for b in range(10):
                pair_score = 0
                for t in tokens:
                    if t in cat_low or t in cats[c][1][b].lower():
                        pair_score += 1
                if pair_score:
                    # Volume 1: 50 instances (plain + 49 contexts) x 20
                    # patterns; Volume 2: 100 instances x 20 patterns;
                    # Volume 3: 50 instances x 20 patterns; Volume 4:
                    # 35 instances x 20 patterns; Volume 5: 100
                    # instances x 20 patterns; Volume 6: 350 instances
                    # x 20 patterns; Volume 7: 5,010 instances
                    # (5,000 contextual + 10 plain) x 20 patterns.
                    total += (50 * 20 + 100 * 20 + 50 * 20 + 35 * 20
                              + 100 * 20 + 350 * 20 + 5010 * 20)
                    continue
                # Volume 1, no pair hit: plain instance matches only on
                # pattern hits; a context instance matches on its context
                # hit (all 20 patterns) or on pattern hits.
                total += n_pat_hits
                for k in range(len(ctxs)):
                    total += 20 if ctx_hit[k] else n_pat_hits
                # Volume 2, no pair hit: no plain instance; a context
                # instance matches on its context hit (all 20 patterns)
                # or on pattern hits.
                for k in range(len(ctxs2)):
                    total += 20 if ctx2_hit[k] else n_pat_hits
                # Volume 3, no pair hit: same as Volume 2 (50 contexts).
                for k in range(len(ctxs3)):
                    total += 20 if ctx3_hit[k] else n_pat_hits
                # Volume 4, no pair hit: same as Volume 2 (35 contexts).
                for k in range(len(ctxs4)):
                    total += 20 if ctx4_hit[k] else n_pat_hits
                # Volume 5, no pair hit: same as Volume 2 (100 contexts).
                for k in range(len(ctxs5)):
                    total += 20 if ctx5_hit[k] else n_pat_hits
                # Volume 6, no pair hit: same as Volume 2 (350 contexts).
                for k in range(len(ctxs6)):
                    total += 20 if ctx6_hit[k] else n_pat_hits
                # Volume 7, no pair hit: plain instances match only on
                # pattern hits (10 of them); a context instance matches
                # on its context hit (all 20 patterns) or on pattern
                # hits (500 contexts).
                total += 10 * n_pat_hits
                for k in range(len(ctxs7)):
                    total += 20 if ctx7_hit[k] else n_pat_hits
        return total
    except Exception:
        return 0


# ------------------------------------------------------------------ enable/disable
_NAMESPACE = "features"
_DISABLED_KEY = "disabled"
_disabled_cache = None  # cached set[int] of disabled feature numbers


def _disabled_numbers():
    """Disabled numbers, cached per process (set_enabled refreshes it).
    Never raises; [] when nothing is stored or config is unreadable."""
    global _disabled_cache
    if _disabled_cache is not None:
        return _disabled_cache
    numbers = set()
    try:
        from memory.config_manager import get_plugin_config
        raw = (get_plugin_config(_NAMESPACE) or {}).get(_DISABLED_KEY) or []
        for v in raw:
            n = _parse_number(v)
            if n is not None:
                numbers.add(n)
    except Exception:
        numbers = set()
    _disabled_cache = numbers
    return numbers


def is_enabled(number):
    """True unless the feature was disabled with set_enabled. Never raises;
    an invalid number counts as not enabled."""
    n = _parse_number(number)
    if n is None:
        return False
    try:
        return n not in _disabled_numbers()
    except Exception:
        return True


def set_enabled(number, on):
    """Enable/disable one feature. Disabled numbers persist in
    memory/config_manager.py under the "features" namespace
    (plugin_config["features"]["disabled"] = [numbers...]) so they
    survive restarts. Returns True on success, False on bad input or
    a persistence failure. Never raises."""
    n = _parse_number(number)
    if n is None:
        return False
    try:
        numbers = set(_disabled_numbers())
        if on:
            numbers.discard(n)
        else:
            numbers.add(n)
        from memory.config_manager import save_plugin_config
        save_plugin_config(_NAMESPACE, {_DISABLED_KEY: sorted(numbers)})
        global _disabled_cache
        _disabled_cache = numbers
        return True
    except Exception:
        return False
