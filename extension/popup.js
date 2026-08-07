/**
 * Popup logic: gets the email (from the page or from a paste), scores it with
 * detector.js, and renders the result. All scoring happens here in the
 * browser — there is no network call anywhere in this extension.
 */

const $ = (id) => document.getElementById(id);

function showError(msg) {
  const el = $("error");
  el.textContent = msg;
  el.classList.remove("hidden");
}

function clearError() {
  $("error").classList.add("hidden");
}

function render(result, meta = {}) {
  const { findings, score } = result;
  const { band, note } = riskBand(score);

  const bandEl = $("band");
  bandEl.className = "band " + band;
  $("band-label").textContent = `${band} — risk score ${score}/100`;
  $("band-note").textContent = note;
  $("band-meta").textContent = meta.sender
    ? `Sender: ${meta.sender}`
    : "";

  const list = $("findings");
  list.innerHTML = "";

  if (!findings.length) {
    const d = document.createElement("div");
    d.className = "finding";
    d.innerHTML = '<div class="t">No phishing signals detected</div>'
      + '<div class="d">None of the checks fired. Stay cautious with '
      + 'unexpected requests regardless.</div>';
    list.appendChild(d);
  } else {
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

  $("result").classList.remove("hidden");
}

async function scanOpenEmail() {
  clearError();
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !/^https:\/\/mail\.google\.com\//.test(tab.url || "")) {
      showError("Open an email in Gmail first, or use the paste option below.");
      return;
    }

    const data = await chrome.tabs.sendMessage(tab.id, { type: "EXTRACT_EMAIL" });
    if (!data || !data.ok || !data.text.trim()) {
      showError("Couldn't read the open email. Gmail's layout may have changed — "
        + "use the paste option below.");
      return;
    }

    render(checkEmail(data.text, data.sender), { sender: data.sender });
  } catch (err) {
    showError("Couldn't reach the page. Reload Gmail and try again, or paste "
      + "the email below.");
  }
}

function scanPasted() {
  clearError();
  const text = $("text").value;
  if (!text.trim()) {
    showError("Paste some email text first.");
    return;
  }
  render(checkEmail(text, $("sender").value.trim()),
         { sender: $("sender").value.trim() });
}

$("scan").addEventListener("click", scanOpenEmail);
$("scan-manual").addEventListener("click", scanPasted);
$("toggle-manual").addEventListener("click", () => {
  $("manual").classList.toggle("hidden");
});
