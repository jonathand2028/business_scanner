/**
 * Content script: pulls the currently open email out of the Gmail page.
 *
 * Gmail's DOM is obfuscated and its class names change without notice, so
 * every selector here is treated as unreliable. Each field tries several
 * selectors and falls back rather than throwing, and the popup always offers
 * manual paste so a broken selector degrades the tool instead of breaking it.
 *
 * Nothing is sent anywhere. The extracted text is handed to the popup, which
 * scores it locally.
 */

const PROVIDER = /mail\.google\.com$/.test(location.hostname) ? "gmail" : "outlook";

/**
 * Selectors per provider. Both webmail clients use obfuscated, generated class
 * names that change without notice, so each field lists several candidates and
 * degrades to the paste box rather than throwing.
 */
const SEL = {
  gmail: {
    subject: ["h2.hP", "h2[data-thread-perm-id]", "[role='heading'] h2"],
    senderAttr: ["span.gD[email]", "span[email]", ".go span[email]"],
    senderText: [".gE.iv.gt", ".iw", ".gE"],
    body: ["div.a3s", "div[data-message-id] div.ii"],
    bodyFallback: ["div[role='listitem']:last-of-type", "div.ii"],
    container: "div[data-message-id], div[role='listitem'], .gs, .h7",
  },
  outlook: {
    subject: [
      "div[role='heading'][aria-level='2']",
      "span[class*='subjectLine']",
      "div[aria-label='Message subject']",
      "h1[role='heading']",
    ],
    senderAttr: [],
    senderText: [
      "span[class*='SenderPersona']",
      "div[aria-label*='From']",
      "span[title*='@']",
      "div[role='heading'] + div",
    ],
    body: [
      "div[aria-label='Message body']",
      "div.allowTextSelection",
      "div[role='document']",
    ],
    bodyFallback: ["div[class*='ReadingPane']", "div[role='main']"],
    container: "div[class*='ReadingPane'], div[role='main'], div[aria-label='Reading Pane']",
  },
}[PROVIDER];

function firstMatch(selectors) {
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) return el;
  }
  return null;
}

/** The body element of the message actually on screen (last, not first). */
function bodyElement() {
  const bodies = document.querySelectorAll(SEL.body.join(", "));
  if (bodies.length) return bodies[bodies.length - 1];
  return firstMatch(SEL.bodyFallback);
}

/**
 * The container holding the open message.
 *
 * This matters more than it looks. Querying the document for a sender returns
 * whichever address appears first in the DOM, which in Gmail is the top of the
 * thread list rather than the message you opened — so every email reported the
 * same sender while the score changed underneath it. Everything is now scoped
 * to the container around the body element, so the sender always belongs to
 * the message being scored.
 */
function messageContainer() {
  const body = bodyElement();
  if (!body) return null;
  return body.closest(SEL.container) || body.parentElement || null;
}

function extractSubject() {
  const el = firstMatch(SEL.subject);
  return el ? el.textContent.trim().replace(/\s+/g, " ").slice(0, 300) : "";
}

function extractSender() {
  const scope = messageContainer() || document;

  // Gmail exposes the address in an `email` attribute; Outlook doesn't.
  for (const sel of SEL.senderAttr) {
    const el = scope.querySelector(sel);
    const addr = el && el.getAttribute("email");
    if (addr) return addr.trim();
  }

  // Otherwise scrape an address out of the header area of this message.
  for (const sel of SEL.senderText) {
    const el = scope.querySelector(sel);
    if (!el) continue;
    const m = (el.getAttribute("title") || el.textContent || "")
      .match(/[\w.+-]+@[\w.-]+\.\w+/);
    if (m) return m[0];
  }

  // Last resort: any address in the container that isn't the user's own.
  const m = (scope.textContent || "").match(/[\w.+-]+@[\w.-]+\.\w+/);
  return m ? m[0] : "";
}

function extractBody() {
  const el = bodyElement();
  return el ? el.innerText.trim() : "";
}

/** Links are read from href attributes, since webmail routinely hides the real
 *  destination behind display text. The detector needs the actual URLs. */
function extractLinks() {
  const scope = bodyElement() || document;
  return [...scope.querySelectorAll("a[href^='http']")]
    .map((a) => a.getAttribute("href"))
    .filter(Boolean)
    .slice(0, 40);
}

