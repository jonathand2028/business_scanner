/**
 * Document fraud detection — JavaScript port of evaluate() from app.py.
 *
 * Same premise as the Python version: a forger has to keep every layer of a
 * document consistent, and usually can't. This cross-checks the printed text
 * against the file's hidden metadata and against a list of approved vendors.
 *
 * Kept in lockstep with the Python implementation by extension/test — the
 * parity test asserts identical scores and findings across the same labeled
 * dataset the web app is evaluated on.
 *
 * Runs in the browser and under Node.
 */

const EDITOR_SOFTWARE = [
  "photoshop", "gimp", "canva", "illustrator", "affinity", "pixelmator",
  "paint.net", "inkscape", "snapseed", "lightroom", "coreldraw",
  "figma", "sketch", "preview",
];

const DATE_GAP_DAYS = 30;

const MONTHS = {
  january: 1, february: 2, march: 3, april: 4, may: 5, june: 6,
  july: 7, august: 8, september: 9, october: 10, november: 11,
  december: 12, jan: 1, feb: 2, mar: 3, apr: 4, jun: 6, jul: 7,
  aug: 8, sep: 9, sept: 9, oct: 10, nov: 11, dec: 12,
};

const DAY_MS = 86400000;

/** Build a UTC date, returning null when the components aren't a real date
 *  (matching Python's datetime() ValueError behaviour). */
function makeDate(y, mo, d) {
  if (!(mo >= 1 && mo <= 12) || !(d >= 1 && d <= 31)) return null;
  const dt = new Date(Date.UTC(y, mo - 1, d));
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1
      || dt.getUTCDate() !== d) return null;
  return dt;
}

/** Port of find_dates(). Returns [{raw, date}] */
function findDates(text) {
  const found = [];
  if (!text) return found;
  const add = (raw, y, mo, d) => {
    const dt = makeDate(y, mo, d);
    if (dt) found.push({ raw, date: dt });
  };

  // ISO: 2026-01-15
  for (const m of text.matchAll(/\b(\d{4})-(\d{1,2})-(\d{1,2})\b/g)) {
    add(m[0], +m[1], +m[2], +m[3]);
  }

  // Numeric slashes: 01/15/2026 or 15/01/2026 (month-first, fall back)
  for (const m of text.matchAll(/\b(\d{1,2})\/(\d{1,2})\/(\d{2,4})\b/g)) {
    const a = +m[1], b = +m[2];
    let y = +m[3];
    if (y < 100) y += 2000;
    const mo = a <= 12 ? a : b;
    const d = a <= 12 ? b : a;
    add(m[0], y, mo, d);
  }

  // "Month DD, YYYY" or "Month YYYY"
  for (const m of text.matchAll(
    /\b([A-Za-z]{3,9})\.?\s+(?:(\d{1,2})(?:st|nd|rd|th)?,?\s+)?(\d{4})\b/g)) {
    const name = m[1].toLowerCase();
    if (name in MONTHS) add(m[0], +m[3], MONTHS[name], m[2] ? +m[2] : 1);
  }

  // "DD Month YYYY"
  for (const m of text.matchAll(/\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})\b/g)) {
    const name = m[2].toLowerCase();
    if (name in MONTHS) add(m[0], +m[3], MONTHS[name], +m[1]);
  }

  return found;
}

/** Port of parse_metadata_date(). Returns Date or null. */
function parseMetadataDate(value) {
  if (!value) return null;
  const s = String(value).trim();
  let m = s.match(/^D?:?(\d{4})(\d{2})(\d{2})/);
  if (m) return makeDate(+m[1], +m[2], +m[3]);
  m = s.match(/^(\d{4})[:\-](\d{2})[:\-](\d{2})/);
  if (m) return makeDate(+m[1], +m[2], +m[3]);
  return null;
}

function softwareIsEditor(software) {
  if (!software) return false;
  const s = String(software).toLowerCase();
  return EDITOR_SOFTWARE.some((n) => s.includes(n));
}

const dayDiff = (a, b) => Math.floor((a - b) / DAY_MS);
const isoDate = (d) => d.toISOString().slice(0, 10);

/**
 * Port of evaluate().
 * @param {string} text
 * @param {object} metadata {creation_date, mod_date, software, has_metadata}
 * @param {string[]} approvedVendors
 * @param {boolean} claimsToBeOriginal
 * @returns {{findings: Array, score: number}}
 */
