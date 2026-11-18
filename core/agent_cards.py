"""core/agent_cards.py — 🤖 AGENT CARDS: ONE Main Agent + 86 workers.

The user asked for 20-30 agent cards on the master screen / Plugin
Settings: one MAIN agent (the orchestrator who talks to the user and
delegates) plus a worker card per job — video upload, APK build, Render
deploy, browser control, Firebase connect, hosting auto-fix, WhatsApp,
live screen, mouse, video editing, GitHub, file transfer, phone, location,
memory, mood, music, screenshot, battery, voice notes, calculator,
translator, weather, news, Python Run, Software Builder, Photo Editor,
Data Analyzer, Report Writer, Email Sender, File Organizer — and 50
utility workers (Timer, Stopwatch, Pomodoro, World Clock, Sleep Timer,
Focus Mode, Unit/Currency Converter, Code Formatter, JSON Viewer, Regex
Tester, File Search, Zip, Storage Analyzer, Disk Cleanup, Download
Manager, Image Resizer, Clipboard, System Info, Process/Startup Manager,
Network Speed, WiFi, Bluetooth, VPN, Battery Monitor, Screen Recorder,
QR/Password Generator, Meme/Subtitle/Invoice/Resume, Notes, Habits,
Expenses, Bookmarks, Contacts, Calendar, Flashcards, Quiz, Poll,
Dictionary, Audio Converter, Video Downloader, YouTube, SMS, Call Log,
Step Counter, Password Vault).

Every card maps to a REAL tool (its "tool" value is a real tool/plugin/
action name in this codebase — tests/test_agent_cards_update.py re-derives
the inventory and fails the build if a card points at nothing). A card's
Run does its REAL job when it can, or says plainly on the card what is
missing (a token, a pairing, a file) instead of pretending.

This module never imports Qt and never touches a widget. Card actions run
on worker threads and return short strings; the HUD (PluginSettingsOverlay
agent-cards box, MainAgentOverlay) reads cards() on the Qt thread and runs
run_card() on a worker thread, reporting back through a pyqtSignal.
All imports of plugins/actions happen lazily inside the action functions
so importing this module can never create a cycle.
"""
from __future__ import annotations

# ── the 88 cards ─────────────────────────────────────────────────────────────
# id: stable, lowercase — used in config, the dashboard JSON and the UI.
# tool: the REAL tool/plugin/action name that does this card's job.
# action: the key in _ACTIONS below. needs: what the card needs to run
# (shown on the card when it is missing).

