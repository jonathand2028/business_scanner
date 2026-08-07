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

function firstMatch(selectors) {
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) return el;
  }
  return null;
}

function extractSubject() {
  const el = firstMatch(["h2.hP", "h2[data-thread-perm-id]", "[role='heading'] h2"]);
  return el ? el.innerText.trim() : "";
}

function extractSender() {
  // Gmail puts the address in an `email` attribute on the sender span.
  const el = firstMatch(["span.gD[email]", "span[email]", ".go span[email]"]);
  if (el) {
    const addr = el.getAttribute("email");
    if (addr) return addr.trim();
  }
  // Fall back to scraping an address out of the header text.
  const header = firstMatch([".gE.iv.gt", ".iw", ".gE"]);
  if (header) {
    const m = header.innerText.match(/[\w.+-]+@[\w.-]+\.\w+/);
    if (m) return m[0];
  }
  return "";
}

function extractBody() {
  // .a3s is the long-standing message-body container. Take the last one so a
  // reply thread yields the message actually on screen.
  const bodies = document.querySelectorAll("div.a3s, div[data-message-id] div.ii");
  if (bodies.length) return bodies[bodies.length - 1].innerText.trim();
  const fallback = firstMatch(["div[role='listitem']:last-of-type", "div.ii"]);
  return fallback ? fallback.innerText.trim() : "";
}

/** Links are read from href attributes, since Gmail often hides the real
 *  destination behind display text. The detector needs the real URLs. */
function extractLinks() {
  const scope = document.querySelector("div.a3s") || document;
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
