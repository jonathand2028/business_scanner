/**
 * Floating result panel, injected on demand for the right-click scan.
 *
 * Deliberately does not touch chrome.storage or the network. It scores the
 * selected text in the page, shows the result, and disappears.
 */

window.__fraudScannerToast = function (text) {
  const existing = document.getElementById("__fraud-scanner-toast");
  if (existing) existing.remove();

  const { findings, score } = checkEmail(text, "");
  const { band, note } = riskBand(score);

  const colors = {
    HIGH: ["#D93025", "#FDF3F2"],
    MEDIUM: ["#E08600", "#FDF8EF"],
    LOW: ["#1E8E3E", "#F2F9F4"],
  };
  const [accent, bg] = colors[band];

  const box = document.createElement("div");
  box.id = "__fraud-scanner-toast";
  box.style.cssText = [
    "position:fixed", "top:16px", "right:16px", "z-index:2147483647",
    "width:340px", "max-height:70vh", "overflow-y:auto",
    "background:#fff", "border:1px solid #E6E6E6",
    `border-left:4px solid ${accent}`,
    "border-radius:8px", "box-shadow:0 6px 24px rgba(0,0,0,.18)",
    "padding:14px 16px",
    "font:13px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif",
    "color:#1A1A1A",
  ].join(";");

  const close = document.createElement("button");
  close.textContent = "×";
  close.style.cssText = [
    "position:absolute", "top:8px", "right:10px", "border:0",
    "background:none", "font-size:20px", "line-height:1",
    "color:#8A8A8A", "cursor:pointer", "padding:0",
  ].join(";");
  close.addEventListener("click", () => box.remove());

  const head = document.createElement("div");
  head.style.cssText = `background:${bg};margin:-14px -16px 10px;padding:12px 16px;border-radius:4px 4px 0 0`;
  const title = document.createElement("div");
  title.textContent = `${band} — risk score ${score}/100`;
  title.style.cssText = `font-weight:700;font-size:14px;color:${accent}`;
  const sub = document.createElement("div");
  sub.textContent = note;
  sub.style.cssText = "font-size:11.5px;color:#6A6A6A;margin-top:1px";
  head.append(title, sub);

  const list = document.createElement("div");
  if (!findings.length) {
    const d = document.createElement("div");
    d.textContent = "No phishing signals found in the selected text.";
    d.style.cssText = "font-size:12px;color:#6A6A6A";
    list.appendChild(d);
  } else {
    for (const f of findings) {
      const row = document.createElement("div");
      row.style.cssText = "padding:8px 0;border-top:1px solid #EEE";
      const t = document.createElement("div");
      t.textContent = f.title;
      t.style.cssText = "font-weight:600;font-size:12.5px";
      const d = document.createElement("div");
      d.textContent = f.detail;
      d.style.cssText = "font-size:11.5px;color:#6A6A6A;margin-top:2px;word-break:break-word";
      row.append(t, d);
      list.appendChild(row);
    }
  }

  const foot = document.createElement("div");
  foot.textContent = "Scanned locally. Nothing was uploaded.";
  foot.style.cssText = "margin-top:10px;padding-top:8px;border-top:1px solid #EEE;font-size:10.5px;color:#8A8A8A";

  box.append(close, head, list, foot);
  document.body.appendChild(box);

  setTimeout(() => {
    const el = document.getElementById("__fraud-scanner-toast");
    if (el) el.remove();
  }, 20000);
};