CARD_DEFS = [
    {
        "id": "main", "name": "Main Agent", "icon": "🧠",
        "job": "Orchestrator — shune, bujhe, worker-ke kaj pathay.",
        "tool": "agents_status", "action": "main_status", "needs": "",
    },
    {
        "id": "video_upload", "name": "Video Upload", "icon": "🎬",
        "job": "YouTube / Instagram / Facebook-e video tola.",
        "tool": "youtube_upload", "action": "video_upload_status",
        "needs": "YouTube OAuth token (upload-er jonno)",
    },
    {
        "id": "apk_build", "name": "APK Build", "icon": "🔧",
        "job": "GitHub Actions-e APK build + self-heal (auto-fix).",
        "tool": "apk_build_selfheal", "action": "apk_build_status",
        "needs": "GitHub token + repo + workflow file",
    },
    {
        "id": "render_deploy", "name": "Render Deploy", "icon": "🚀",
        "job": "Render API diye dashboard deploy + status + env var.",
        "tool": "render_deploy", "action": "render_deploy_run",
        "needs": "Render API key",
    },
    {
        "id": "browser_control", "name": "Browser Control", "icon": "🌐",
        "job": "Mouse diye Chrome khola + page chalano (no browser helper).",
        "tool": "browser_control", "action": "browser_open",
        "needs": "Chrome + Playwright/CDP driver",
    },
    {
        "id": "firebase_connect", "name": "Firebase Connect", "icon": "🔥",
        "job": "Firebase project app/website-er sathe connect kora.",
        "tool": "firebase_connect", "action": "firebase_run",
        "needs": "Chrome-e Google login",
    },
    {
        "id": "hosting_autofix", "name": "Hosting Auto-Fix", "icon": "🛠️",
        "job": "Render deploy fail hole nijei thik kore redeploy.",
        "tool": "hosting_autofix", "action": "hosting_autofix_run",
        "needs": "Render API key",
    },
    {
        "id": "whatsapp", "name": "WhatsApp", "icon": "💬",
        "job": "WhatsApp Business-e message + auto-reply.",
        "tool": "whatsapp_send", "action": "whatsapp_status",
        "needs": "WhatsApp Business token + phone number id",
    },
    {
        "id": "live_screen", "name": "Live Screen", "icon": "📱",
        "job": "Phone-er live screen master screen-e dekha.",
        "tool": "live_screen", "action": "live_screen_status",
        "needs": "Phone pair (Jarvis Link) + v1.9.7 stream",
    },
    {
        "id": "mouse_control", "name": "Mouse Control", "icon": "🖱️",
        "job": "Mouse move/click/type — manusher moto.",
        "tool": "mouse_control", "action": "mouse_demo",
        "needs": "pyautogui",
    },
    {
        "id": "video_edit", "name": "Video Editing", "icon": "✂️",
        "job": "ffmpeg diye trim/cut/merge/text/thumbnail.",
        "tool": "video_edit", "action": "video_edit_status",
        "needs": "ffmpeg (prothom use-e auto-download)",
    },
    {
        "id": "github_repo", "name": "GitHub Repo Create", "icon": "📦",
        "job": "GitHub-e repo banao — token ba browser, duita path.",
        "tool": "github_create_repo", "action": "github_status",
        "needs": "GitHub token (API path-er jonno)",
    },
    {
        "id": "file_transfer", "name": "File Transfer", "icon": "📁",
        "job": "Phone <-> PC file pathano (2 MB porjonto).",
        "tool": "phone_send_file", "action": "link_status",
        "needs": "Phone pair (Jarvis Link)",
    },
    {
        "id": "phone_control", "name": "Phone Control", "icon": "📲",
        "job": "Phone-er app khola, command chalano, kotha bolano.",
        "tool": "phone_command", "action": "link_status",
        "needs": "Phone pair (Jarvis Link)",
    },
    {
        "id": "location_map", "name": "Location Map", "icon": "📍",
        "job": "Phone kothay — GPS location + map link.",
        "tool": "phone_location", "action": "location_status",
        "needs": "Phone GPS + Location permission",
    },
    {
        "id": "memory", "name": "Memory", "icon": "🧠",
        "job": "Mone rakha — fact save, recall, kokhono delete noy.",
        "tool": "recall_memory", "action": "memory_status",
        "needs": "",
    },
    {
        "id": "mood", "name": "Mood", "icon": "🎭",
        "job": "Mood & feelings — tone bodlano.",
        "tool": "set_mood", "action": "mood_status",
        "needs": "",
    },
    {
        "id": "music", "name": "Music", "icon": "🎵",
        "job": "YouTube-e gaan khujo + chalao.",
        "tool": "youtube_search", "action": "music_search",
        "needs": "YouTube API key",
    },
    {
        "id": "screenshot", "name": "Screenshot", "icon": "📸",
        "job": "PC screen-er screenshot neoa.",
        "tool": "screen_process", "action": "pc_screenshot",
        "needs": "",
    },
    {
        "id": "battery_device", "name": "Battery / Device", "icon": "🔋",
        "job": "CPU, RAM, battery, uptime — PC-r haal.",
        "tool": "system_status", "action": "device_status",
        "needs": "",
    },
    {
        "id": "voice_notes", "name": "Voice Notes", "icon": "🎙️",
        "job": "Dictation note — bole likhe rakho, pore shono.",
        "tool": "voice_tools", "action": "voice_notes_status",
        "needs": "",
    },
    {
        "id": "calculator", "name": "Calculator", "icon": "🔢",
        "job": "Calculator khola.",
        "tool": "open_app", "action": "open_calculator",
        "needs": "",
    },
    {
        "id": "translator", "name": "Translator", "icon": "🌐",
        "job": "English <-> Bengali <-> Hindi translate.",
        "tool": "voice_tools", "action": "translate_sample",
        "needs": "Gemini key",
    },
    {
        "id": "weather", "name": "Weather", "icon": "🌤️",
        "job": "Aajker weather — shohor-er.",
        "tool": "weather_report", "action": "weather_now",
        "needs": "",
    },
    {
        "id": "news", "name": "News", "icon": "📰",
        "job": "Latest news — khobor.",
        "tool": "web_search", "action": "news_now",
        "needs": "",
    },
    {
        "id": "python_run", "name": "Python Run", "icon": "🐍",
        "job": "Python code chalao — snippet ba project folder.",
        "tool": "python_run", "action": "python_run_status",
        "needs": "",
    },
    {
        "id": "software_builder", "name": "Software Builder", "icon": "🛠️",
        "job": "Boro software banao — localhost-e chalao, deploy koro.",
        "tool": "software_builder", "action": "software_builder_status",
        "needs": "",
    },
    {
        "id": "photo_editor", "name": "Photo Editor", "icon": "🖼️",
        "job": "Photo edit + 6-copy A4 sheet (360x420 px, 300 DPI).",
        "tool": "photo_editor", "action": "photo_editor_status",
        "needs": "",
    },
    {
        "id": "data_analyzer", "name": "Data Analyzer", "icon": "📊",
        "job": "CSV/Excel file-er summary — row, column, avg/min/max.",
        "tool": "data_analyzer", "action": "data_analyzer_status",
        "needs": "CSV ba Excel file",
    },
    {
        "id": "report_writer", "name": "Report Writer", "icon": "📝",
        "job": "Asol report file likhe — topic + aajker haal.",
        "tool": "report_writer", "action": "report_writer_status",
        "needs": "",
    },
    {
        "id": "email_sender", "name": "Email Sender", "icon": "✉️",
        "job": "SMTP diye asol email pathano.",
        "tool": "email_sender", "action": "email_sender_status",
        "needs": "SMTP settings (host/user/app password)",
    },
    {
        "id": "file_organizer", "name": "File Organizer", "icon": "🗂️",
        "job": "Folder sajano — dry-run preview age, tarpor sotti soray.",
        "tool": "file_organizer", "action": "file_organizer_status",
        "needs": "",
    },
    # ── 50 NEW utility cards (agents round) ──────────────────────────────
    # Each maps to a REAL plugin tool (utility_* / youtube_play) and its
    # action calls a REAL core/utility_tools (or youtube_agent) function.
    # No placeholder cards: a card whose job needs input says so plainly
    # on Run instead of faking it.
    {
        "id": "timer", "name": "Timer", "icon": "⏱️",
        "job": "Countdown timer — minute diye chalao.",
        "tool": "utility_time", "action": "timer_status", "needs": "",
    },
    {
        "id": "stopwatch", "name": "Stopwatch", "icon": "⏱️",
        "job": "Stopwatch — start / stop / lap.",
        "tool": "utility_time", "action": "stopwatch_status", "needs": "",
    },
    {
        "id": "pomodoro", "name": "Pomodoro", "icon": "🍅",
        "job": "25 min kaj + 5 min break cycle.",
        "tool": "utility_time", "action": "pomodoro_status", "needs": "",
    },
    {
        "id": "world_clock", "name": "World Clock", "icon": "🌍",
        "job": "Duniar shohorer somoy ek sathe.",
        "tool": "utility_time", "action": "world_clock_status", "needs": "",
    },
    {
        "id": "sleep_timer", "name": "Sleep Timer", "icon": "😴",
        "job": "Nirdisto somoy pore PC ghumabe.",
        "tool": "utility_time", "action": "sleep_timer_status", "needs": "",
    },
    {
        "id": "focus_mode", "name": "Focus Mode", "icon": "🎯",
        "job": "Notification bondho + focus timer.",
        "tool": "utility_time", "action": "focus_mode_status", "needs": "",
    },
    {
        "id": "unit_converter", "name": "Unit Converter", "icon": "🔁",
        "job": "Length / weight / volume / temperature convert.",
        "tool": "utility_convert", "action": "unit_convert_sample",
        "needs": "",
    },
    {
        "id": "currency_converter", "name": "Currency Converter",
        "icon": "💱",
        "job": "Live rate-e currency convert (free API).",
        "tool": "utility_convert", "action": "currency_convert_sample",
        "needs": "Internet (live rate-er jonno)",
    },
    {
        "id": "code_formatter", "name": "Code Formatter", "icon": "🧹",
        "job": "Python / JSON code format kora.",
        "tool": "utility_convert", "action": "code_format_sample",
        "needs": "",
    },
    {
        "id": "json_viewer", "name": "JSON Viewer", "icon": "📋",
        "job": "JSON check + sundor kore dekhano.",
        "tool": "utility_convert", "action": "json_view_sample", "needs": "",
    },
    {
        "id": "regex_tester", "name": "Regex Tester", "icon": "🔍",
        "job": "Regex pattern test kora — match gulo dekhay.",
        "tool": "utility_convert", "action": "regex_test_sample",
        "needs": "",
    },
    {
        "id": "file_search", "name": "File Search", "icon": "🔍",
        "job": "Naam diye file khujo PC-te.",
        "tool": "utility_files", "action": "file_search_sample", "needs": "",
    },
    {
        "id": "zip_tool", "name": "Zip Tool", "icon": "📦",
        "job": "Zip banao / zip kholo.",
        "tool": "utility_files", "action": "zip_tool_status", "needs": "",
    },
    {
        "id": "storage_analyzer", "name": "Storage Analyzer", "icon": "💽",
        "job": "Disk use + boro folder gulo dekhay.",
        "tool": "utility_files", "action": "storage_analyzer_run",
        "needs": "",
    },
    {
        "id": "disk_cleanup", "name": "Disk Cleanup", "icon": "🧹",
        "job": "Purono temp file — preview age, Recycle Bin-e pathay.",
        "tool": "utility_files", "action": "disk_cleanup_preview",
        "needs": "",
    },
    {
        "id": "download_manager", "name": "Download Manager", "icon": "⬇️",
        "job": "URL theke file download (100 MB cap).",
        "tool": "utility_files", "action": "download_manager_status",
        "needs": "Internet",
    },
    {
        "id": "image_resizer", "name": "Image Resizer", "icon": "🖼️",
        "job": "Image resize kora (PIL).",
        "tool": "utility_files", "action": "image_resizer_status",
        "needs": "",
    },
    {
        "id": "clipboard", "name": "Clipboard", "icon": "📋",
        "job": "PC clipboard dekha / bosano.",
        "tool": "utility_files", "action": "clipboard_get", "needs": "",
    },
    {
        "id": "system_info", "name": "System Info", "icon": "🖥️",
        "job": "OS / CPU / RAM / disk / battery.",
        "tool": "utility_system", "action": "system_info_run", "needs": "",
    },
    {
        "id": "process_manager", "name": "Process Manager", "icon": "⚙️",
        "job": "Top process gulo + PID diye bondho kora.",
        "tool": "utility_system", "action": "process_list_run", "needs": "",
    },
    {
        "id": "startup_manager", "name": "Startup Manager", "icon": "🚀",
        "job": "Windows-er sathe ki ki chalu hoy — list.",
        "tool": "utility_system", "action": "startup_list_run", "needs": "",
    },
    {
        "id": "network_speed", "name": "Network Speed Test", "icon": "📶",
        "job": "Download speed mapa (1 MB probe).",
        "tool": "utility_system", "action": "network_speed_run",
        "needs": "Internet",
    },
    {
        "id": "wifi_networks", "name": "WiFi Networks", "icon": "📶",
        "job": "Kacher WiFi network-er list.",
        "tool": "utility_system", "action": "wifi_networks_run", "needs": "",
    },
    {
        "id": "bluetooth_devices", "name": "Bluetooth Devices", "icon": "🔵",
        "job": "Bluetooth device-er list.",
        "tool": "utility_system", "action": "bluetooth_devices_run",
        "needs": "",
    },
    {
        "id": "vpn_status", "name": "VPN Status", "icon": "🔒",
        "job": "VPN adapter connect ache kina.",
        "tool": "utility_system", "action": "vpn_status_run", "needs": "",
    },
    {
        "id": "battery_monitor", "name": "Battery Monitor", "icon": "🔋",
        "job": "PC + phone battery ek sathe.",
        "tool": "utility_system", "action": "battery_monitor_run",
        "needs": "",
    },
    {
        "id": "screen_recorder", "name": "Screen Recorder", "icon": "🎥",
        "job": "PC screen record (ffmpeg) — start/stop.",
        "tool": "utility_system", "action": "screen_recorder_status",
        "needs": "ffmpeg",
    },
    {
        "id": "qr_generator", "name": "QR Generator", "icon": "🔳",
        "job": "Text/URL-er QR code PNG banano.",
        "tool": "utility_create", "action": "qr_generator_sample",
        "needs": "",
    },
    {
        "id": "password_generator", "name": "Password Generator",
        "icon": "🔑",
        "job": "Strong random password banano.",
        "tool": "utility_create", "action": "password_generator_run",
        "needs": "",
    },
    {
        "id": "meme_maker", "name": "Meme Maker", "icon": "😂",
        "job": "Image-te upore-niche text diye meme.",
        "tool": "utility_create", "action": "meme_maker_status", "needs": "",
    },
    {
        "id": "subtitle_maker", "name": "Subtitle Maker", "icon": "💬",
        "job": "Text theke .srt subtitle file.",
        "tool": "utility_create", "action": "subtitle_maker_status",
        "needs": "",
    },
    {
        "id": "invoice_maker", "name": "Invoice Maker", "icon": "🧾",
        "job": "Excel invoice banano.",
        "tool": "utility_create", "action": "invoice_maker_status",
        "needs": "",
    },
    {
        "id": "resume_builder", "name": "Resume Builder", "icon": "📄",
        "job": "DOCX resume banano.",
        "tool": "utility_create", "action": "resume_builder_status",
        "needs": "",
    },
    {
        "id": "notes", "name": "Notes", "icon": "📝",
        "job": "Choto note likhe rakha + dekhano.",
        "tool": "utility_life", "action": "notes_list", "needs": "",
    },
    {
        "id": "habit_tracker", "name": "Habit Tracker", "icon": "✅",
        "job": "Protidin-er habit + streak.",
        "tool": "utility_life", "action": "habit_status_run", "needs": "",
    },
    {
        "id": "expense_tracker", "name": "Expense Tracker", "icon": "💰",
        "job": "Kharcha likhe rakha + masher hisab.",
        "tool": "utility_life", "action": "expense_summary_run", "needs": "",
    },
    {
        "id": "bookmark_manager", "name": "Bookmark Manager", "icon": "🔖",
        "job": "URL bookmark save + list.",
        "tool": "utility_life", "action": "bookmark_list_run", "needs": "",
    },
    {
        "id": "contacts", "name": "Contacts", "icon": "👤",
        "job": "Contact save + khujo.",
        "tool": "utility_life", "action": "contacts_list", "needs": "",
    },
    {
        "id": "calendar", "name": "Calendar", "icon": "📅",
        "job": "Aajker + agami event-er list.",
        "tool": "utility_life", "action": "calendar_today_run", "needs": "",
    },
    {
        "id": "flashcard_maker", "name": "Flashcard Maker", "icon": "🃏",
        "job": "Flashcard banao + quiz.",
        "tool": "utility_life", "action": "flashcard_quiz_run", "needs": "",
    },
    {
        "id": "quiz_maker", "name": "Quiz Maker", "icon": "❓",
        "job": "Choto quiz banao (general knowledge).",
        "tool": "utility_life", "action": "quiz_make_run", "needs": "",
    },
    {
        "id": "poll_maker", "name": "Poll Maker", "icon": "📊",
        "job": "Poll banao + vote.",
        "tool": "utility_life", "action": "poll_status_run", "needs": "",
    },
    {
        "id": "dictionary", "name": "Dictionary", "icon": "📖",
        "job": "English shobder mane (free API).",
        "tool": "utility_life", "action": "dictionary_sample",
        "needs": "Internet",
    },
    {
        "id": "audio_converter", "name": "Audio Converter", "icon": "🎵",
        "job": "Audio format bodlano (ffmpeg).",
        "tool": "utility_media", "action": "audio_converter_status",
        "needs": "ffmpeg",
    },
    {
        "id": "video_downloader", "name": "Video Downloader", "icon": "📥",
        "job": "PUBLIC video download (yt-dlp).",
        "tool": "utility_media", "action": "video_downloader_status",
        "needs": "yt-dlp + public video",
    },
    {
        "id": "youtube", "name": "YouTube", "icon": "📺",
        "job": "Search + play Mark-er nijer video screen-e. Like/Comment "
               "korte login/token lagbe — fake kokhono na.",
        "tool": "youtube_play", "action": "youtube_play_run",
        "needs": "YouTube API key (search) / OAuth token (like/comment)",
    },
    {
        "id": "sms_sender", "name": "SMS Sender", "icon": "📱",
        "job": "Phone diye SMS pathano (relay).",
        "tool": "utility_phone", "action": "sms_sender_status",
        "needs": "Phone pair kora",
    },
    {
        "id": "call_log", "name": "Call Log", "icon": "📞",
        "job": "Phone-er shesh call-er log (relay).",
        "tool": "utility_phone", "action": "call_log_run",
        "needs": "Phone pair kora",
    },
    {
        "id": "step_counter", "name": "Step Counter", "icon": "👣",
        "job": "Aaj koto step — phone theke (relay).",
        "tool": "utility_phone", "action": "step_counter_run",
        "needs": "Phone pair kora",
    },
    {
        "id": "password_vault", "name": "Password Vault", "icon": "🔐",
        "job": "Password encrypted kore save (AES-256-GCM).",
        "tool": "utility_vault", "action": "vault_status", "needs": "",
    },
    {
        "id": "video_upload_browser", "name": "Video Upload (Browser)",
        "icon": "📤",
        "job": "Instagram/Facebook/YouTube-e browser diye video upload.",
        "tool": "video_upload_browser",
        "action": "video_upload_browser_status",
        "needs": "Instagram/Facebook/YouTube login (Chrome-e)",
    },
    {
        "id": "social_auto", "name": "Social Auto", "icon": "💬",
        "job": "Instagram/Facebook like/comment/message/auto-reply "
               "(permission-first).",
        "tool": "social_auto", "action": "social_auto_status",
        "needs": "Instagram/Facebook login (Chrome-e); sob toggle default OFF",
    },
    {
        "id": "mouse_video_edit", "name": "Mouse Video Editor", "icon": "✂️",
        "job": "CapCut/Premiere-e mouse diye video edit (manusher moto).",
        "tool": "mouse_video_edit", "action": "mouse_video_edit_status",
        "needs": "CapCut/Premiere/Clipchamp install (na thakle ffmpeg)",
    },
    {
        "id": "app_editor", "name": "App Editor", "icon": "🖥️",
        "job": "Jekono desktop app khule mouse diye chalano.",
        "tool": "app_editor", "action": "app_editor_status",
        "needs": "App-ta PC-te install thakte hobe",
    },
    {
        "id": "advanced_browser", "name": "Advanced Browser Control",
        "icon": "🌐",
        "job": "Chrome-e manusher moto: kholo/click/type/fill/scroll/play/"
               "upload/tab — prottek step verify kore.",
        "tool": "advanced_browser", "action": "advanced_browser_status",
        "needs": "Chrome + Playwright/CDP driver",
    },
    {
        "id": "browser_setup", "name": "Browser Setup", "icon": "🧪",
        "job": "Playwright full process: Python check → pip install → "
               "browser download → sample code run.",
        "tool": "browser_setup", "action": "browser_setup_status",
        "needs": "System Python (Mark-er bundled Python na)",
    },
    {
        "id": "hosting_deploy", "name": "Hosting / Deploy", "icon": "🚀",
        "job": "Render Web Service + Static Site deploy, GitHub repo "
               "create — tomar logged-in Chrome-e, AUTO ba MANUAL mode.",
        "tool": "hosting_deploy", "action": "hosting_deploy_status",
        "needs": "Render/GitHub login (tomar Chrome-e)",
    },
]

