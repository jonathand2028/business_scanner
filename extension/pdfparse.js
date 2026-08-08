/**
 * Minimal in-browser PDF reader.
 *
 * The web app uses pypdf on the server. The extension can't do that — sending
 * someone's invoices to a server is exactly what this tool is supposed to avoid
 * — so this extracts what the detector needs directly from the raw bytes, with
 * no external library.
 *
 * Scope is deliberately narrow:
 *
 *   metadata  — /CreationDate, /ModDate, /Producer, /Creator from the Info
 *               dictionary. Reliable for the large majority of PDFs, since the
 *               Info dictionary is usually stored uncompressed.
 *
 *   text      — decompresses FlateDecode content streams using the browser's
 *               native DecompressionStream, then pulls string literals out of
 *               the text-showing operators (Tj, TJ, ', "). This works on
 *               ordinary generated PDFs (including the app's own samples) and
 *               will not work on scanned images or unusual encodings.
 *
 * When text extraction returns nothing the caller falls back to asking the user
 * to paste the text, rather than silently scoring an empty document — an empty
 * extraction would suppress every date-based check and produce a falsely clean
 * result.
 */

const PDF_HEADER = "%PDF-";

function bytesToLatin1(bytes) {
  let out = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    out += String.fromCharCode.apply(
      null, bytes.subarray(i, Math.min(i + CHUNK, bytes.length)));
  }
  return out;
}

function isPdf(bytes) {
  return bytesToLatin1(bytes.subarray(0, 8)).startsWith(PDF_HEADER);
}

/**
 * Decode a PDF string: (Acme \(Ltd\)) or <48656C6C6F>.
 * Outer delimiters are stripped. Octal escapes matter here — writers routinely
 * emit "GIMP 2\05610" for "GIMP 2.10" and "D\07220260615" for "D:20260615",
 * so skipping them silently corrupts both the software name and every date.
 */
function decodePdfString(raw) {
  if (raw == null) return "";
  let s = String(raw).trim();

  if (s.startsWith("<") && s.endsWith(">")) {
    const hex = s.slice(1, -1).replace(/\s+/g, "");
    let out = "";
    for (let i = 0; i + 1 < hex.length; i += 2) {
      out += String.fromCharCode(parseInt(hex.substr(i, 2), 16));
    }
    // UTF-16BE BOM
    if (out.charCodeAt(0) === 0xFE && out.charCodeAt(1) === 0xFF) {
      let u = "";
      for (let i = 2; i + 1 < out.length; i += 2) {
        u += String.fromCharCode((out.charCodeAt(i) << 8) | out.charCodeAt(i + 1));
      }
      return u;
    }
    return out;
  }

  if (s.startsWith("(") && s.endsWith(")")) s = s.slice(1, -1);

  // Octal escapes first, so \056 doesn't get partially eaten as an escape.
  return s
    .replace(/\\(\d{1,3})/g, (_, o) => String.fromCharCode(parseInt(o, 8)))
    .replace(/\\([nrtbf()\\])/g, (_, c) =>
      ({ n: "\n", r: "\r", t: "\t", b: "\b", f: "\f" }[c] || c));
}

/**
 * ASCII85 decode. reportlab (and therefore this app's own sample invoices)
 * wraps content streams in ASCII85 before Flate, so without this the text
 * layer silently comes back empty.
 */
function ascii85Decode(bytes) {
  let s = bytesToLatin1(bytes).replace(/\s+/g, "");
  if (s.startsWith("<~")) s = s.slice(2);
  const end = s.indexOf("~>");
  if (end !== -1) s = s.slice(0, end);

  const out = [];
  let tuple = [];
  for (const ch of s) {
    if (ch === "z" && tuple.length === 0) { out.push(0, 0, 0, 0); continue; }
    const code = ch.charCodeAt(0) - 33;
    if (code < 0 || code > 84) continue;
    tuple.push(code);
    if (tuple.length === 5) {
      let v = 0;
      for (const t of tuple) v = v * 85 + t;
      out.push((v >>> 24) & 255, (v >>> 16) & 255, (v >>> 8) & 255, v & 255);
      tuple = [];
    }
  }
  if (tuple.length > 1) {
    const n = tuple.length;
    while (tuple.length < 5) tuple.push(84);
    let v = 0;
    for (const t of tuple) v = v * 85 + t;
    const b = [(v >>> 24) & 255, (v >>> 16) & 255, (v >>> 8) & 255, v & 255];
    out.push(...b.slice(0, n - 1));
  }
  return new Uint8Array(out);
}

/** Pull /CreationDate, /ModDate, /Producer, /Creator out of the raw file. */
function extractMetadata(bytes) {
  const s = bytesToLatin1(bytes);
  const field = (name) => {
    // Either a literal string (…) or a hex string <…>
    const re = new RegExp("/" + name + "\\s*(\\((?:[^()\\\\]|\\\\.)*\\)|<[0-9A-Fa-f\\s]*>)");
    const m = s.match(re);
    return m ? decodePdfString(m[1]).trim() : null;
  };

  const creation = field("CreationDate");
  const mod = field("ModDate");
  const producer = field("Producer");
  const creator = field("Creator");

  // The app treats Producer/Creator as one "software" signal; prefer whichever
  // names an editor so a file that is e.g. Creator: Word / Producer: Photoshop
  // is not let through.
  let software = producer || creator || null;
  const editorish = [producer, creator].filter(Boolean).find((v) =>
    /photoshop|gimp|canva|illustrator|affinity|pixelmator|paint\.net|inkscape|snapseed|lightroom|coreldraw|figma|sketch|preview/i
      .test(v));
  if (editorish) software = editorish;

  const hasMetadata = Boolean(creation || mod || producer || creator);

  return {
    creation_date: creation,
    mod_date: mod,
    software,
    producer,
    creator,
    has_metadata: hasMetadata,
  };
}

