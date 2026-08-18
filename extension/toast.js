/**
 * In-page result panel.
 *
 * Used two ways:
 *
 *   __fraudScannerShow(result)  — called by the content script when an opened
 *                                 email scores MEDIUM or higher, so the reasons
 *                                 are visible without clicking the toolbar icon
 *   __fraudScannerToast(text)   — called by the right-click "scan selection"
 *                                 menu, which scores the text first
 *
 * Only appears when there's something worth saying. A clean email gets a green
 * badge on the icon and nothing else, because a panel on every message would
 * be noise and people would learn to ignore it.
 *
 * No network, no storage. Dismissing it is remembered in a variable for the
 * life of the page only.
 */

(function () {
  const ID = "__fraud-scanner-panel";
  const COLORS = {
    HIGH: ["#D93025", "#FDF3F2"],
    MEDIUM: ["#E08600", "#FDF8EF"],
    LOW: ["#1E8E3E", "#F2F9F4"],
  };

  let dismissed = new Set();

  function remove() {
    const el = document.getElementById(ID);
    if (el) el.remove();
  }

  /**
   * @param {{findings:Array, score:number, band:string, note:string,
   *          subject?:string, sender?:string, key?:string}} r
   */
  function show(r) {
    if (r.key && dismissed.has(r.key)) return;
    remove();

    const [accent, bg] = COLORS[r.band] || COLORS.LOW;

    const box = document.createElement("div");
    box.id = ID;
    box.style.cssText = [
      "position:fixed", "top:70px", "right:20px", "z-index:2147483647",
      "width:330px", "max-height:60vh", "overflow-y:auto",
      "background:#fff", "border:1px solid #E6E6E6",
      `border-left:4px solid ${accent}`,
      "border-radius:8px", "box-shadow:0 8px 28px rgba(0,0,0,.20)",
      "padding:0", "overflow-x:hidden",
      "font:13px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif",
      "color:#1A1A1A",
    ].join(";");

    const head = document.createElement("div");
    head.style.cssText = `background:${bg};padding:12px 40px 12px 16px;position:relative`;

    const title = document.createElement("div");
    title.textContent = `${r.band} — risk score ${r.score}/100`;
    title.style.cssText = `font-weight:700;font-size:14px;color:${accent}`;

    const sub = document.createElement("div");
    sub.textContent = r.note || "";
    sub.style.cssText = "font-size:11.5px;color:#6A6A6A;margin-top:1px";

    const meta = document.createElement("div");
    meta.textContent = [
      r.subject ? `“${r.subject}”` : "",
      r.sender ? `from ${r.sender}` : "",
    ].filter(Boolean).join("  ·  ");
    meta.style.cssText = "font-size:11px;color:#6A6A6A;margin-top:5px;word-break:break-word";

    const close = document.createElement("button");
    close.textContent = "×";
    close.setAttribute("aria-label", "Dismiss");
    close.style.cssText = [
      "position:absolute", "top:8px", "right:10px", "border:0",
      "background:none", "font-size:20px", "line-height:1",
      "color:#7A7A7A", "cursor:pointer", "padding:0",
    ].join(";");
    close.addEventListener("click", () => {
      if (r.key) dismissed.add(r.key);
      remove();
    });

    head.append(title, sub, meta, close);

    const body = document.createElement("div");
    body.style.cssText = "padding:4px 16px 12px";

    if (!r.findings || !r.findings.length) {
      const d = document.createElement("div");
      d.textContent = "No phishing signals found.";
      d.style.cssText = "font-size:12px;color:#6A6A6A;padding-top:8px";
      body.appendChild(d);
    } else {
      for (const f of r.findings) {
        const row = document.createElement("div");
        row.style.cssText = "padding:9px 0;border-top:1px solid #EEE";
        const t = document.createElement("div");
        t.textContent = f.title;
        t.style.cssText = "font-weight:600;font-size:12.5px";
        const d = document.createElement("div");
        d.textContent = f.detail;
        d.style.cssText = "font-size:11.5px;color:#6A6A6A;margin-top:2px;word-break:break-word";
        row.append(t, d);
        body.appendChild(row);
      }
    }

    const foot = document.createElement("div");
    foot.textContent = "Scanned locally. Nothing was uploaded. A decision aid, not a verdict.";
    foot.style.cssText = "border-top:1px solid #EEE;padding:8px 16px;font-size:10.5px;color:#8A8A8A";

    box.append(head, body, foot);
    document.body.appendChild(box);
  }

  window.__fraudScannerShow = show;
  window.__fraudScannerHide = remove;

  /** Right-click path: score the selection, then show it. */
  window.__fraudScannerToast = function (text) {
    const { findings, score } = checkEmail(text, "");
    const { band, note } = riskBand(score);
    show({ findings, score, band, note });
    setTimeout(remove, 20000);
  };
})();