_BY_ID = {c["id"]: c for c in CARD_DEFS}


# ── registry reads ───────────────────────────────────────────────────────────

def count() -> int:
    return len(CARD_DEFS)


def card_def(card_id: str) -> dict | None:
    return _BY_ID.get(str(card_id or "").strip())


def _ready(card: dict) -> tuple[bool, str]:
    """(ready, missing-text) — cheap config checks only, never network,
    never a driver launch. Never raises."""
    try:
        cid = card["id"]
        if cid in ("render_deploy", "hosting_autofix"):
            try:
                from core import connectors as _conn
                if not _conn.get_token("render_api_key"):
                    return False, "Render API key set kora nei"
            except Exception:
                return False, "Render API key check korte parlam na"
        if cid == "video_upload":
            try:
                from core import connectors as _conn
                if not (_conn.get_token("youtube_access_token")
                        or _conn.get_token("drive_access_token")):
                    return False, "YouTube/Drive OAuth token set kora nei"
            except Exception:
                pass
        if cid == "apk_build":
            try:
                from core import connectors as _conn
                if not _conn.get_token("github_token"):
                    return False, "GitHub token set kora nei"
            except Exception:
                pass
        if cid == "github_repo":
            try:
                from core import connectors as _conn
                if not _conn.get_token("github_token"):
                    return False, "GitHub token set kora nei (browser path cholbe)"
            except Exception:
                pass
        if cid == "whatsapp":
            try:
                from core import connectors as _conn
                if not (_conn.get_token("whatsapp_token")
                        and _conn.get_token("whatsapp_phone_number_id")):
                    return False, "WhatsApp token / number id set kora nei"
            except Exception:
                pass
        if cid == "music":
            try:
                from core import connectors as _conn
                if not _conn.get_token("youtube_api_key"):
                    return False, "YouTube API key set kora nei"
            except Exception:
                pass
        if cid in ("live_screen", "file_transfer", "phone_control",
                   "sms_sender", "call_log", "step_counter"):
            try:
                from core import jarvis_link as _jl
                link = _jl.LINK
                if link is None or not getattr(link, "paired", False):
                    return False, "Phone pair kora nei"
            except Exception:
                return False, "Phone link check korte parlam na"
        if cid == "youtube":
            try:
                from core import connectors as _conn
                if not _conn.get_token("youtube_api_key"):
                    return False, ("YouTube API key set kora nei "
                                   "(search-er jonno; direct URL chalano jabe)")
            except Exception:
                pass
        if cid == "browser_control":
            try:
                from core import browser_driver as _bd
                if not _bd.find_chrome_exe():
                    return False, "Chrome install pelam na ei PC-te"
            except Exception:
                pass
        if cid == "email_sender":
            try:
                from core import email_sender as _em
                ok, _missing = _em.configured()
                if not ok:
                    return False, "SMTP set kora nei"
            except Exception:
                pass
        return True, ""
    except Exception:
        return True, ""


