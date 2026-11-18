"""plugins/cat02_browser.py — 🌐 BROWSER CONTROL (Category 2, features 21-40).

One dispatcher plugin — the loader registers exactly ONE tool per file, so
the Category 2 tools are `action`s of `browser_tools`, not separate files:

    download_manager   download a URL into ~/Downloads/Jarvis/<type>/, or list
    web_scrape         title / description / prices / tables from a URL
    price_compare      cheapest-first prices for a product (web_search + scrape)
    page_screenshot    JPEG of the current page via the browser helper
    browser_tabs       list / switch / close / new tab (browser helper tabs API)
    bookmarks          save / list / open bookmarks (browser helper bookmarks API)
    read_summary       read the current page, summarise it with Gemini
    browser_scroll_watch  scroll, or auto-scroll to the bottom step by step
    browser_form_fill  fill a form by field label (browser helper; never submits)
    close_popups       close popup/banner controls (never accepts cookies)

How each action reaches the browser:
  * Browser helper actions (screenshot, tabs, bookmarks, fill, close_popups,
    autoscroll) go through the dashboard's browser-command queue
    (dashboard/server.py queue_browser_command / wait_browser_result).
    The plugin finds the running DashboardServer in-process (it is the same
    process as the app) and falls back to HTTP on the local dashboard with
    the browser token from Settings when it cannot — it never invents a
    token and never stores one.
  * Page actions that Playwright can do (read, plain scroll, screenshot
    fallback, form fill by selector) go through the normal tool runner:
    player.run_tool() when a player is present, else
    core.automation.ENGINE.get_tool_runner(). Either may be absent (tests,
    phone dashboard) — then the action says so honestly instead of failing.

Privacy / safety, same as the rest of browser control:
  * Website passwords are NEVER stored, shown or sent: logins/signups are
    filled only from the browser helper popup's own chrome.storage.local.
  * Captcha: Mark NEVER solves a captcha automatically. If a page shows one,
    the tool says so and asks the user to solve it in the browser, then
    continue — there is no auto-solve path anywhere in this file.
  * close_popups never clicks "Accept"/"Allow" on a cookie banner — only
    explicit close/dismiss controls, or "Reject"/"Decline".
  * Closing a tab is confirm-first: pass confirm=true, or the tool asks.
  * Downloads are capped (200 MB) and organised by file type; filenames are
    sanitised so a URL can never write outside the download folder.
"""
from __future__ import annotations

import base64
import gc
import html
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

PLUGIN = {
    "name": "browser_tools",
    "description": (
        "Category 2 browser tools (features 21-40), dispatched by 'action'. "
        "download_manager: download a URL into Downloads/Jarvis by file type, "
        "or list downloads. web_scrape: title, description, prices and tables "
        "from a URL. price_compare: cheapest-first prices for a product. "
        "page_screenshot: JPEG screenshot of the current page (Chrome "
        "browser helper). browser_tabs: list, switch, close (confirm=true first) "
        "or open a new tab. bookmarks: save, list or open a bookmark. "
        "read_summary: read the current page and summarise it. "
        "browser_scroll_watch: scroll, or auto-scroll to the bottom step by "
        "step. browser_form_fill: fill a form by field label — never submits "
        "it. close_popups: close popup/banner controls. "
        "CAPTCHA: Mark never solves a captcha automatically — if a page shows "
        "one, it asks the user to solve it in the browser and continue. "
        "Website passwords are never stored, shown or sent by any of these. "
        "Call with action=<one of the names above> plus that action's args."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "download_manager | web_scrape | price_compare | "
                    "page_screenshot | browser_tabs | bookmarks | read_summary | "
                    "browser_scroll_watch | browser_form_fill | close_popups"
                ),
            },
            "url": {"type": "STRING", "description": "URL to download, scrape, compare, bookmark or open in a new tab."},
            "filename": {"type": "STRING", "description": "download_manager: optional new name for the downloaded file."},
            "product": {"type": "STRING", "description": "price_compare: the product to compare prices for."},
            "store_urls": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "price_compare: optional store/product URLs to scrape prices from, in addition to web search.",
            },
            "fields": {
                "type": "OBJECT",
                "description": "browser_form_fill: {field label: value}, e.g. {\"City\": \"Kolkata\"} — matched by visible label, placeholder or input name. Values are never returned.",
            },
            "tab_action": {"type": "STRING", "description": "browser_tabs: list | switch | close | new (default list)."},
            "tab_id": {"type": "INTEGER", "description": "browser_tabs: tab id from 'list', for switch / close."},
            "bookmark_action": {"type": "STRING", "description": "bookmarks: save | list | open (default list)."},
            "bookmark_id": {"type": "STRING", "description": "bookmarks: bookmark id from 'list', for open."},
            "title": {"type": "STRING", "description": "bookmarks save: title for the bookmark (default: the URL)."},
            "text": {"type": "STRING", "description": "bookmarks list: search text. browser_scroll_watch: scroll amount in pixels."},
            "direction": {"type": "STRING", "description": "browser_scroll_watch scroll: up | down (default down)."},
            "amount": {"type": "INTEGER", "description": "browser_scroll_watch scroll: pixels per scroll (default 500)."},
            "step": {"type": "INTEGER", "description": "browser_scroll_watch watch: pixels per auto-scroll step (default 800)."},
            "max_steps": {"type": "INTEGER", "description": "browser_scroll_watch watch: max auto-scroll steps (default 20)."},
            "scroll_action": {"type": "STRING", "description": "browser_scroll_watch: scroll | watch (default scroll)."},
            "confirm": {"type": "BOOLEAN", "description": "browser_tabs close: pass true to confirm closing the tab."},
        },
        "required": ["action"],
    },
}

