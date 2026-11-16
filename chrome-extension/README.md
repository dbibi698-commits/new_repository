# Mark-LVII Browser Control — Chrome extension

Lets Mark-LVII drive **this browser** through its dashboard: open pages,
click, type, scroll, read page text, and log in — only when Mark (or you, via
the dashboard) asks it to.

## Install (unpacked — no Chrome Web Store)

1. Open `chrome://extensions` in Chrome (or any Chromium browser).
2. Turn **Developer mode** ON (top right).
3. Click **Load unpacked** and pick this `chrome-extension` folder.
4. Click the extension icon → set:
   - **Mark dashboard URL** — on the same Wi-Fi: `http://192.168.1.108:8000`
     (your PC's LAN IP — the Jarvis Link overlay shows it), or from anywhere:
     your Render URL, e.g. `https://<your-app>.onrender.com`.
   - **Browser token** — the shared secret. Mark creates it when the dashboard
     starts and stores it in `config/api_keys.json` under
     `plugin_config.jarvis_link.browser_token` (or set `BROWSER_TOKEN` in the
     environment / on Render to fix it). Copy that value into the popup —
     never share it with anyone else.
5. Click **Connect**, then **Test** — it should report "Dashboard OK".

## How it works

- The extension polls `GET /api/browser/commands` every 3 s (with backoff
  up to 30 s on failure) using the `X-Browser-Token` header.
- Mark — or a remote caller such as Muse via the Render URL — queues a
  command with `POST /api/browser/command` and the same token.
- The extension runs it in the active tab and posts the result to
  `POST /api/browser/result`, which Mark can wait on (up to 60 s).

## Examples

| Want | Command (action / url / selector / text) |
|---|---|
| Open GitHub | `open` / `https://github.com` |
| Open WhatsApp Web | `open` / `https://web.whatsapp.com` |
| Go to a page in the current tab | `navigate` / `https://github.com` |
| Click a button/link | `click` / selector `#submit` or text `Sign in` |
| Type into a field | `type` / selector `input[name=q]` / text `mark-lvii` |
| Scroll down | `scroll` / text `800` (pixels; or a selector to scroll to) |
| Read the page | `read` (returns title, URL, first ~4000 chars) |
| Log in | `login` — fills the username/password fields (see below) |

## Login flow (passwords stay in this browser)

1. In the extension popup, fill **Saved login — username** and **password**
   and click **Save**. They are stored in `chrome.storage.local` only.
2. Open the login page, then send a `login` command.
3. The extension fills the fields. It does **not** press submit — you (or a
   later `click` command) do that, so a wrongly filled form is never sent.
4. **Mark never sees the password.** The dashboard never receives, stores, or
   logs any credential — the extension only uses what you saved in the popup.

## Honest limits

- This is an **unpacked install, NOT the Chrome Web Store**. Publishing there
  needs a paid Chrome Web Store developer account ($5) plus Google review, and
  is not part of this delivery.
- The extension only acts when the dashboard is **reachable**: same LAN
  (`http://<PC-IP>:8000`), or the Render URL from anywhere. If the PC is off
  or Render is asleep, commands queue (max 20, 60 s expiry) and time out.
- It can only drive pages the content script runs on (`http://`/`https://`).
  Chrome's own pages (`chrome://…`, the Web Store) and some login pages with
  extra bot checks may refuse clicks/fills.
- The browser token is a shared secret: anyone who has it can queue browser
  commands. Keep it private, and rotate it by deleting
  `plugin_config.jarvis_link.browser_token` from `config/api_keys.json`
  (a new one is generated on the next dashboard start) or changing
  `BROWSER_TOKEN`.

## Files

- `manifest.json` — Manifest V3, permissions: tabs, scripting, storage, activeTab
- `background.js` — service worker: polls, runs commands, posts results
- `content.js` — runs in pages: click / type / scroll / read / login
- `popup.html` + `popup.js` — settings, status, Connect/Disconnect, Test
- `icons/` — 16/48/128 px icons (generated, no external assets)
