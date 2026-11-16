// background.js — Mark-LVII Browser Control (service worker)
//
// Polls the Mark dashboard for queued browser commands and carries them out
// in this browser, then posts the result back. The dashboard is the only
// thing that can queue commands, and only with the shared browser token
// (X-Browser-Token) — a different secret from the dashboard login tokens.
//
// Login credentials are NEVER fetched from Mark: for a "login" command this
// worker attaches the username/password saved in the popup's own
// chrome.storage.local, and nothing else.

const POLL_MS = 3000;        // normal poll interval
const MAX_BACKOFF_MS = 30000; // on failure, double up to this
const RESULT_TIMEOUT_MS = 10000;

let pollTimer = null;
let backoffMs = POLL_MS;
let lastPollAt = 0;          // epoch ms of the last successful poll
let lastPollError = "";

// ── storage helpers ─────────────────────────────────────────────────────────

function getSettings() {
  return chrome.storage.local.get({
    dashboardUrl: "",
    browserToken: "",
    connected: false,
    extId: "",
    loginUsername: "",
    loginPassword: "",
  });
}

async function getExtId() {
  const s = await getSettings();
  if (s.extId) return s.extId;
  const id = "ext-" + Math.random().toString(36).slice(2, 10);
  await chrome.storage.local.set({ extId: id });
  return id;
}

// ── dashboard calls ─────────────────────────────────────────────────────────

async function dashFetch(base, path, opts = {}) {
  const s = await getSettings();
  const url = base.replace(/\/+$/, "") + path;
  const res = await fetch(url, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      "X-Browser-Token": s.browserToken || "",
      ...(opts.headers || {}),
    },
    signal: AbortSignal.timeout(RESULT_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

async function postResult(base, id, ok, data, error) {
  try {
    await dashFetch(base, "/api/browser/result", {
      method: "POST",
      body: JSON.stringify({ id, ok, data: data ?? null, error: error || "" }),
    });
  } catch (e) {
    // A failed result post must never kill the poll loop.
    console.warn("[Mark] result post failed:", e);
  }
}

// ── command execution ───────────────────────────────────────────────────────

async function activeTabId() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tabs.length) throw new Error("no active tab");
  return tabs[0].id;
}

function sendToTab(tabId, cmd) {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tabId, cmd, (resp) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message ||
          "content script not ready — reload the page and try again" });
      } else {
        resolve(resp || { ok: false, error: "no reply from page" });
      }
    });
  });
}

async function runCommand(cmd) {
  const action = (cmd.action || "").toLowerCase();

  if (action === "open") {
    if (!cmd.url) return { ok: false, error: "open needs a url" };
    const tab = await chrome.tabs.create({ url: cmd.url, active: true });
    return { ok: true, data: { tabId: tab.id, url: cmd.url } };
  }

  if (action === "navigate") {
    if (!cmd.url) return { ok: false, error: "navigate needs a url" };
    const tabId = await activeTabId();
    await chrome.tabs.update(tabId, { url: cmd.url });
    return { ok: true, data: { tabId, url: cmd.url } };
  }

  // Everything else runs inside the active tab's content script.
  const tabId = await activeTabId();

  if (action === "login") {
    // Credentials come ONLY from this browser's popup storage.
    const s = await getSettings();
    if (!s.loginUsername || !s.loginPassword) {
      return { ok: false,
        error: "no login saved — save a username and password in the " +
               "extension popup first (they stay in this browser, Mark " +
               "never sees them)" };
    }
    return sendToTab(tabId, { ...cmd,
      credentials: { username: s.loginUsername, password: s.loginPassword } });
  }

  if (["click", "type", "scroll", "read"].includes(action)) {
    return sendToTab(tabId, cmd);
  }

  return { ok: false, error: "unknown action: " + (cmd.action || "") };
}

// ── poll loop ───────────────────────────────────────────────────────────────

async function pollOnce() {
  const s = await getSettings();
  if (!s.connected || !s.dashboardUrl || !s.browserToken) return;
  const extId = await getExtId();
  const base = s.dashboardUrl.replace(/\/+$/, "");
  try {
    const data = await dashFetch(base,
      "/api/browser/commands?ext=" + encodeURIComponent(extId));
    lastPollAt = Date.now();
    lastPollError = "";
    backoffMs = POLL_MS; // success resets the backoff
    const commands = (data && data.commands) || [];
    for (const cmd of commands) {
      try {
        const r = await runCommand(cmd);
        await postResult(base, cmd.id, !!r.ok, r.data ?? null, r.error || "");
      } catch (e) {
        await postResult(base, cmd.id, false, null, String(e && e.message || e));
      }
    }
  } catch (e) {
    lastPollError = String(e && e.message || e);
    backoffMs = Math.min(backoffMs * 2, MAX_BACKOFF_MS);
  }
}

function schedulePoll() {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    try { await pollOnce(); } catch (e) { /* never throw uncaught */ }
    schedulePoll();
  }, backoffMs);
}

function statusSnapshot() {
  return { lastPollAt, lastPollError, backoffMs };
}

// Popup asks for these (status line, last poll, Test button uses the same
// settings the worker does).
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "mark-status") {
    getSettings().then((s) => sendResponse({
      ...statusSnapshot(),
      connected: !!s.connected,
      dashboardUrl: s.dashboardUrl || "",
      hasToken: !!s.browserToken,
    }));
    return true;
  }
  if (msg && msg.type === "mark-test") {
    (async () => {
      const s = await getSettings();
      if (!s.dashboardUrl || !s.browserToken) {
        sendResponse({ ok: false, error: "set the dashboard URL and token first" });
        return;
      }
      try {
        const data = await dashFetch(s.dashboardUrl.replace(/\/+$/, ""),
          "/api/browser/status");
        sendResponse({ ok: true, data });
      } catch (e) {
        sendResponse({ ok: false, error: String(e && e.message || e) });
      }
    })();
    return true;
  }
  return false;
});

// Restart polling whenever settings change (Connect/Disconnect, new URL/token).
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" &&
      (changes.connected || changes.dashboardUrl || changes.browserToken)) {
    backoffMs = POLL_MS;
    schedulePoll();
  }
});

schedulePoll();