_ACTIONS = (
    "download_manager", "web_scrape", "price_compare", "page_screenshot",
    "browser_tabs", "bookmarks", "read_summary", "browser_scroll_watch",
    "browser_form_fill", "close_popups",
)

_MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024   # 200 MB — a bigger file is not a download, it is a decision
_MAX_FETCH_BYTES = 2 * 1024 * 1024        # scrape cap: enough for a page, not for a dump
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/124.0.0.0 Safari/537.36"}

_TYPE_DIRS = {
    "images": {"png", "jpg", "jpeg", "gif", "webp", "svg", "avif", "bmp", "ico"},
    "videos": {"mp4", "mkv", "webm", "mov", "avi", "mpg", "mpeg"},
    "documents": {"pdf", "doc", "docx", "txt", "md", "epub", "rtf", "odt",
                  "xls", "xlsx", "csv", "ppt", "pptx"},
    "audio": {"mp3", "wav", "ogg", "m4a", "flac", "aac"},
    "archives": {"zip", "tar", "gz", "7z", "rar", "xz"},
}
_PRICE_RE = re.compile(
    r"(?:₹|\$|€|£|Rs\.?|INR)\s?[\d,]+(?:\.\d{1,2})?")
_PRICE_NUM_RE = re.compile(r"[\d,]+(?:\.\d{1,2})?")


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _short(text: str, limit: int = 1200) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _is_failed(text: str | None) -> bool:
    return bool(text) and str(text).startswith("status=failed")


def _log(player, text: str) -> None:
    if player is None:
        return
    try:
        player.write_log(f"JARVIS: {text}")
    except Exception:
        pass


# ── tool runner (Playwright browser_control, web_search, …) ─────────────────

def _run_tool(player, name: str, params: dict):
    """Run another tool: player.run_tool() first, else the automation
    engine's full runner (actions + plugins + inline tools). Returns the
    tool's string, or None when no runner is wired at all."""
    fn = None
    if player is not None:
        fn = getattr(player, "run_tool", None)
    if not callable(fn):
        try:
            from core.automation import ENGINE
            fn = ENGINE.get_tool_runner()
        except Exception:
            fn = None
    if not callable(fn):
        return None
    try:
        return str(fn(name, params or {}) or "")
    except Exception as e:
        return f"status=failed action={name} reason=tool runner error: {e}"


# ── browser helper commands (via the dashboard's browser queue) ───────────

def _dashboard_server():
    """The running DashboardServer, found in-process: plugins run in the
    app's own process, and the server object is the one main.py built.
    gc is the only handle — main.py keeps JarvisLive in a local, not a
    module global, so there is nothing cleaner to read. Returns None when
    the dashboard never started (tests, phone dashboard)."""
    try:
        from dashboard.server import DashboardServer
        for obj in gc.get_objects():
            if isinstance(obj, DashboardServer):
                return obj
    except Exception:
        pass
    return None