def cards() -> list[dict]:
    """All cards with live readiness. Never raises."""
    out = []
    for c in CARD_DEFS:
        ready, missing = _ready(c)
        d = dict(c)
        d["ready"] = ready
        d["missing"] = missing
        out.append(d)
    return out


# ── actions (each returns a short string, never raises) ──────────────────────

def _main_status() -> str:
    try:
        from core.agents import REGISTRY, describe_agents
        snap = REGISTRY.snapshot()
        working = [a for a in snap if a.get("status") == "working"]
        done = sum(int(a.get("completed_count") or 0) for a in snap)
        lines = ["🧠 Main Agent — 7 worker-er live status:"]
        for a in snap:
            lines.append(f"  {a.get('icon', '')} {a.get('name', '?')}: "
                         f"{a.get('status', 'idle')}")
        lines.append(f"{len(working)} working • {done} done total. "
                     "Bolo ki korbo — ami thik worker-ke pathabo.")
        return "\n".join(lines)
    except Exception as e:
        return f"Agent-der status dekhte parlam na: {e}"


def _video_upload_status() -> str:
    try:
        from core import connectors as _conn
        yt = bool(_conn.get_token("youtube_access_token"))
        drive = bool(_conn.get_token("drive_access_token"))
        ig = bool(_conn.get_token("instagram_access_token"))
        lines = ["🎬 Video Upload — readiness:"]
        lines.append(("✅ YouTube upload ready" if yt else
                      "❌ YouTube upload — OAuth token lagbe "
                      "(youtube_access_token, ~1h)"))
        lines.append(("✅ Drive ready" if drive else
                      "❌ Drive — OAuth token lagbe"))
        lines.append(("✅ Instagram upload ready" if ig else
                      "❌ Instagram upload — Graph token lagbe"))
        lines.append("Upload korte bolo: file path + kothay (YouTube/Instagram/"
                     "Facebook) — ami tole dibo.")
        return "\n".join(lines)
    except Exception as e:
        return f"Video upload-er status dekhte parlam na: {e}"


