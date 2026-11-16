// popup.js — Mark-LVII Browser Control popup
//
// Everything here lives in chrome.storage.local — this browser only.
// The dashboard URL + browser token are what the background worker uses to
// poll; the saved login is used only by content.js to fill a page's own
// login fields, and is never sent to Mark or the dashboard.

const $ = (id) => document.getElementById(id);
const statusEl = $("status");
const msgEl = $("msg");

function showMsg(text) {
  msgEl.textContent = text || "";
}

function timeAgo(ms) {
  if (!ms) return "never";
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return s + "s ago";
  return Math.floor(s / 60) + "m " + (s % 60) + "s ago";
}

async function refreshStatus() {
  const s = await chrome.storage.local.get({
    dashboardUrl: "", browserToken: "", connected: false,
  });
  let st;
  try {
    st = await chrome.runtime.sendMessage({ type: "mark-status" });
  } catch (e) {
    st = null;
  }
  const connected = !!s.connected && !!s.dashboardUrl && !!s.browserToken;
  const last = st ? st.lastPollAt : 0;
  const err = st ? st.lastPollError : "";
  statusEl.innerHTML =
    (connected
      ? '<span class="ok">● Connected</span>'
      : '<span class="bad">● Not connected</span>') +
    "<br>Dashboard: " + (s.dashboardUrl ? escapeHtml(s.dashboardUrl) : "not set") +
    "<br>Last poll: " + timeAgo(last) +
    (err ? "<br>Last error: " + escapeHtml(err) : "");
  $("connectBtn").textContent = s.connected ? "Disconnect" : "Connect";
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function loadFields() {
  const s = await chrome.storage.local.get({
    dashboardUrl: "", browserToken: "",
    loginUsername: "", loginPassword: "",
  });
  $("dashboardUrl").value = s.dashboardUrl || "";
  $("browserToken").value = s.browserToken || "";
  $("loginUsername").value = s.loginUsername || "";
  $("loginPassword").value = s.loginPassword || "";
}

async function saveFields() {
  const dashboardUrl = $("dashboardUrl").value.trim().replace(/\/+$/, "");
  const browserToken = $("browserToken").value.trim();
  await chrome.storage.local.set({
    dashboardUrl,
    browserToken,
    loginUsername: $("loginUsername").value,
    loginPassword: $("loginPassword").value,
  });
  return { dashboardUrl, browserToken };
}

$("saveBtn").addEventListener("click", async () => {
  try {
    await saveFields();
    showMsg("Saved in this browser.");
    await refreshStatus();
  } catch (e) {
    showMsg("Save failed: " + e.message);
  }
});

$("connectBtn").addEventListener("click", async () => {
  try {
    const { dashboardUrl, browserToken } = await saveFields();
    const s = await chrome.storage.local.get({ connected: false });
    if (!s.connected && (!dashboardUrl || !browserToken)) {
      showMsg("Set the dashboard URL and browser token first.");
      return;
    }
    await chrome.storage.local.set({ connected: !s.connected });
    showMsg(!s.connected ? "Connecting — polling the dashboard…" : "Disconnected.");
    await refreshStatus();
  } catch (e) {
    showMsg("Failed: " + e.message);
  }
});

$("testBtn").addEventListener("click", async () => {
  try {
    await saveFields();
    showMsg("Testing…");
    const res = await chrome.runtime.sendMessage({ type: "mark-test" });
    if (res && res.ok) {
      const d = res.data || {};
      showMsg("Dashboard OK — extensions seen: " +
        ((d.connected || []).join(", ") || "none yet") +
        " • queued: " + (d.queued ?? 0) +
        " • results: " + (d.results ?? 0));
    } else {
      showMsg("Test failed: " + ((res && res.error) || "no reply") +
        "\nCheck the URL is reachable and the token matches.");
    }
  } catch (e) {
    showMsg("Test failed: " + e.message);
  }
});

loadFields();
refreshStatus();
setInterval(refreshStatus, 3000);
