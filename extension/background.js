/**
 * Service worker.
 *
 * Two jobs:
 *
 *  1. Own the toolbar badge. The content script scans an email the moment it
 *     opens and reports a score here; this turns that into a coloured badge so
 *     the result is visible without the user clicking anything.
 *
 *  2. Provide a right-click "Scan selected text" option that works on any
 *     page. Google Docs renders its text to a canvas rather than the DOM, so
 *     an extension can't read a document reliably. Scanning a selection is the
 *     honest substitute, and it works everywhere rather than only in Gmail.
 *
 * Still no network calls. Scoring happens in the page, and results are held in
 * memory only, so nothing is written to disk.
 */

const BADGE_COLOR = {
  HIGH: "#D93025",
  MEDIUM: "#E08600",
  LOW: "#1E8E3E",
};

// tabId -> last result. In-memory only; cleared when the worker restarts.
const lastResult = new Map();

function setBadge(tabId, band, score) {
  if (tabId == null) return;
  chrome.action.setBadgeText({ tabId, text: String(score) });
  chrome.action.setBadgeBackgroundColor({
    tabId,
    color: BADGE_COLOR[band] || "#6A6A6A",
  });
  chrome.action.setTitle({
    tabId,
    title: `Phishing risk: ${band} (${score}/100). Click for details.`,
  });
}

function clearBadge(tabId) {
  if (tabId == null) return;
  chrome.action.setBadgeText({ tabId, text: "" });
  chrome.action.setTitle({ tabId, title: "Scan this email or a document" });
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const tabId = sender.tab && sender.tab.id;

  if (msg && msg.type === "AUTO_SCAN_RESULT") {
    lastResult.set(tabId, msg.result);
    setBadge(tabId, msg.result.band, msg.result.score);
    sendResponse({ ok: true });
    return true;
  }

  if (msg && msg.type === "AUTO_SCAN_CLEARED") {
    lastResult.delete(tabId);
    clearBadge(tabId);
    sendResponse({ ok: true });
    return true;
  }

  // The popup asks for whatever the content script last found, so opening it
  // doesn't have to re-scan.
  if (msg && msg.type === "GET_LAST_RESULT") {
    sendResponse(lastResult.get(msg.tabId) || null);
    return true;
  }

  return false;
});

chrome.tabs.onRemoved.addListener((tabId) => lastResult.delete(tabId));

// ---------------------------------------------------------------- context menu

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "scan-selection",
    title: "Scan selected text for phishing signals",
    contexts: ["selection"],
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "scan-selection" || !info.selectionText || !tab) return;
  try {
    // On Gmail and Outlook the detector is already present as a content
    // script. Injecting it again would redeclare its constants and throw, so
    // check first and only load what's missing.
    const [probe] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => ({
        hasDetector: typeof checkEmail === "function",
        hasToast: typeof window.__fraudScannerToast === "function",
      }),
    });

    const needed = [];
    if (!probe.result.hasDetector) needed.push("detector.js");
    if (!probe.result.hasToast) needed.push("toast.js");
    if (needed.length) {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: needed,
      });
    }

    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (text) => window.__fraudScannerToast(text),
      args: [info.selectionText],
    });
  } catch (err) {
    // Some pages (chrome:// URLs, the Web Store) don't allow injection.
    chrome.action.setTitle({
      tabId: tab.id,
      title: "Can't scan on this page.",
    });
  }
});
