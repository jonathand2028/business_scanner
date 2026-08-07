/**
 * Phishing detection — JavaScript port of check_email() from app.py.
 *
 * This is a deliberate second implementation of logic that already exists in
 * Python. The reason is privacy: the extension reads people's email, so the
 * detection has to run inside the browser rather than being sent to a server.
 *
 * Because there are now two implementations, they can drift apart. test/ runs
 * both against the same labeled cases and asserts the scores match exactly,
 * so drift is caught rather than discovered later.
 *
 * Works in the browser and under Node (for the tests).
 */

const URGENCY = [
  "urgent", "immediately", "act now", "final notice", "within 24 hours",
  "suspended", "verify your account", "confirm your account",
  "account has been", "limited time", "expire", "last warning",
  "as soon as possible", "failure to", "avoid suspension",
];

const SENSITIVE = [
  "password", "log in", "login", "ssn", "social security",
  "bank account", "routing number", "wire transfer", "gift card",
  "credit card", "cvv", "one-time code", "verification code",
  "seed phrase", "update your payment", "confirm your payment",
];

const GENERIC = [
  "dear customer", "dear user", "dear account holder",
  "valued customer", "dear sir/madam", "dear member",
];

const SHORTENERS = [
  "bit.ly", "tinyurl", "t.co", "goo.gl", "ow.ly", "is.gd",
  "buff.ly", "rebrand.ly", "cutt.ly",
];

const URL_RE = /https?:\/\/[^\s<>"')]+/gi;
const IP_URL_RE = /https?:\/\/\d{1,3}(?:\.\d{1,3}){3}/i;
const LINK_DOMAIN_RE = /https?:\/\/([^/]+)\/?/;

/** Matches Python's `sorted({w for w in LIST if w in low})` */
function matchedTerms(list, low) {
  return [...new Set(list.filter((w) => low.includes(w)))].sort();
}

/**
 * @param {string} text   full email text (subject + body)
 * @param {string} sender sender address, optional
 * @returns {{findings: Array, score: number}}
 */
function checkEmail(text, sender = "") {
  const findings = [];
  let score = 0;
  const low = (text || "").toLowerCase();

  const urgency = matchedTerms(URGENCY, low);
  if (urgency.length) {
    score += 22;
    findings.push({
      level: "medium",
      title: "Pressure / urgency language",
      detail: "Phrases pushing you to act fast: " + urgency.join(", ") + ".",
    });
  }

  const sensitive = matchedTerms(SENSITIVE, low);
  if (sensitive.length) {
    score += 28;
    findings.push({
      level: "high",
      title: "Asks for credentials or payment",
      detail: "Legitimate companies rarely ask for these by email: "
        + sensitive.join(", ") + ".",
    });
  }

  const urls = (text || "").match(URL_RE) || [];
  const ipUrls = urls.filter((u) => IP_URL_RE.test(u));
  const shortened = urls.filter((u) =>
    SHORTENERS.some((s) => u.toLowerCase().includes(s)));
  const httpUrls = urls.filter((u) => u.toLowerCase().startsWith("http://"));

  if (ipUrls.length) {
    score += 28;
    findings.push({
      level: "high",
      title: "Link points to a raw IP address",
      detail: "Real companies use domain names, not numeric IPs: "
        + ipUrls.slice(0, 3).join(", ") + ".",
    });
  }
  if (shortened.length) {
    score += 16;
    findings.push({
      level: "medium",
      title: "Shortened / hidden links",
      detail: "Shortened links hide their true destination: "
        + shortened.slice(0, 3).join(", ") + ".",
    });
  }
  if (httpUrls.length) {
    score += 10;
    findings.push({
      level: "low",
      title: "Insecure (http) link",
      detail: "Links use http, not https: "
        + httpUrls.slice(0, 3).join(", ") + ".",
    });
  }

  if (GENERIC.some((g) => low.includes(g))) {
    score += 8;
    findings.push({
      level: "low",
      title: "Generic greeting",
      detail: "A vague greeting like 'Dear customer' suggests a mass send, "
        + "not a real relationship.",
    });
  }

  // Sender domain vs. link domains
  if (sender && sender.includes("@") && urls.length) {
    const sdom = sender.split("@").pop().trim().toLowerCase().replace(/>+$/, "");
    const linkDoms = new Set();
    for (const u of urls) {
      const m = u.toLowerCase().match(LINK_DOMAIN_RE);
      if (m) linkDoms.add(m[1].split(":")[0]);
    }
    if (sdom && linkDoms.size
        && [...linkDoms].every((d) => !d.includes(sdom) && !sdom.includes(d))) {
      score += 12;
      findings.push({
        level: "medium",
        title: "Links do not match the sender",
        detail: `The sender is @${sdom} but the links point elsewhere, `
          + "a common spoofing sign.",
      });
    }
  }

  return { findings, score: Math.min(score, 100) };
}

/** Matches risk_band() in app.py */
function riskBand(score) {
  if (score >= 50) return { band: "HIGH", note: "Likely phishing - do not click links" };
  if (score >= 20) return { band: "MEDIUM", note: "Some warning signs - treat with care" };
  return { band: "LOW", note: "No strong phishing signals found" };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { checkEmail, riskBand };
}