def _apk_build_status() -> str:
    try:
        from core import connectors as _conn
        tok = bool(_conn.get_token("github_token"))
        if not tok:
            return ("🔧 APK Build — GitHub token set kora nei. Plugin Settings > "
                    "🔗 CONNECTORS-e GitHub token bosao, tarpor repo + workflow "
                    "file dao — ami GitHub Actions-e build dispatch korbo, fail "
                    "hole nijei fix korbo (max 3 bar).")
        return ("🔧 APK Build ready — GitHub token ache. Repo (owner/name) + "
                "workflow file (e.g. build-apk.yml) dao — ami Actions-e build "
                "dispatch korbo, fail hole log pore nijei fix korbo.")
    except Exception as e:
        return f"APK build-er status dekhte parlam na: {e}"


def _render_deploy_run() -> str:
    try:
        from core import render_deploy as _rd
        return _rd.trigger_deploy()
    except Exception as e:
        return f"Render deploy korte parlam na: {e}"


def _browser_open() -> str:
    try:
        from core import browser_control as _bc
        ok, msg = _bc.open_chrome_mouse("https://www.google.com")
        return msg
    except Exception as e:
        return f"Browser khulte parlam na: {e}"


def _firebase_run() -> str:
    try:
        from core import firebase_connect as _fb
        from pathlib import Path as _Path
        folder = str(_Path.home() / "Documents" / "firebase-config")
        ok, msg = _fb.connect_flow(folder)
        return msg
    except Exception as e:
        return f"Firebase connect korte parlam na: {e}"


def _hosting_autofix_run() -> str:
    try:
        from core import hosting_autofix as _hf
        return _hf.autofix()
    except Exception as e:
        return f"Hosting auto-fix korte parlam na: {e}"


def _whatsapp_status() -> str:
    try:
        from core import connectors as _conn
        from core import autoreply as _ar
        tok = bool(_conn.get_token("whatsapp_token"))
        num = bool(_conn.get_token("whatsapp_phone_number_id"))
        cfg = _ar.get_config() if hasattr(_ar, "get_config") else {}
        wa = bool((cfg or {}).get("whatsapp_enabled")) \
            if isinstance(cfg, dict) else False
        lines = ["💬 WhatsApp — status:"]
        lines.append("✅ Token set" if tok else "❌ Business token set kora nei")
        lines.append("✅ Number id set" if num else "❌ Phone number id set kora nei")
        lines.append("✅ Auto-reply ON" if wa else "• Auto-reply OFF "
                     "(dashboard webhooks diye on kora jay)")
        lines.append("Message pathate bolo: kar kache + ki likhbo.")
        return "\n".join(lines)
    except Exception as e:
        return f"WhatsApp-er status dekhte parlam na: {e}"


def _live_screen_status() -> str:
    try:
        from core import live_screen as _ls
        return _ls.live_status()
    except Exception as e:
        return f"Live screen-er status dekhte parlam na: {e}"


def _mouse_demo() -> str:
    try:
        from core import mouse_control as _mc
        w, h = _mc.screen_size()
        if w <= 0:
            return "Mouse control — screen-er size pelam na."
        cx, cy = w // 2, h // 2
        for x, y in ((cx - 60, cy - 60), (cx + 60, cy - 60),
                     (cx + 60, cy + 60), (cx, cy)):
            ok, _m = _mc.move(x, y)
            if not ok:
                return "Mouse move korte parlam na."
        ok, pos = _mc.position()
        return (f"🖱️ Mouse control cholche — screen {w}x{h}, "
                f"choto square-e ghurlam. {pos}")
    except Exception as e:
        return f"Mouse control korte parlam na: {e}"


def _video_edit_status() -> str:
    try:
        from core import video_edit as _ve
        return "✂️ Video Editing — " + str(_ve.ffmpeg_status())
    except Exception as e:
        return f"Video edit-er status dekhte parlam na: {e}"


def _github_status() -> str:
    try:
        from core import connectors as _conn
        return "📦 GitHub — " + str(_conn.github_list_repos())
    except Exception as e:
        return f"GitHub repo list pelam na: {e}"


def _link_status() -> str:
    try:
        from core import jarvis_link as _jl
        link = _jl.LINK
        if link is None:
            return "📱 Jarvis Link load hoy ni — app restart koro."
        d = link.status_dict() if hasattr(link, "status_dict") else {}
        if not d.get("paired"):
            return ("📱 Phone pair kora nei — age jarvis_link_qr diye QR scan "
                    "koro, tarpor file/command jabe.")
        return (f"📱 Phone pair kora ache ({d.get('pc_name', '') or 'phone'}) — "
                f"file pathano, app khola, command — sob cholbe.")
    except Exception as e:
        return f"Phone link-er status dekhte parlam na: {e}"