/** Inflate a raw zlib/deflate buffer using the browser's built-in decompressor. */
async function inflate(bytes) {
  const tryFormat = async (format) => {
    const ds = new DecompressionStream(format);
    const stream = new Blob([bytes]).stream().pipeThrough(ds);
    return new Uint8Array(await new Response(stream).arrayBuffer());
  };
  try {
    return await tryFormat("deflate");
  } catch {
    try {
      return await tryFormat("deflate-raw");
    } catch {
      return null;
    }
  }
}

/** Pull readable strings out of a decoded content stream. */
function textFromContentStream(str) {
  const parts = [];

  // TJ arrays: [(Hello) -250 (World)] TJ
  for (const m of str.matchAll(/\[((?:[^\][\\]|\\.)*)\]\s*TJ/g)) {
    for (const s of m[1].matchAll(/\((?:[^()\\]|\\.)*\)/g)) {
      parts.push(decodePdfString(s[0].slice(1, -1)));
    }
    parts.push(" ");
  }

  // Simple shows: (Hello) Tj   /   (Hello) '   /   (Hello) "
  for (const m of str.matchAll(/\((?:[^()\\]|\\.)*\)\s*(?:Tj|'|")/g)) {
    const lit = m[0].match(/\((?:[^()\\]|\\.)*\)/)[0];
    parts.push(decodePdfString(lit.slice(1, -1)));
    parts.push(" ");
  }

  // Newlines between text blocks so dates don't run into each other.
  return parts.join("").replace(/[ \t]{2,}/g, " ").trim();
}

/** Extract visible text. Returns "" when nothing could be decoded. */
async function extractText(bytes) {
  const s = bytesToLatin1(bytes);
  const chunks = [];

  // Every "stream ... endstream" span; try to inflate each one.
  const re = /stream\r?\n?/g;
  let m;
  while ((m = re.exec(s)) !== null) {
    const start = m.index + m[0].length;
    const end = s.indexOf("endstream", start);
    if (end === -1) continue;
    const raw = bytes.subarray(start, end);
    if (!raw.length) continue;

    let decoded = null;

    if (raw[0] === 0x78) {
      // Bare zlib
      const out = await inflate(raw);
      if (out) decoded = bytesToLatin1(out);
    } else {
      // Possibly ASCII85, possibly ASCII85 + Flate, possibly plain.
      const a85 = ascii85Decode(raw);
      if (a85.length) {
        if (a85[0] === 0x78) {
          const out = await inflate(a85);
          if (out) decoded = bytesToLatin1(out);
        } else {
          const asText = bytesToLatin1(a85);
          if (/TJ|Tj/.test(asText)) decoded = asText;
        }
      }
      if (!decoded) {
        const asText = bytesToLatin1(raw);
        if (/TJ|Tj/.test(asText)) decoded = asText;
      }
    }
    if (!decoded) continue;

    const text = textFromContentStream(decoded);
    if (text) chunks.push(text);
    if (chunks.length > 60) break; // guard against pathological files
  }

  return chunks.join("\n").trim();
}

/** Minimal JPEG EXIF read for Software and DateTime. */
function extractJpegExif(bytes) {
  const meta = { creation_date: null, mod_date: null, software: null,
                 has_metadata: false };
  if (!(bytes[0] === 0xFF && bytes[1] === 0xD8)) return meta;

  const s = bytesToLatin1(bytes.subarray(0, Math.min(bytes.length, 200000)));
  // EXIF DateTime fields look like 2026:06:10 15:30:00 in plain ASCII.
  const dt = s.match(/\b(\d{4}):(\d{2}):(\d{2})\s\d{2}:\d{2}:\d{2}\b/);
  if (dt) {
    meta.creation_date = dt[0];
    meta.has_metadata = true;
  }
  const sw = s.match(/(Adobe Photoshop[^\0]{0,30}|GIMP[^\0]{0,20}|Canva|Pixelmator[^\0]{0,15}|Affinity[^\0]{0,20}|Snapseed|Lightroom[^\0]{0,20})/i);
  if (sw) {
    meta.software = sw[1].trim();
    meta.has_metadata = true;
  }
  return meta;
}

/**
 * Read any supported file.
 * @returns {{kind, text, metadata, textExtracted:boolean, note:string}}
 */
async function readFile(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());

  if (isPdf(bytes)) {
    const metadata = extractMetadata(bytes);
    let text = "";
    try {
      text = await extractText(bytes);
    } catch {
      text = "";
    }
    return {
      kind: "pdf",
      text,
      metadata,
      textExtracted: Boolean(text),
      note: text ? "" :
        "Couldn't read the text layer (this happens with scanned PDFs and some "
        + "encodings). Metadata checks still ran — paste the document text below "
        + "for the full set of checks.",
    };
  }

  const name = (file.name || "").toLowerCase();
  if (/\.(jpe?g)$/.test(name) || bytes[0] === 0xFF) {
    return {
      kind: "image",
      text: "",
      metadata: extractJpegExif(bytes),
      textExtracted: false,
      note: "Images have no text layer in the browser (the web app uses OCR). "
        + "Metadata checks ran — paste any visible text below for the rest.",
    };
  }

  return {
    kind: "unknown",
    text: "",
    metadata: { has_metadata: false },
    textExtracted: false,
    note: "Unsupported file type. PDF and JPEG are supported here; the web app "
      + "handles more formats.",
  };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { readFile, extractMetadata, extractText, decodePdfString,
                     textFromContentStream, isPdf, ascii85Decode };
}