function extractEmail() {
  const subject = extractSubject();
  const sender = extractSender();
  const body = extractBody();
  const links = extractLinks();

  // Append hrefs so the detector sees destinations the reader can't.
  const text = [subject, body, links.join("\n")].filter(Boolean).join("\n\n");

  return {
    ok: Boolean(body || subject),
    subject,
    sender,
    body,
    links,
    text,
  };
}

try {
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg && msg.type === "EXTRACT_EMAIL") {
      try {
        sendResponse(extractEmail());
      } catch (err) {
        sendResponse({ ok: false, error: String(err) });
      }
    }
    return true;
  });
} catch {
  // Orphaned content script from a previous version of the extension.
}

// ----------------------------------------------------------------------
// Auto-scan
//
// Gmail and Outlook are single-page apps, so opening a message never reloads
// anything. A cheap polled signature check detects when the open message
// changes; the expensive extraction only runs when it has.
//
// Scoring happens here, in the page. Only the resulting number and band go to
// the service worker, which turns them into a toolbar badge. The email text
// never leaves this script.
// ----------------------------------------------------------------------

let lastSignature = null;
let pollTimer = null;

/**
 * Reloading or updating the extension orphans any content script already
 * running in an open tab: chrome.runtime stops working and every call throws
 * "Extension context invalidated". Since this script polls on a timer, that
 * would otherwise throw every 1.2 seconds forever until the page is reloaded.
 *
 * So every message is guarded, and the first sign of invalidation shuts this
 * instance down cleanly. The new content script takes over on next page load.
 */
function contextAlive() {
  try {
    return Boolean(chrome.runtime && chrome.runtime.id);
  } catch {
    return false;
  }
}

function shutdown() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  try {
    if (window.__fraudScannerHide) window.__fraudScannerHide();
  } catch { /* page may be tearing down */ }
}

function safeSend(message) {
  if (!contextAlive()) {
    shutdown();
    return;
  }
  try {
    chrome.runtime.sendMessage(message, () => void chrome.runtime.lastError);
  } catch {
    shutdown();
  }
}

/**
 * Cheap change check.
 *
 * The first version of this used a MutationObserver on document.body. That was
 * a mistake: Gmail and Outlook fire thousands of mutations a second, and the
 * extraction path uses innerText, which forces a layout reflow. The result was
 * a visibly sluggish page.
 *
 * This instead polls a signature built from textContent and the URL. Unlike
 * innerText, textContent doesn't trigger reflow, so the check costs almost
 * nothing, and the expensive extraction only runs when something actually
 * changed.
 */
function signature() {
  const subj = document.querySelector(SEL.subject.join(", "));
  const body = document.querySelector(SEL.body.join(", "));
  return [
    location.href,
    subj ? subj.textContent.slice(0, 120) : "",
    body ? body.textContent.length : 0,
  ].join("|");
}

function autoScan() {
  let data;
  try {
    data = extractEmail();
  } catch {
    return;
  }

  if (!data.ok || !(data.text || "").trim()) {
    safeSend({ type: "AUTO_SCAN_CLEARED" });
    return;
  }

  const { findings, score } = checkEmail(data.text, data.sender);
  const { band, note } = riskBand(score);
  const result = {
    score, band, note, findings,
    subject: data.subject,
    sender: data.sender,
    key: lastSignature,
  };

  safeSend({ type: "AUTO_SCAN_RESULT", result });

  // Show the reasons in the page when there's something worth flagging, so the
  // common case needs no clicks. A clean email just gets a green badge —
  // a panel on every message would be noise and get ignored.
  if (band === "LOW") {
    window.__fraudScannerHide && window.__fraudScannerHide();
  } else if (window.__fraudScannerShow) {
    window.__fraudScannerShow(result);
  }
}

function tick() {
  if (!contextAlive()) { shutdown(); return; }
  if (document.hidden) return;          // don't work in a background tab
  let sig;
  try {
    sig = signature();
  } catch {
    return;
  }
  if (sig === lastSignature) return;
  lastSignature = sig;
  autoScan();
}

pollTimer = setInterval(tick, 1200);

// Both clients use hash routing, so react immediately when the URL changes
// rather than waiting up to a second for the next tick.
window.addEventListener("hashchange", () => setTimeout(tick, 250));
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) tick();
});

setTimeout(tick, 800);