def _location_status() -> str:
    try:
        from core import phone_location as _pl
        fix = _pl.last_fix()
        if not fix:
            return ("📍 Phone-er location jani na ekhono — 'Find phone' chapo; "
                    "phone GPS + Location permission ON thakte hobe.")
        return (f"📍 Phone: Lat {fix.get('lat')}, Lng {fix.get('lon')} "
                f"({fix.get('at') or ''}) • "
                f"google.com/maps?q={fix.get('lat')},{fix.get('lon')}")
    except Exception as e:
        return f"Location dekhte parlam na: {e}"


def _memory_status() -> str:
    try:
        from memory.memory_manager import load_memory
        mem = load_memory() or {}
        # load_memory() -> {category: {key: {"value": ...}}} — count entries.
        n = sum(len(v) for v in mem.values() if isinstance(v, dict))
        return (f"🧠 Memory — {n} ta fact save ache. Data kokhono delete hoy "
                f"na — daily snapshot + auto-restore on ache.")
    except Exception as e:
        return f"Memory-r status dekhte parlam na: {e}"


def _mood_status() -> str:
    try:
        from core import mood as _mood
        m = _mood.current()
        return (f"🎭 Mood ekhon: {m.get('emoji', '')} {m.get('name', '?')} — "
                f"{m.get('desc', '')}")
    except Exception as e:
        return f"Mood-er status dekhte parlam na: {e}"


def _music_search() -> str:
    try:
        from core import connectors as _conn
        return "🎵 Music — " + str(
            _conn.youtube_search(None, "top music 2026", 3))
    except Exception as e:
        return f"Gaan khujte parlam na: {e}"


def _pc_screenshot() -> str:
    try:
        from core import jarvis_link as _jl
        link = _jl.LINK
        if link is not None:
            try:
                p = link.capture_pc_screen()
                if p:
                    return f"📸 PC screenshot nilam: {p}"
            except Exception:
                pass
        import io
        import mss
        from pathlib import Path as _Path
        from PIL import Image
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        img.thumbnail((1280, 1280))
        p = _Path(__file__).resolve().parent.parent / "memory" / "pc_screen.jpg"
        p.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(p), format="JPEG", quality=80)
        return f"📸 PC screenshot nilam: {p}"
    except Exception as e:
        return f"PC screenshot nite parlam na: {e}"


def _device_status() -> str:
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        try:
            batt = psutil.sensors_battery()
            batt_txt = (f"{int(batt.percent)}% "
                        f"({'charging' if batt.power_plugged else 'on battery'})"
                        if batt else "battery pelam na")
        except Exception:
            batt_txt = "battery pelam na"
        return (f"🔋 Device — CPU {cpu:.0f}% • RAM {mem.percent:.0f}% "
                f"({mem.used // (1024 ** 2)} / {mem.total // (1024 ** 2)} MB) • "
                f"Battery {batt_txt}")
    except Exception as e:
        return f"Device-er status dekhte parlam na: {e}"


def _voice_notes_status() -> str:
    try:
        from plugins import cat01_voice as _vt
        return "🎙️ Voice Notes — " + str(
            _vt.run({"action": "dictate", "mode": "read"}))
    except Exception as e:
        return f"Voice note porte parlam na: {e}"


def _open_calculator() -> str:
    try:
        from actions import open_app as _oa
        return str(_oa.open_app({"app_name": "Calculator"}))
    except Exception as e:
        return f"Calculator khulte parlam na: {e}"


def _translate_sample() -> str:
    try:
        from plugins import cat01_voice as _vt
        return "🌐 Translator — " + str(_vt.run({
            "action": "translate",
            "text": "Good morning, how are you?",
            "target_language": "Bengali"}))
    except Exception as e:
        return f"Translate korte parlam na: {e}"


def _weather_now() -> str:
    try:
        from actions import weather_report as _wr
        city = "Kolkata"
        try:
            from core import phone_location as _pl
            pc = _pl.pc_location() or {}
            if pc.get("city"):
                city = str(pc["city"])
        except Exception:
            pass
        return str(_wr.weather_action({"city": city, "time": "today"}))
    except Exception as e:
        return f"Weather dekhte parlam na: {e}"


def _news_now() -> str:
    try:
        from actions import web_search as _ws
        return "📰 News — " + str(
            _ws.web_search({"query": "latest news", "mode": "news"}))
    except Exception as e:
        return f"News ante parlam na: {e}"


def _python_run_status() -> str:
    try:
        from core import python_run as _pr
        out = _pr.run_snippet_text('print("Mark Python Run ready")')
        return (f"🐍 Python Run — Python {_pr.python_version()} — snippet "
                f"+ project folder, duitoi cholbe.\n{out}")
    except Exception as e:
        return f"Python Run-er status dekhte parlam na: {e}"


def _software_builder_status() -> str:
    try:
        from core import software_builder as _sb
        servers = _sb.list_servers()
        lines = ["🛠️ Software Builder — spec dao, full project baniye "
                 "localhost-e chalabo (fix loop max 3)."]
        if servers:
            for s in servers:
                lines.append(f"  🌐 {s.get('project', '')}: {s.get('url', '')} "
                             f"(port {s.get('port')})")
        else:
            lines.append("  • Ekhono kono localhost server cholche na.")
        return "\n".join(lines)
    except Exception as e:
        return f"Software Builder-er status dekhte parlam na: {e}"


def _photo_editor_status() -> str:
    try:
        from core import photo_editor as _pe
        cw, ch = _pe.size_px()
        return (f"🖼️ Photo Editor — edit + background remove + 6-copy A4 sheet.\n"
                f"  • Default copy: {cw}x{ch} px (1.2x1.4 inch, 300 DPI)\n"
                f"  • Sheet: 2480x3508 px, print-ready PNG (PDF noy)\n"
                f"  • Bolo: 'ei photo-ta 6 copy A4 kore dao'")
    except Exception as e:
        return f"Photo Editor-er status dekhte parlam na: {e}"


def _data_analyzer_status() -> str:
    try:
        return ("📊 Data Analyzer — CSV ba Excel file-er path dao, ami "
                "summary dibo (row, column, avg/min/max, top values). "
                "Excel-er jonno openpyxl lagbe (requirements-e ache).")
    except Exception as e:
        return f"Data Analyzer-er status dekhte parlam na: {e}"


def _report_writer_status() -> str:
    try:
        from core import report_writer as _rw
        res = _rw.write_report("Mark-LVII status")
        if not res.get("ok"):
            return f"📝 Report Writer — {res.get('error', '')}"
        return (f"📝 Report Writer — status report likhe dilam:\n"
                f"  {res['path']}\n"
                f"  • Topic dao (jemon 'Weekly sales summary') — ami report "
                f"likhe dibo.")
    except Exception as e:
        return f"Report Writer-er status dekhte parlam na: {e}"


