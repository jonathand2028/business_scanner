/**
 * Popup logic.
 *
 * On open it tries to scan the email already on screen, so the common case is
 * zero clicks. If that isn't possible — not on Gmail, no message open, or
 * Gmail's DOM changed — it falls back to a paste box and says why.
 *
 * All scoring happens here in the browser. There is no network call anywhere
 * in this extension.
 */

const $ = (id) => document.getElementById(id);

function show(id) { $(id).classList.remove("hidden"); }
function hide(id) { $(id).classList.add("hidden"); }

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

function render(result, meta = {}) {
  const { findings, score } = result;
  const { band, note } = riskBand(score);

  hide("status");

  $("band").className = "band " + band;
  $("band-label").textContent = `${band} — risk score ${score}/100`;
  $("band-note").textContent = note;
  $("band-meta").textContent = [
    meta.subject ? `“${meta.subject}”` : "",
    meta.sender ? `from ${meta.sender}` : "",
  ].filter(Boolean).join("  ·  ");

  const list = $("findings");
  list.innerHTML = "";

  if (!findings.length) {
    const d = document.createElement("div");
    d.className = "finding";
    d.innerHTML = '<div class="t">No phishing signals detected</div>'
      + '<div class="d">None of the seven checks fired. Still be cautious '
      + 'with unexpected requests — this is a decision aid, not a guarantee.'
      + '</div>';
    list.appendChild(d);
  } else {
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
      t.appendChild(pill);
      t.appendChild(document.createTextNode(f.title));
      const dd = document.createElement("div");
      dd.className = "d";
      dd.textContent = f.detail;
      d.appendChild(t);
      d.appendChild(dd);
      list.appendChild(d);
    }
  }

  show("result");
  show("rescan");
}

async function scanOpenEmail({ silent = false } = {}) {
  hide("result");
  hide("rescan");
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

  render(checkEmail(data.text, data.sender),
         { sender: data.sender, subject: data.subject });
}

function scanPasted() {
  const text = $("text").value;
  if (!text.trim()) {
    setStatus("Paste some email text first.", "warn");
    return;
  }
  render(checkEmail(text, $("sender").value.trim()),
         { sender: $("sender").value.trim() });
}

$("rescan").addEventListener("click", () => scanOpenEmail());
$("scan-manual").addEventListener("click", scanPasted);
$("toggle-manual").addEventListener("click", () => {
  $("manual").classList.toggle("hidden");
});
$("text").addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") scanPasted();
});

// Scan whatever is on screen the moment the popup opens.
scanOpenEmail();
