/**
 * Popup logic for both tabs.
 *
 * Email tab scans the message on screen the moment the popup opens.
 * Document tab reads a PDF locally, extracts metadata and (where possible) the
 * text layer, and runs the same cross-checks the web app runs.
 *
 * All scoring happens here in the browser. There is no network call anywhere
 * in this extension.
 */

const $ = (id) => document.getElementById(id);
const show = (id) => $(id).classList.remove("hidden");
const hide = (id) => $(id).classList.add("hidden");

// ----------------------------------------------------------------- tabs
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => {
      t.classList.toggle("active", t === tab);
      $(t.dataset.panel).classList.toggle("hidden", t !== tab);
    });
  });
});

// --------------------------------------------------------- shared render
function renderFindings(containerId, findings, emptyTitle, emptyBody) {
  const list = $(containerId);
  list.innerHTML = "";

  if (!findings.length) {
    const d = document.createElement("div");
    d.className = "finding";
    const t = document.createElement("div");
    t.className = "t";
    t.textContent = emptyTitle;
    const dd = document.createElement("div");
    dd.className = "d";
    dd.textContent = emptyBody;
    d.append(t, dd);
    list.appendChild(d);
    return;
  }

  const heading = document.createElement("div");
  heading.className = "count";
  heading.textContent = findings.length === 1
    ? "1 signal found" : `${findings.length} signals found`;
  list.appendChild(heading);

  for (const f of findings) {
    const d = document.createElement("div");
    d.className = "finding";
    const t = document.createElement("div");
    t.className = "t";
    const pill = document.createElement("span");
    pill.className = "pill " + f.level;
    pill.textContent = f.level;
    t.append(pill, document.createTextNode(f.title));
    const dd = document.createElement("div");
    dd.className = "d";
    dd.textContent = f.detail;
    d.append(t, dd);
    list.appendChild(d);
  }
}

function renderBand(prefix, score, bandInfo, metaLine) {
  $(prefix + "band").className = "band " + bandInfo.band;
  $(prefix + "band-label").textContent =
    `${bandInfo.band} — risk score ${score}/100`;
  $(prefix + "band-note").textContent = bandInfo.note;
  $(prefix + "band-meta").textContent = metaLine || "";
}

// ================================================================ EMAIL
function setStatus(msg, kind = "info") {
  const el = $("status");
  el.textContent = msg;
  el.className = "status " + kind;
  show("status");
}

function openManual(reason) {
  show("manual");
  if (reason) setStatus(reason, "warn");
  $("text").focus();
}

function renderEmail(result, meta = {}) {
  hide("status");
  const { findings, score } = result;
  renderBand("", score, riskBand(score), [
    meta.subject ? `“${meta.subject}”` : "",
    meta.sender ? `from ${meta.sender}` : "",
  ].filter(Boolean).join("  ·  "));
  renderFindings("findings", findings,
    "No phishing signals detected",
    "None of the seven checks fired. Still be cautious with unexpected "
    + "requests — this is a decision aid, not a guarantee.");
  show("result");
  show("rescan");
}

async function scanOpenEmail({ silent = false } = {}) {
  hide("result"); hide("rescan");
  if (!silent) setStatus("Reading the open email…");

  let tab;
  try {
    [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  } catch {
    openManual("Couldn't read the current tab. Paste the email instead.");
    return;
  }
  if (!tab || !/^https:\/\/mail\.google\.com\//.test(tab.url || "")) {
    openManual("You're not on Gmail. Paste an email below to scan it.");
    return;
  }

  let data;
  try {
    data = await chrome.tabs.sendMessage(tab.id, { type: "EXTRACT_EMAIL" });
  } catch {
    openManual("Couldn't reach the Gmail page — reload the tab and try again, "
      + "or paste the email below.");
    return;
  }
  if (!data || !data.ok || !(data.text || "").trim()) {
    openManual("No open email found. Open a message in Gmail, or paste one below.");
    return;
  }

  renderEmail(checkEmail(data.text, data.sender),
              { sender: data.sender, subject: data.subject });
}

function scanPastedEmail() {
  const text = $("text").value;
  if (!text.trim()) { setStatus("Paste some email text first.", "warn"); return; }
  renderEmail(checkEmail(text, $("sender").value.trim()),
              { sender: $("sender").value.trim() });
}

$("rescan").addEventListener("click", () => scanOpenEmail());
$("scan-manual").addEventListener("click", scanPastedEmail);
$("toggle-manual").addEventListener("click", () =>
  $("manual").classList.toggle("hidden"));
$("text").addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") scanPastedEmail();
});