def _email_sender_status() -> str:
    try:
        from core import email_sender as _em
        return _em.describe()
    except Exception as e:
        return f"Email Sender-er status dekhte parlam na: {e}"


def _file_organizer_status() -> str:
    try:
        from core import file_organizer as _fo
        from pathlib import Path as _Path
        dl = str(_Path.home() / "Downloads")
        return _fo.organize_text(dl, dry_run=True)
    except Exception as e:
        return f"File Organizer-er status dekhte parlam na: {e}"


# ── 50 utility card actions ──────────────────────────────────────────────────
# Zero-arg actions: Run shows the real status / a real sample result, or
# says plainly what input it needs. Nothing here starts a side effect on
# a plain Run (no timer armed, no file written, no message sent).

def _ut(fn_name, *args, **kwargs):
    """Call a core/utility_tools function by name. Never raises."""
    try:
        from core import utility_tools as _u
        return str(getattr(_u, fn_name)(*args, **kwargs))
    except Exception as e:
        return f"Utility chalate parlam na: {e}"


def _ut_action(fn_name, *args, **kwargs):
    """Build a zero-arg card action around a utility function."""
    def _act():
        return _ut(fn_name, *args, **kwargs)
    return _act


from pathlib import Path as _Path

_timer_status = _ut_action("timer_status")
_stopwatch_status = _ut_action("stopwatch", "status")
_pomodoro_status = _ut_action("pomodoro", "status")
_world_clock_status = _ut_action("world_clock")
_sleep_timer_status = _ut_action("sleep_timer_status")
_unit_convert_sample = _ut_action("unit_convert", 1, "km", "mile")
_currency_convert_sample = _ut_action("currency_convert", 1, "USD", "INR")
_code_format_sample = _ut_action("code_format", "x = 1\nprint(x)", "python")
_json_view_sample = _ut_action("json_view", '{"name": "Mark", "version": 1}')
_regex_test_sample = _ut_action("regex_test", r"\d+", "abc 123 def 45")
_file_search_sample = _ut_action("file_search", "MarkLVII",
                                 str(_Path.home() / "Downloads"))
_storage_analyzer_run = _ut_action("storage_analyzer")
_disk_cleanup_preview = _ut_action("disk_cleanup", True)
_clipboard_get = _ut_action("clipboard", "get")
_system_info_run = _ut_action("system_info")
_process_list_run = _ut_action("process_list")
_startup_list_run = _ut_action("startup_list")
_network_speed_run = _ut_action("network_speed_test")
_wifi_networks_run = _ut_action("wifi_networks")
_bluetooth_devices_run = _ut_action("bluetooth_devices")
_vpn_status_run = _ut_action("vpn_status")
_battery_monitor_run = _ut_action("battery_monitor")
_screen_recorder_status = _ut_action("screen_record", "status")
_qr_generator_sample = _ut_action(
    "qr_generate", "https://mark-lvii-dashboard.onrender.com",
    "mark-dashboard")
_password_generator_run = _ut_action("password_generate", 16)
_notes_list = _ut_action("note_list")
_habit_status_run = _ut_action("habit_status")
_expense_summary_run = _ut_action("expense_summary")
_bookmark_list_run = _ut_action("bookmark_list")
_contacts_list = _ut_action("contact_find", "")
_calendar_today_run = _ut_action("calendar_today")
_flashcard_quiz_run = _ut_action("flashcard_quiz")
_quiz_make_run = _ut_action("quiz_make", "", 3)
_poll_status_run = _ut_action("poll_status")
_dictionary_sample = _ut_action("dictionary_lookup", "hello")
_call_log_run = _ut_action("call_log")
_step_counter_run = _ut_action("step_counter")
_vault_status = _ut_action("vault_get", "")


def _focus_mode_status():
    return ("🎯 Focus mode — chalu korte 'focus mode on' bolo (25 min, "
            "notification bondho thakbe). Bondho korte 'focus mode off'.")


def _zip_tool_status():
    return ("📦 Zip Tool — zip banate 'zip banao <folder/file>' bolo, "
            "khulte 'zip kholo <file.zip>' bolo.")


def _download_manager_status():
    return ("⬇️ Download Manager — download korte URL dao: "
            "'download koro <url>'. 100 MB-er beshi file nebo na.")


def _image_resizer_status():
    return ("🖼️ Image Resizer — resize korte 'image resize koro <path> "
            "<width>' bolo (jemon: 800).")


def _meme_maker_status():
    return ("😂 Meme Maker — meme banate image + upore/niche text dao: "
            "'meme banao <image> | <upore> | <niche>'.")


def _subtitle_maker_status():
    return ("💬 Subtitle Maker — subtitle banate text dao (prottek line "
            "ekta caption): 'subtitle banao <text>'. Video-r pashe .srt "
            "likhbo.")


def _invoice_maker_status():
    return ("🧾 Invoice Maker — invoice banate 'invoice banao <client> | "
            "<amount> | <item>' bolo. Excel (.xlsx) file banabo.")


def _resume_builder_status():
    return ("📄 Resume Builder — resume banate 'resume banao <naam> | "
            "<role> | <skill1, skill2>' bolo. DOCX file banabo.")


def _audio_converter_status():
    return ("🎵 Audio Converter — convert korte 'audio convert koro "
            "<file> <mp3/wav/ogg>' bolo. ffmpeg lagbe.")


def _video_downloader_status():
    return ("📥 Video Downloader — sudhu PUBLIC video: 'video download "
            "koro <url>' bolo. yt-dlp lagbe; private/login video hobe na.")


def _sms_sender_status():
    return ("📱 SMS Sender — SMS pathate 'SMS pathao <number>-e: <message>' "
            "bolo. Phone pair kora thakte hobe.")


def _youtube_play_run():
    """Play a Sheru video on Mark's own video screen (HUD player when
    available, else Chrome via the browser driver). Honest when the
    YouTube API key / Chrome is missing. Never raises."""
    try:
        from core import youtube_agent as _yt
        return _yt.play_video("Sheru")
    except Exception as e:
        return f"YouTube chalate parlam na: {e}"