def _ext_command_http(action: str, timeout: float, **extra):
    """Fallback when no in-process server object exists: queue over HTTP on
    the local dashboard (port 8000, or 8001 when TLS is on) with the browser
    token from Settings — the same token the browser helper popup holds. The
    token is read, never logged, never stored anywhere else. Returns the
    browser helper's result dict, or None when the local dashboard is not
    reachable at all."""
    try:
        from memory.config_manager import get_plugin_config
        token = str((get_plugin_config("jarvis_link") or {})
                    .get("browser_token") or "").strip()
    except Exception:
        token = ""
    if not token:
        return None
    try:
        import requests
    except Exception:
        return None
    body = {"action": action}
    for key in ("url", "selector", "text"):
        if extra.get(key) not in (None, ""):
            body[key] = extra.pop(key)
    body.update(extra)
    headers = {"X-Browser-Token": token}
    cmd_id = None
    live_base, live_verify = "http://127.0.0.1:8000", True
    for base, verify in (("http://127.0.0.1:8000", True),
                         ("https://127.0.0.1:8001", False)):
        try:
            r = requests.post(base + "/api/browser/command", json=body,
                              headers=headers, timeout=5, verify=verify)
            if r.status_code == 401:
                return {"ok": False,
                        "error": "browser token mismatch — check the token in "
                                 "the browser helper popup matches the dashboard"}
            data = r.json()
            cmd_id = data.get("id")
            if cmd_id:
                live_base, live_verify = base, verify
                break
        except Exception:
            continue
    if not cmd_id:
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(live_base + f"/api/browser/result/{cmd_id}",
                             headers=headers, timeout=5, verify=live_verify)
            if r.status_code == 200:
                res = (r.json() or {}).get("result") or {}
                return {"ok": bool(res.get("ok")), "data": res.get("data"),
                        "error": res.get("error") or ""}
        except Exception:
            pass
        time.sleep(2)
    return {"ok": False, "error": "timeout"}


def _ext_command(action: str, timeout: float = 30.0, **extra) -> dict:
    """Queue one command for the browser helper and wait for its answer.

    Always returns a dict {ok, data, error} — never raises, never returns
    None. ok=False + an honest error when the dashboard is not running or
    no browser helper is connected (the browser helper polls every ~3 s, so a
    timeout means it is not connected, not that the page is slow)."""
    srv = _dashboard_server()
    if srv is not None:
        try:
            cmd_id = srv.queue_browser_command(
                action,
                str(extra.pop("url", "") or ""),
                str(extra.pop("selector", "") or ""),
                str(extra.pop("text", "") or ""),
                extra or None,
            )
            res = srv.wait_browser_result(cmd_id, timeout)
            if res.get("ok"):
                return {"ok": True, "data": res.get("data"),
                        "error": ""}
            return {"ok": False, "data": res.get("data"),
                    "error": str(res.get("error") or "timeout")}
        except Exception as e:
            return {"ok": False, "error": f"browser command failed: {e}"}
    res = _ext_command_http(action, timeout, **extra)
    if res is not None:
        return res
    return {"ok": False,
            "error": "dashboard not running, or no browser helper "
                     "connected — open Mark's dashboard (Remote Control) and "
                     "connect the browser helper popup first"}

# ── download_manager ────────────────────────────────────────────────────────

def _safe_filename(name: str, fallback: str = "download") -> str:
    name = unquote(str(name or "")).strip().replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._\- ]+", "_", name).strip(" .")
    return name or fallback


