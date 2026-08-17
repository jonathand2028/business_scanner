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
    linkScope: "div.a3s",
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
    linkScope: "div[aria-label='Message body']",
  },
}[PROVIDER];

function firstMatch(selectors) {
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) return el;
  }
  return null;
}

function extractSubject() {
  const el = firstMatch(SEL.subject);
  return el ? el.innerText.trim().slice(0, 300) : "";
}

function extractSender() {
  // Gmail exposes the address in an `email` attribute; Outlook doesn't.
  for (const sel of SEL.senderAttr) {
    const el = document.querySelector(sel);
    const addr = el && el.getAttribute("email");
    if (addr) return addr.trim();
  }
  // Otherwise scrape an address out of the header area.
  const header = firstMatch(SEL.senderText);
  if (header) {
    const m = (header.getAttribute("title") || header.innerText || "")
      .match(/[\w.+-]+@[\w.-]+\.\w+/);
    if (m) return m[0];
  }
  return "";
}

function extractBody() {
  // Take the last match so a reply thread yields the message on screen.
  const bodies = document.querySelectorAll(SEL.body.join(", "));
  if (bodies.length) return bodies[bodies.length - 1].innerText.trim();
  const fallback = firstMatch(SEL.bodyFallback);
  return fallback ? fallback.innerText.trim() : "";
}

/** Links are read from href attributes, since webmail routinely hides the real
 *  destination behind display text. The detector needs the actual URLs. */
function extractLinks() {
  const scope = document.querySelector(SEL.linkScope) || document;
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
    chrome.runtime.sendMessage({ type: "AUTO_SCAN_CLEARED" },
                               () => void chrome.runtime.lastError);
    return;
  }

  const { findings, score } = checkEmail(data.text, data.sender);
  const { band, note } = riskBand(score);

  chrome.runtime.sendMessage({
    type: "AUTO_SCAN_RESULT",
    result: {
      score, band, note, findings,
      subject: data.subject,
      sender: data.sender,
    },
  }, () => void chrome.runtime.lastError);
}

function tick() {
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

setInterval(tick, 1200);

// Both clients use hash routing, so react immediately when the URL changes
// rather than waiting up to a second for the next tick.
window.addEventListener("hashchange", () => setTimeout(tick, 250));
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) tick();
});

setTimeout(tick, 800);