def _video_upload_browser_status() -> str:
    try:
        from core import video_upload as _vu
        lines = ["📤 Video Upload (Browser) — readiness:",
                 "  • Sites: Instagram, Facebook, YouTube (browser diye)",
                 f"  • Mode: {_vu.get_mode()} (Manual-e tumi click koro, ami dekhi)",
                 "  • Instagram limit: " + _vu.site_limit("instagram"),
                 "  • Facebook limit: " + _vu.site_limit("facebook"),
                 "  • YouTube limit: " + _vu.site_limit("youtube"),
                 "  • Login lagbe prottek site-e (Chrome-e tomar account)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Video Upload status dekhte parlam na: {e}"


def _social_auto_status() -> str:
    try:
        from core import social_auto as _sa
        t = _sa.toggles()
        lines = ["💬 Social Auto — toggles (sob OFF by default):"]
        for name in _sa.TOGGLES:
            lines.append(f"  • {name}: {'ON' if t.get(name) else 'OFF'}")
        lines.append(_sa.limits_text())
        return "\n".join(lines)
    except Exception as e:
        return f"Social Auto status dekhte parlam na: {e}"


def _mouse_video_edit_status() -> str:
    try:
        from core import mouse_video_edit as _mve
        return "✂️ Mouse Video Editor — " + _mve.editor_status_text()
    except Exception as e:
        return f"Mouse Video Editor status dekhte parlam na: {e}"


def _app_editor_status() -> str:
    return ("🖥️ App Editor — jekono desktop app khule mouse diye chalai "
            "(Notepad/Word/Paint/Photos...). App-er naam bolo.")


def _browser_setup_status() -> str:
    try:
        from core import browser_setup as _bs
        return _bs.status_text()
    except Exception as e:
        return f"Browser Setup status dekhte parlam na: {e}"


def _hosting_deploy_status() -> str:
    try:
        from plugins import hosting_deploy as _hd
        return _hd.status_text()
    except Exception as e:
        return f"Hosting / Deploy status dekhte parlam na: {e}"


def _advanced_browser_status() -> str:
    try:
        from core import browser_driver as _drv
        chrome = _drv.find_chrome_exe()
        lines = ["🌐 Advanced Browser Control — readiness:",
                 ("✅ Chrome pelam: " + chrome) if chrome else
                 "❌ Chrome install pelam na ei PC-te",
                 "  • Actions: open / click / type / fill / scroll / play / "
                 "upload / multi-tab / wait / screenshot",
                 "  • Prottek step-er pore page verify hoy; fail hole step-er "
                 "naam bolei theme jay.",
                 "  • Login: tomar nijer Chrome profile — ami password dekhi "
                 "na, rakhi na."]
        return "\n".join(lines)
    except Exception as e:
        return f"Browser Control status dekhte parlam na: {e}"


_ACTIONS = {
    "main_status": _main_status,
    "video_upload_status": _video_upload_status,
    "apk_build_status": _apk_build_status,
    "render_deploy_run": _render_deploy_run,
    "browser_open": _browser_open,
    "firebase_run": _firebase_run,
    "hosting_autofix_run": _hosting_autofix_run,
    "whatsapp_status": _whatsapp_status,
    "live_screen_status": _live_screen_status,
    "mouse_demo": _mouse_demo,
    "video_edit_status": _video_edit_status,
    "github_status": _github_status,
    "link_status": _link_status,
    "location_status": _location_status,
    "memory_status": _memory_status,
    "mood_status": _mood_status,
    "music_search": _music_search,
    "pc_screenshot": _pc_screenshot,
    "device_status": _device_status,
    "voice_notes_status": _voice_notes_status,
    "open_calculator": _open_calculator,
    "translate_sample": _translate_sample,
    "weather_now": _weather_now,
    "news_now": _news_now,
    "python_run_status": _python_run_status,
    "software_builder_status": _software_builder_status,
    "photo_editor_status": _photo_editor_status,
    "data_analyzer_status": _data_analyzer_status,
    "report_writer_status": _report_writer_status,
    "email_sender_status": _email_sender_status,
    "file_organizer_status": _file_organizer_status,
    # ── 50 utility card actions ──
    "timer_status": _timer_status,
    "stopwatch_status": _stopwatch_status,
    "pomodoro_status": _pomodoro_status,
    "world_clock_status": _world_clock_status,
    "sleep_timer_status": _sleep_timer_status,
    "focus_mode_status": _focus_mode_status,
    "unit_convert_sample": _unit_convert_sample,
    "currency_convert_sample": _currency_convert_sample,
    "code_format_sample": _code_format_sample,
    "json_view_sample": _json_view_sample,
    "regex_test_sample": _regex_test_sample,
    "file_search_sample": _file_search_sample,
    "zip_tool_status": _zip_tool_status,
    "storage_analyzer_run": _storage_analyzer_run,
    "disk_cleanup_preview": _disk_cleanup_preview,
    "download_manager_status": _download_manager_status,
    "image_resizer_status": _image_resizer_status,
    "clipboard_get": _clipboard_get,
    "system_info_run": _system_info_run,
    "process_list_run": _process_list_run,
    "startup_list_run": _startup_list_run,
    "network_speed_run": _network_speed_run,
    "wifi_networks_run": _wifi_networks_run,
    "bluetooth_devices_run": _bluetooth_devices_run,
    "vpn_status_run": _vpn_status_run,
    "battery_monitor_run": _battery_monitor_run,
    "screen_recorder_status": _screen_recorder_status,
    "qr_generator_sample": _qr_generator_sample,
    "password_generator_run": _password_generator_run,
    "meme_maker_status": _meme_maker_status,
    "subtitle_maker_status": _subtitle_maker_status,
    "invoice_maker_status": _invoice_maker_status,
    "resume_builder_status": _resume_builder_status,
    "notes_list": _notes_list,
    "habit_status_run": _habit_status_run,
    "expense_summary_run": _expense_summary_run,
    "bookmark_list_run": _bookmark_list_run,
    "contacts_list": _contacts_list,
    "calendar_today_run": _calendar_today_run,
    "flashcard_quiz_run": _flashcard_quiz_run,
    "quiz_make_run": _quiz_make_run,
    "poll_status_run": _poll_status_run,
    "dictionary_sample": _dictionary_sample,
    "audio_converter_status": _audio_converter_status,
    "video_downloader_status": _video_downloader_status,
    "youtube_play_run": _youtube_play_run,
    "sms_sender_status": _sms_sender_status,
    "call_log_run": _call_log_run,
    "step_counter_run": _step_counter_run,
    "vault_status": _vault_status,
    "video_upload_browser_status": _video_upload_browser_status,
    "social_auto_status": _social_auto_status,
    "mouse_video_edit_status": _mouse_video_edit_status,
    "app_editor_status": _app_editor_status,
    "advanced_browser_status": _advanced_browser_status,
    "browser_setup_status": _browser_setup_status,
    "hosting_deploy_status": _hosting_deploy_status,
}


# ── run ──────────────────────────────────────────────────────────────────────

def run_card(card_id: str, actions: dict | None = None) -> str:
    """Run one card's default action. Returns a short string, never raises.
    `actions` overrides the real action map (tests inject fakes)."""
    try:
        card = card_def(card_id)
        if card is None:
            return f"Agent card '{card_id}' khuje pelam na."
        table = actions if isinstance(actions, dict) else _ACTIONS
        fn = table.get(card["action"])
        if not callable(fn):
            return f"{card['name']} card-er action khuje pelam na."
        out = fn()
        return str(out or "")[:1500] or f"{card['name']} — kichu uttor elo na."
    except Exception as e:
        return f"Card chalate parlam na: {e}"