function evaluateDocument(text, metadata = {}, approvedVendors = null,
                          claimsToBeOriginal = true) {
  const findings = [];
  let score = 0;

  const docDates = findDates(text).map((d) => d.date);
  const metaCreate = parseMetadataDate(metadata.creation_date);
  const metaMod = parseMetadataDate(metadata.mod_date);
  const software = metadata.software;

  const minDate = (ds) => new Date(Math.min(...ds.map((d) => d.getTime())));
  const maxDate = (ds) => new Date(Math.max(...ds.map((d) => d.getTime())));

  // 1. Printed date vs. real file creation date
  if (docDates.length && metaCreate) {
    const earliest = minDate(docDates);
    const gap = dayDiff(metaCreate, earliest);
    if (gap > DATE_GAP_DAYS) {
      score += 35;
      findings.push({
        level: "high",
        title: "Printed date is older than the file itself",
        detail: `The document shows a date of ${isoDate(earliest)}, but the `
          + `file was actually created on ${isoDate(metaCreate)} (${gap} days `
          + `later). A genuine document is normally created on or near its `
          + `printed date.`,
      });
    }
  }

  // 1b. Dated after the file was created
  if (docDates.length && metaCreate) {
    const earliest = minDate(docDates);
    const ahead = dayDiff(earliest, metaCreate);
    if (ahead > 1) {
      score += 20;
      findings.push({
        level: "medium",
        title: "Dated after the file was created",
        detail: `The document is dated ${isoDate(earliest)}, but the file was `
          + `created earlier, on ${isoDate(metaCreate)}. A future-dated invoice `
          + `can be a sign of a fabricated record.`,
      });
    }
  }

  // 2. Editing software on a supposed original
  if (claimsToBeOriginal && softwareIsEditor(software)) {
    score += 30;
    findings.push({
      level: "high",
      title: "Edited in image/graphics software",
      detail: `The file reports it was produced or last saved with `
        + `'${software}'. An untouched original (a real system export or `
        + `camera photo) would not normally pass through an editor.`,
    });
  }

  // 3. Created and modified at clearly different times
  if (metaCreate && metaMod) {
    const moddiff = dayDiff(metaMod, metaCreate);
    if (moddiff > 1) {
      score += 15;
      findings.push({
        level: "medium",
        title: "Modified after it was created",
        detail: `Created ${isoDate(metaCreate)} but last modified `
          + `${isoDate(metaMod)}. Worth checking what changed.`,
      });
    }
  }

  // 4. Missing / stripped metadata
  if (metadata.has_metadata === false) {
    score += 20;
    findings.push({
      level: "medium",
      title: "Hidden file data is missing",
      detail: "This file has little or no metadata. That can be innocent, but "
        + "fraudsters often strip it to hide where a file really came from, so "
        + "treat a 'clean' file with mild suspicion.",
    });
  }

  // 5. Vendor not on the approved list
  if (approvedVendors && approvedVendors.length) {
    const vendors = approvedVendors.map((v) => v.trim().toLowerCase())
      .filter(Boolean);
    if (vendors.length && text) {
      const low = text.toLowerCase();
      if (!vendors.some((v) => low.includes(v))) {
        score += 25;
        findings.push({
          level: "medium",
          title: "No approved vendor found in the document",
          detail: "None of your approved vendor names appear in this document. "
            + "If this is supposed to be from a known supplier, that is a problem.",
        });
      }
    }
  }

  // 6. Conflicting dates inside the document
  if (docDates.length >= 2) {
    const spread = dayDiff(maxDate(docDates), minDate(docDates));
    if (spread > 365 * 2) {
      score += 10;
      findings.push({
        level: "low",
        title: "Dates inside the document are far apart",
        detail: `The document mentions dates spanning ${spread} days, which can `
          + `indicate copy-paste from another file.`,
      });
    }
  }

  return { findings, score: Math.min(score, 100) };
}

/** Port of risk_band() for documents. */
function documentRiskBand(score) {
  if (score >= 50) return { band: "HIGH", note: "Likely fraud - review before trusting" };
  if (score >= 20) return { band: "MEDIUM", note: "Some inconsistencies - worth a human check" };
  return { band: "LOW", note: "No strong inconsistencies found" };
}

/** Port of find_invoice_number(). */
function findInvoiceNumber(text) {
  const m = (text || "").match(
    /invoice\s*(?:#|no\.?|number)\s*:?\s*([A-Za-z0-9][A-Za-z0-9\-/]{3,})/i);
  return m ? m[1].trim() : null;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    evaluateDocument, documentRiskBand, findDates, parseMetadataDate,
    softwareIsEditor, findInvoiceNumber,
  };
}
