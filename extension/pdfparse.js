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

/**
 * JPEG EXIF reader — walks the TIFF IFD structure properly rather than
 * pattern-matching the raw bytes.
 *
 * This matters for photographed receipts and IDs. The tags that give away an
 * edited image are Software (0x0131) and the three DateTime fields, and a
 * regex over the file finds them only by luck: it can't tell a real Software
 * tag from the same words appearing in a comment or a colour profile, and it
 * can't tell which of several timestamps is which.
 *
 * EXIF tags read:
 *   0x0132 DateTime          — last modification (matches pypdf/Pillow's DateTime)
 *   0x9003 DateTimeOriginal  — when the photo was taken
 *   0x0131 Software          — the editor that last wrote the file
 */
const EXIF_TAGS = { 0x0132: "datetime", 0x9003: "datetime_original",
                    0x0131: "software" };

function readExifIfd(view, tiffStart, ifdOffset, little, out, depth = 0) {
  if (depth > 2) return;
  const base = tiffStart + ifdOffset;
  if (base + 2 > view.byteLength) return;
  const count = view.getUint16(base, little);

  for (let i = 0; i < count; i++) {
    const entry = base + 2 + i * 12;
    if (entry + 12 > view.byteLength) return;

    const tag = view.getUint16(entry, little);
    const type = view.getUint16(entry + 2, little);
    const num = view.getUint32(entry + 4, little);

    // 0x8769 is the pointer to the EXIF sub-IFD, where DateTimeOriginal lives.
    if (tag === 0x8769) {
      readExifIfd(view, tiffStart, view.getUint32(entry + 8, little),
                  little, out, depth + 1);
      continue;
    }

    const name = EXIF_TAGS[tag];
    if (!name || type !== 2) continue; // type 2 = ASCII

    let valueOffset = entry + 8;
    if (num > 4) valueOffset = tiffStart + view.getUint32(entry + 8, little);
    if (valueOffset + num > view.byteLength) continue;

    let s = "";
    for (let j = 0; j < num; j++) {
      const c = view.getUint8(valueOffset + j);
      if (c === 0) break;
      s += String.fromCharCode(c);
    }
    s = s.trim();
    if (s) out[name] = s;
  }
}

function extractJpegExif(bytes) {
  const meta = { creation_date: null, mod_date: null, software: null,
                 has_metadata: false };
  if (!(bytes[0] === 0xFF && bytes[1] === 0xD8)) return meta;

  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let offset = 2;
  let found = null;

  // Walk JPEG markers looking for APP1 with an "Exif\0\0" header.
  while (offset + 4 <= bytes.length) {
    if (view.getUint8(offset) !== 0xFF) break;
    const marker = view.getUint8(offset + 1);
    if (marker === 0xD8 || marker === 0x01 || (marker >= 0xD0 && marker <= 0xD7)) {
      offset += 2; continue;
    }
    if (marker === 0xDA || marker === 0xD9) break; // start of scan / end
    const size = view.getUint16(offset + 2, false);
    if (marker === 0xE1) {
      const hdr = bytesToLatin1(bytes.subarray(offset + 4, offset + 10));
      if (hdr.startsWith("Exif")) { found = offset + 10; break; }
    }
    offset += 2 + size;
  }

  if (found === null) return meta;

  // TIFF header: "II" little-endian or "MM" big-endian, then 0x2A.
  const byteOrder = bytesToLatin1(bytes.subarray(found, found + 2));
  const little = byteOrder === "II";
  if (!little && byteOrder !== "MM") return meta;
  if (view.getUint16(found + 2, little) !== 0x2A) return meta;

  const out = {};
  try {
    readExifIfd(view, found, view.getUint32(found + 4, little), little, out);
  } catch {
    return meta;
  }

  if (out.software) meta.software = out.software;
  // DateTimeOriginal is when the shutter fired; DateTime is the last write.
  if (out.datetime_original) meta.creation_date = out.datetime_original;
  if (out.datetime) {
    meta.mod_date = out.datetime;
    if (!meta.creation_date) meta.creation_date = out.datetime;
  }
  meta.has_metadata = Boolean(meta.software || meta.creation_date || meta.mod_date);
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
                     textFromContentStream, isPdf, ascii85Decode,
                     extractJpegExif };
}