def _type_dir(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    for folder, exts in _TYPE_DIRS.items():
        if ext in exts:
            return folder
    return "other"


def _download_manager(params: dict) -> str:
    url = str(params.get("url") or "").strip()
    if not url:
        # No URL → list what is already downloaded.
        root = Path.home() / "Downloads" / "Jarvis"
        if not root.exists():
            return "Downloads/Jarvis-e ekhono kichu download kora nei."
        files = sorted((p for p in root.rglob("*") if p.is_file()),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:20]
        if not files:
            return "Downloads/Jarvis-e ekhono kichu download kora nei."
        lines = []
        for p in files:
            kb = p.stat().st_size / 1024
            size = f"{kb:.0f} KB" if kb < 1024 else f"{kb / 1024:.1f} MB"
            lines.append(f"• {p.parent.name}/{p.name} ({size})")
        return "Downloads:\n" + "\n".join(lines)
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        import requests
    except Exception:
        return "Download korte parlam na — requests library nei."
    # Filename: explicit rename wins, else Content-Disposition, else the URL.
    # NOTE: _safe_filename("") returns its "download" fallback, so only call
    # it when the user actually gave a name — otherwise every download
    # without a rename would land as download.txt.
    raw_rename = str(params.get("filename") or "").strip()
    rename = _safe_filename(raw_rename) if raw_rename else ""
    try:
        r = requests.get(url, stream=True, timeout=30, headers=_UA)
    except Exception as e:
        return f"Download korte parlam na: {e}"
    if r.status_code != 200:
        return (f"Download korte parlam na — server bollo HTTP "
                f"{r.status_code} ({url}).")
    total = int(r.headers.get("content-length") or 0)
    if total > _MAX_DOWNLOAD_BYTES:
        return (f"File-ta onek boro ({total / 1048576:.0f} MB) — 200 MB-er "
                "beshi download kori na, vul kore boro file namate giye "
                "disk bhorbe na.")
    name = rename
    if not name:
        disp = r.headers.get("content-disposition") or ""
        m = re.search(r"filename\*?=(?:UTF-8''|\"?)([^\";]+)", disp)
        name = _safe_filename(m.group(1) if m else
                              urlparse(url).path.rsplit("/", 1)[-1],
                              "download")
    if "." not in name:
        ext = urlparse(url).path.rsplit(".", 1)[-1].lower()
        if re.fullmatch(r"[a-z0-9]{2,5}", ext or ""):
            name += "." + ext
    folder = _type_dir(name)
    dest = Path.home() / "Downloads" / "Jarvis" / folder
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return f"Download folder banate parlam na: {e}"
    path = dest / name
    if path.exists():
        stem, suffix = path.stem, path.suffix
        for i in range(2, 100):
            path = dest / f"{stem} ({i}){suffix}"
            if not path.exists():
                break
    written = 0
    try:
        with open(path, "wb") as f:
            for chunk in r.iter_content(1024 * 64):
                if not chunk:
                    continue
                written += len(chunk)
                if written > _MAX_DOWNLOAD_BYTES:
                    f.close()
                    path.unlink(missing_ok=True)
                    return ("Download bondho korlam — file 200 MB chariye "
                            "jachhe.")
                f.write(chunk)
    except Exception as e:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return f"Download majhpathe theme gelo: {e}"
    mb = written / 1048576
    if written < 1024:
        size = f"{written} B"
    elif written < 1048576:
        size = f"{written / 1024:.0f} KB"
    else:
        size = f"{mb:.1f} MB"
    return f"✅ Download holo: {path} ({size}) — {folder} folder-e rakhlam."


# ── web_scrape ──────────────────────────────────────────────────────────────

class _StdlibScraper(HTMLParser):
    """Title / meta description / tables / visible text with the stdlib only
    (used when beautifulsoup4 is not installed — requirements.txt lists it,
    but a missing install must disable exactly this, never the plugin)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.tables: list[list[list[str]]] = []
        self._in_title = False
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cell = ""
        self._row: list[str] = []
        self._table: list[list[str]] = []
        self._text: list[str] = []
        self._skip = 0  # inside script/style

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
            return
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            d = dict(attrs)
            if d.get("name", "").lower() == "description":
                self.description = d.get("content", "")
        if tag == "table":
            self._in_table = True
            self._table = []
        if tag == "tr" and self._in_table:
            self._in_row = True
            self._row = []
        if tag in ("td", "th") and self._in_row:
            self._in_cell = True
            self._cell = ""

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        if tag == "title":
            self._in_title = False
        if tag == "table" and self._in_table:
            self._in_table = False
            if self._table:
                self.tables.append(self._table)
        if tag == "tr" and self._in_row:
            self._in_row = False
            if self._row:
                self._table.append(self._row)
        if tag in ("td", "th") and self._in_cell:
            self._in_cell = False
            self._row.append(self._cell.strip())

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
        elif self._in_cell:
            self._cell += data
        else:
            self._text.append(data)

    @property
    def text(self) -> str:
        return " ".join(t.strip() for t in self._text if t.strip())


def _fetch_html(url: str) -> str | None:
    try:
        import requests
        r = requests.get(url, timeout=20, headers=_UA)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    raw = r.content[:_MAX_FETCH_BYTES]
    # requests guesses ISO-8859-1 for text/html with no charset, which turns
    # UTF-8 pages into mojibake (₹ becomes â€¦) and hides every non-ASCII
    # price. Pages are overwhelmingly UTF-8: try that first, then what
    # requests detected, then latin-1 as a last resort.
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode(r.apparent_encoding or "latin-1", errors="replace")
    except Exception:
        return raw.decode("utf-8", errors="replace")


def _scrape_page(url: str):
    """Returns (title, description, prices, tables, text) or None on fetch
    failure. bs4 when it is installed, stdlib html.parser otherwise."""
    page = _fetch_html(url)
    if page is None:
        return None
    try:
        from bs4 import BeautifulSoup  # noqa: PLC0415 — optional, listed in requirements.txt
        soup = BeautifulSoup(page, "html.parser")
        title = (soup.title.string or "").strip() if soup.title else ""
        desc = ""
        meta = soup.find("meta", attrs={"name": "description"})
        if meta:
            desc = str(meta.get("content") or "")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        tables = []
        for table in soup.find_all("table")[:3]:
            rows = []
            for tr in table.find_all("tr")[:6]:
                rows.append([c.get_text(" ", strip=True)
                             for c in tr.find_all(["td", "th"])])
            if rows:
                tables.append(rows)
        return title, desc, _PRICE_RE.findall(text)[:10], tables, text
    except ImportError:
        pass
    except Exception:
        pass
    sc = _StdlibScraper()
    try:
        sc.feed(page)
    except Exception:
        pass
    return (sc.title.strip(), sc.description,
            _PRICE_RE.findall(sc.text)[:10], sc.tables[:3], sc.text)


def _web_scrape(params: dict) -> str:
    url = str(params.get("url") or "").strip()
    if not url:
        return "Kon URL scrape korbo — URL-ta dao."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    got = _scrape_page(url)
    if got is None:
        return (f"Page-ta khulte parlam na ({url}) — site-ta block korte "
                "pare, ba URL-ta vul.")
    title, desc, prices, tables, _text = got
    parts = []
    if title:
        parts.append(f"Title: {title[:200]}")
    if desc:
        parts.append(f"Description: {desc[:300]}")
    if prices:
        seen = list(dict.fromkeys(p.strip() for p in prices))[:10]
        parts.append("Prices: " + ", ".join(seen))
    for table in tables[:2]:
        rows = [" | ".join(row) for row in table[:5] if any(row)]
        if rows:
            parts.append("Table:\n" + "\n".join(rows))
    if not parts:
        return f"Page-ta khullo, kintu title/description/price/table kichui pelam na ({url})."
    return _short("\n".join(parts), 1500)


# ── price_compare ───────────────────────────────────────────────────────────

def _price_value(text: str):
    m = _PRICE_NUM_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except Exception:
        return None


def _price_compare(params: dict, player) -> str:
    product = str(params.get("product") or "").strip()
    stores = [str(u).strip() for u in (params.get("store_urls") or [])
              if str(u).strip()]
    if not product and not stores:
        return "Kon product-er daam compare korbo — product-er naam dao."
    found: list[tuple[float, str, str]] = []  # (value, label, source)
    if product:
        res = _run_tool(player, "web_search",
                        {"query": product, "mode": "price"})
        if res and not _is_failed(res):
            for line in str(res).splitlines():
                for price in _PRICE_RE.findall(line):
                    value = _price_value(price)
                    if value:
                        label = re.sub(r"\s+", " ", line).strip()[:120]
                        found.append((value, price, label or "web search"))
    for store_url in stores[:3]:
        got = _scrape_page(store_url)
        if got is None:
            continue
        _t, _d, prices, _tb, _x = got
        domain = urlparse(store_url).netloc or store_url
        for price in list(dict.fromkeys(prices))[:3]:
            value = _price_value(price)
            if value:
                found.append((value, price, domain))
    if not found:
        return (f"'{product or stores[0]}'-er daam kothao pelam na — "
                "site-gulo scrape block korte pare. Store-er URL dile "
                "abar try korbo.")
    found.sort(key=lambda item: item[0])
    lines = []
    for value, price, source in found[:8]:
        lines.append(f"• {price} — {source}")
    cheapest = found[0]
    return ("Cheapest first:\n" + "\n".join(lines) +
            f"\nSobcheye kom: {cheapest[1]} ({cheapest[2]}). "
            "Daam bodle jete pare — kenar age store-e check koro.")


# ── page_screenshot ─────────────────────────────────────────────────────────

def _page_screenshot(params: dict, player) -> str:
    res = _ext_command("screenshot", timeout=45.0)
    if res.get("ok") and isinstance(res.get("data"), dict):
        data_url = str((res.get("data") or {}).get("dataUrl") or "")
        page_url = str((res.get("data") or {}).get("url") or "")
        if data_url.startswith("data:image/"):
            try:
                raw = base64.b64decode(data_url.split(",", 1)[1])
            except Exception:
                raw = b""
            if raw:
                out_dir = _base_dir() / "memory" / "page_screenshots"
                try:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    path = out_dir / (
                        "page_" + time.strftime("%Y%m%d_%H%M%S") + ".jpg")
                    path.write_bytes(raw)
                    msg = f"✅ Screenshot nilam: {path}"
                    if page_url:
                        msg += f" (page: {page_url})"
                    _log(player, msg)
                    return msg
                except Exception as e:
                    return f"Screenshot nilam, kintu save korte parlam na: {e}"
    # Fallback: Playwright screenshot (PNG, Desktop by default in
    # browser_control) — no browser helper needed.
    fallback = _run_tool(player, "browser_control", {"action": "screenshot"})
    if fallback and not _is_failed(fallback):
        return str(fallback)
    err = str(res.get("error") or "browser helper theke screenshot elo na")
    return (f"Screenshot nite parlam na: {err}. browser helper connect "
            "kora ache kina dekho.")


# ── browser_tabs ────────────────────────────────────────────────────────────

def _browser_tabs(params: dict, player) -> str:
    sub = str(params.get("tab_action") or "list").strip().lower()
    if sub not in ("list", "switch", "close", "new"):
        return "tab_action dao: list | switch | close | new."
    if sub == "close" and not params.get("confirm"):
        tab_id = params.get("tab_id")
        which = f"tab {tab_id}" if tab_id else "ei tab"
        return (f"{which} bondho korbo? Confirm korte 'confirm' true diye "
                "abar bolo — bondho tab fire paoa jay na.")
    extra: dict = {"tab_action": sub}
    if params.get("tab_id") not in (None, ""):
        extra["tab_id"] = params.get("tab_id")
    if params.get("url"):
        extra["url"] = str(params.get("url"))
    res = _ext_command("tabs", timeout=30.0, **extra)
    if res.get("ok"):
        data = res.get("data") or {}
        if sub == "list":
            tabs = data.get("tabs") or []
            if not tabs:
                return "Kono tab khola nei (browser helper-e)."
            lines = [f"• [{t.get('id')}] {t.get('title') or '(no title)'}"
                     f"{' ◀ active' if t.get('active') else ''}"
                     f"\n  {t.get('url') or ''}" for t in tabs]
            return "Tabs:\n" + "\n".join(lines)
        if sub == "new":
            return f"✅ Notun tab khullam: {data.get('url') or ''}"
        if sub == "switch":
            return f"✅ Tab {data.get('tabId')} active korlam."
        return f"✅ Tab {data.get('tabId')} bondho korlam."
    # Fallback for the two actions Playwright also has.
    if sub == "new":
        out = _run_tool(player, "browser_control",
                        {"action": "new_tab",
                         "url": str(params.get("url") or "")})
        if out and not _is_failed(out):
            return str(out)
    if sub == "close":
        out = _run_tool(player, "browser_control", {"action": "close_tab"})
        if out and not _is_failed(out):
            return str(out)
    return (f"Tabs {sub} korte parlam na: "
            f"{res.get('error') or 'browser helper paoa jayni'}. "
            "browser helper connect kora ache kina dekho.")


# ── bookmarks ───────────────────────────────────────────────────────────────

def _bookmarks(params: dict) -> str:
    sub = str(params.get("bookmark_action") or "list").strip().lower()
    if sub not in ("save", "list", "open"):
        return "bookmark_action dao: save | list | open."
    extra: dict = {"bookmark_action": sub}
    if sub == "save":
        url = str(params.get("url") or "").strip()
        if not url:
            return "Kon URL bookmark korbo — URL dao."
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        extra["url"] = url
        extra["title"] = str(params.get("title") or url)
    if sub == "open":
        if params.get("url"):
            extra["url"] = str(params.get("url"))
        elif params.get("bookmark_id"):
            extra["bookmark_id"] = str(params.get("bookmark_id"))
        else:
            return "Kon bookmark khulbo — URL ba bookmark_id dao."
    if sub == "list" and params.get("text"):
        extra["text"] = str(params.get("text"))
    res = _ext_command("bookmarks", timeout=30.0, **extra)
    if not res.get("ok"):
        return (f"Bookmark {sub} korte parlam na: "
                f"{res.get('error') or 'browser helper paoa jayni'}. "
                "Bookmarks Chrome-e thake — browser helper connect kora thakte hobe.")
    data = res.get("data") or {}
    if sub == "save":
        return f"✅ Bookmark korlam: {data.get('title')} ({data.get('url')})"
    if sub == "open":
        return f"✅ Bookmark khullam: {data.get('url')}"
    items = data.get("bookmarks") or []
    if not items:
        return "Kono bookmark pelam na."
    lines = [f"• [{b.get('id')}] {b.get('title') or '(no title)'}"
             f"\n  {b.get('url')}" for b in items[:20]]
    return "Bookmarks:\n" + "\n".join(lines)


# ── read_summary ────────────────────────────────────────────────────────────

def _read_page_text(player) -> tuple[str, str]:
    """(text, source) — Playwright first, browser helper second."""
    out = _run_tool(player, "browser_control", {"action": "get_text"})
    if out and not _is_failed(out) and len(str(out).strip()) > 50:
        return str(out), "browser"
    res = _ext_command("read", timeout=30.0)
    if res.get("ok") and isinstance(res.get("data"), dict):
        text = str((res.get("data") or {}).get("text") or "")
        title = str((res.get("data") or {}).get("title") or "")
        if text.strip():
            return (f"{title}\n{text}" if title else text), "browser helper"
    return "", res.get("error") or "page porte parlam na"


def _read_summary(params: dict, player) -> str:
    text, err = _read_page_text(player)
    if not text.strip():
        return (f"Page-ta porte parlam na: {err}. Browser-e page khola "
                "ache kina dekho.")
    snippet = text.strip()[:6000]
    try:
        from core import gemini
        summary = gemini.text(
            "Summarise this web page in 5-8 short lines, in the same "
            "language as the page. Keep names, numbers and prices exact:\n\n"
            + snippet,
            tier=gemini.FAST, timeout_ms=30_000, default="")
    except Exception:
        summary = ""
    if summary:
        return _short(summary, 1200)
    # Gemini answered nothing — fall back to the page's own first lines
    # rather than inventing a summary.
    lines = [ln.strip() for ln in snippet.splitlines() if ln.strip()][:6]
    return ("Summary banate parlam na (AI uttor dilo na) — page-er prothom "
            "line-gulo:\n" + _short("\n".join(lines), 1000))


# ── browser_scroll_watch ────────────────────────────────────────────────────

def _browser_scroll_watch(params: dict, player) -> str:
    sub = str(params.get("scroll_action") or "scroll").strip().lower()
    if sub == "watch":
        step = int(params.get("step") or 800)
        max_steps = int(params.get("max_steps") or 20)
        res = _ext_command("autoscroll", timeout=45.0,
                           step=step, max_steps=max_steps)
        if res.get("ok"):
            data = res.get("data") or {}
            done = "bottom-e pouchalam" if data.get("reachedBottom") \
                else "bottom-e pouchano jayni"
            return (f"✅ Auto-scroll: {data.get('steps')} step, {done} "
                    f"(page height {data.get('pageHeight')} px). "
                    "Ebar 'read_summary' diye page-ta porte paro.")
        return (f"Auto-scroll korte parlam na: "
                f"{res.get('error') or 'browser helper paoa jayni'}.")
    direction = str(params.get("direction") or "down").strip().lower()
    amount = int(params.get("amount") or 500)
    selector = str(params.get("selector") or "")
    res = _ext_command("scroll", timeout=30.0,
                       text=str(amount if direction == "down" else -amount),
                       selector=selector)
    if res.get("ok"):
        data = res.get("data") or {}
        if data.get("scrolledTo"):
            return f"✅ Scroll korlam: {data.get('scrolledTo')}-e gelam."
        return f"✅ Scroll korlam {direction} {amount}px."
    out = _run_tool(player, "browser_control",
                    {"action": "scroll", "direction": direction,
                     "amount": amount})
    if out and not _is_failed(out):
        return str(out)
    return (f"Scroll korte parlam na: "
            f"{res.get('error') or 'browser helper paoa jayni'}.")


# ── browser_form_fill ───────────────────────────────────────────────────────

def _browser_form_fill(params: dict, player) -> str:
    fields = params.get("fields")
    if not isinstance(fields, dict) or not fields:
        return ("Kon field-e ki likhbo — fields dao, e.g. "
                "{\"City\": \"Kolkata\"}.")
    clean = {str(k): str(v) for k, v in fields.items()
             if str(k).strip() and str(v) != ""}
    if not clean:
        return "Fields khali — label ar value dao."
    res = _ext_command("fill", timeout=30.0, fields=clean)
    if res.get("ok"):
        data = res.get("data") or {}
        filled = data.get("filled") or []
        missed = data.get("missed") or []
        msg = f"✅ Form bhorlam: {', '.join(filled)} — form SUBMIT korini."
        if missed:
            msg += f" Pelam na: {', '.join(missed)}."
        return msg
    # Fallback: Playwright fill_form takes CSS selectors, not labels — only
    # try it when every key already looks like a selector.
    if all(str(k).strip()[:1] in "#.["
           or ">" in str(k) or "[" in str(k) for k in clean):
        out = _run_tool(player, "browser_control",
                        {"action": "fill_form", "fields": clean})
        if out and not _is_failed(out):
            return str(out)
    return (f"Form bhorti korte parlam na: "
            f"{res.get('error') or 'browser helper paoa jayni'}. "
            "Browser helper-e fill label diye khonje; selector diye bhorti korte "
            "chaile selector dao.")


# ── close_popups ────────────────────────────────────────────────────────────

def _close_popups() -> str:
    res = _ext_command("close_popups", timeout=30.0)
    if not res.get("ok"):
        return (f"Popup bondho korte parlam na: "
                f"{res.get('error') or 'browser helper paoa jayni'}.")
    data = res.get("data") or {}
    closed = int(data.get("closed") or 0)
    if closed:
        return f"✅ {closed}-ta popup/banner bondho korlam."
    return ("Bondho korar moto popup/banner pelam na — page-ta emnitei "
            "porishkar.")


# ── dispatch ────────────────────────────────────────────────────────────────

def run(parameters: dict, player=None, session_memory=None) -> str:
    """Dispatch one Category 2 browser action. Never raises."""
    try:
        params = parameters or {}
        action = str(params.get("action") or "").strip().lower()
        if action == "download_manager":
            out = _download_manager(params)
        elif action == "web_scrape":
            out = _web_scrape(params)
        elif action == "price_compare":
            out = _price_compare(params, player)
        elif action == "page_screenshot":
            out = _page_screenshot(params, player)
        elif action == "browser_tabs":
            out = _browser_tabs(params, player)
        elif action == "bookmarks":
            out = _bookmarks(params)
        elif action == "read_summary":
            out = _read_summary(params, player)
        elif action == "browser_scroll_watch":
            out = _browser_scroll_watch(params, player)
        elif action == "browser_form_fill":
            out = _browser_form_fill(params, player)
        elif action == "close_popups":
            out = _close_popups()
        else:
            out = ("Action dao: " + ", ".join(_ACTIONS) + ".")
        _log(player, str(out)[:200])
        return _short(str(out), 1500)
    except Exception as e:
        return f"Browser tool-e error holo: {e}"