// ============================================================= DOCUMENT
function docStatus(msg, kind = "info") {
  const el = $("doc-status");
  el.textContent = msg;
  el.className = "status " + kind;
  show("doc-status");
}

function vendorList() {
  return $("vendors").value.split(",").map((s) => s.trim()).filter(Boolean);
}

function renderDoc(result, parsed, meta = {}) {
  const { findings, score } = result;
  renderBand("doc-", score, documentRiskBand(score), meta.filename || "");
  renderFindings("doc-findings", findings,
    "No inconsistencies found",
    "The printed dates, the file metadata, and your vendor list all agree. "
    + "This is a decision aid, not proof the document is genuine.");

  // What we actually managed to read — so a clean result can be judged in context
  const bits = [];
  if (parsed) {
    const m = parsed.metadata || {};
    bits.push(`<b>Metadata:</b> `
      + (m.has_metadata
          ? [m.creation_date ? `created ${m.creation_date}` : null,
             m.mod_date ? `modified ${m.mod_date}` : null,
             m.software ? `software “${m.software}”` : null]
            .filter(Boolean).join(" · ") || "present"
          : "none found"));
    bits.push(`<b>Text layer:</b> `
      + (parsed.textExtracted
          ? `${parsed.text.length.toLocaleString()} characters read`
          : "not readable"));
    if (parsed.note) bits.push(parsed.note);
  } else {
    bits.push("<b>Pasted text only</b> — no file metadata, so the "
      + "metadata-based checks did not run.");
  }
  $("doc-extract").innerHTML = bits.join("<br>");

  hide("doc-status");
  show("doc-result");
}

async function scanFile(file) {
  hide("doc-result");
  docStatus(`Reading ${file.name}…`);
  try {
    const parsed = await readFile(file);
    if (parsed.kind === "unknown") { docStatus(parsed.note, "warn"); return; }
    const result = evaluateDocument(parsed.text, parsed.metadata,
                                    vendorList(), true);
    renderDoc(result, parsed, { filename: file.name });
    if (!parsed.textExtracted) show("doc-manual");
  } catch (err) {
    docStatus("Couldn't read that file. Try pasting the text instead.", "warn");
  }
}

function scanPastedDoc() {
  const text = $("doc-text").value;
  if (!text.trim()) { docStatus("Paste some document text first.", "warn"); return; }
  hide("doc-result");
  renderDoc(evaluateDocument(text, { has_metadata: true }, vendorList(), true),
            null, {});
}

$("drop").addEventListener("click", () => $("file").click());
$("file").addEventListener("change", (e) => {
  if (e.target.files && e.target.files[0]) scanFile(e.target.files[0]);
});
["dragenter", "dragover"].forEach((ev) =>
  $("drop").addEventListener(ev, (e) => {
    e.preventDefault(); $("drop").classList.add("over");
  }));
["dragleave", "drop"].forEach((ev) =>
  $("drop").addEventListener(ev, (e) => {
    e.preventDefault(); $("drop").classList.remove("over");
  }));
$("drop").addEventListener("drop", (e) => {
  const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
  if (f) scanFile(f);
});
$("doc-toggle-manual").addEventListener("click", () =>
  $("doc-manual").classList.toggle("hidden"));
$("doc-scan-manual").addEventListener("click", scanPastedDoc);
$("doc-text").addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") scanPastedDoc();
});

// Scan whatever email is on screen the moment the popup opens.
scanOpenEmail();
