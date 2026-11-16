// content.js — Mark-LVII Browser Control (runs in every http(s) page)
//
// Receives one command at a time from background.js and carries it out in
// this page's DOM. Login credentials, when present, arrive only from the
// extension popup's own chrome.storage.local — Mark never sees them and this
// script never sends them anywhere except into the page's own login fields.

function findByText(text) {
  if (!text) return null;
  const needle = text.trim().toLowerCase();
  if (!needle) return null;
  const els = document.querySelectorAll(
    "button, a, input[type='submit'], input[type='button'], [role='button']");
  for (const el of els) {
    const label = (el.innerText || el.value || el.getAttribute("aria-label") || "")
      .trim().toLowerCase();
    if (label && (label === needle || label.includes(needle))) return el;
  }
  return null;
}

function findTarget(selector, text) {
  if (selector) {
    try {
      const el = document.querySelector(selector);
      if (el) return el;
    } catch (e) { /* bad selector — fall through to text search */ }
  }
  return findByText(text);
}

// Setting .value directly does not fire the events frameworks listen for,
// so use the native setter and dispatch input/change.
function setFieldValue(el, value) {
  const proto = el.tagName === "TEXTAREA"
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
  setter.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function doClick(cmd) {
  const el = findTarget(cmd.selector, cmd.text);
  if (!el) return { ok: false, error: "nothing to click: " + (cmd.selector || cmd.text || "") };
  try { el.scrollIntoView({ block: "center" }); } catch (e) { /* ignore */ }
  el.click();
  return { ok: true, data: { clicked: (el.innerText || el.value || el.tagName || "").trim().slice(0, 120) } };
}

function doType(cmd) {
  const el = findTarget(cmd.selector, cmd.text);
  if (!el) return { ok: false, error: "no field found: " + (cmd.selector || "") };
  if (!("value" in el)) return { ok: false, error: "element is not a text field" };
  el.focus();
  setFieldValue(el, cmd.text || "");
  return { ok: true, data: { typed: (cmd.text || "").length + " chars" } };
}

function doScroll(cmd) {
  if (cmd.selector) {
    const el = findTarget(cmd.selector, "");
    if (!el) return { ok: false, error: "nothing to scroll to: " + cmd.selector };
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    return { ok: true, data: { scrolledTo: cmd.selector } };
  }
  const dy = parseInt(cmd.text || "500", 10) || 500;
  window.scrollBy({ top: dy, behavior: "smooth" });
  return { ok: true, data: { scrolledBy: dy, scrollY: Math.round(window.scrollY) } };
}

function doRead() {
  const text = (document.body ? document.body.innerText : "") || "";
  return { ok: true, data: {
    title: document.title || "",
    url: location.href,
    text: text.slice(0, 4000),
  } };
}

function findLoginFields() {
  const user = document.querySelector(
    "input[type='email'], input[name*='user' i], input[name*='email' i], " +
    "input[name*='login' i], input[autocomplete='username'], " +
    "input[type='text']");
  const pass = document.querySelector(
    "input[type='password'], input[autocomplete='current-password']");
  return { user, pass };
}

function doLogin(cmd) {
  const creds = cmd.credentials || {};
  if (!creds.username || !creds.password) {
    return { ok: false,
      error: "no login saved — save a username and password in the " +
             "extension popup first (they stay in this browser, Mark " +
             "never sees them)" };
  }
  const { user, pass } = findLoginFields();
  if (!user || !pass) {
    return { ok: false, error: "no username/password fields found on this page" };
  }
  user.focus();
  setFieldValue(user, creds.username);
  pass.focus();
  setFieldValue(pass, creds.password);
  // Do NOT submit automatically: the user (or a later click command) presses
  // the login button, so a wrongly filled form is never sent by accident.
  return { ok: true, data: { filled: true, note: "fields filled — submit not pressed" } };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  try {
    const action = (msg.action || "").toLowerCase();
    let result;
    if (action === "click") result = doClick(msg);
    else if (action === "type") result = doType(msg);
    else if (action === "scroll") result = doScroll(msg);
    else if (action === "read") result = doRead();
    else if (action === "login") result = doLogin(msg);
    else result = { ok: false, error: "unknown action: " + (msg.action || "") };
    sendResponse(result);
  } catch (e) {
    sendResponse({ ok: false, error: String(e && e.message || e) });
  }
  return true; // async reply
});
