/**
 * Checks the in-browser PDF reader against real PDFs produced by the app's own
 * sample generator, comparing what JavaScript extracts to what pypdf extracted
 * on the Python side.
 *
 * Fixtures are written by test/make_pdf_fixtures.py.
 *
 *   node extension/test/pdf_test.js
 *
 * Text extraction is best-effort by design — some PDFs are scans, some use
 * encodings this doesn't decode. The assertion is therefore not "text matches
 * byte for byte" but "the metadata matches exactly, and enough text is
 * recovered for the date checks to fire the same way".
 */

const fs = require("fs");
const path = require("path");

// DecompressionStream and Blob exist in Node 18+, which is what CI uses.
if (typeof DecompressionStream === "undefined") {
  console.log("DecompressionStream unavailable in this Node build — skipping.");
  process.exit(0);
}

const { extractMetadata, extractText, isPdf } = require("../pdfparse.js");
const { evaluateDocument, documentRiskBand } = require("../docdetector.js");

const fixturesPath = path.join(__dirname, "pdf_fixtures.json");
if (!fs.existsSync(fixturesPath)) {
  console.log("No pdf_fixtures.json — run test/make_pdf_fixtures.py first.");
  process.exit(0);
}
const fixtures = JSON.parse(fs.readFileSync(fixturesPath, "utf8"));

let failures = 0;

(async () => {
  console.log("In-browser PDF reader vs. pypdf");
  console.log("=".repeat(66));

  for (const fx of fixtures) {
    const bytes = new Uint8Array(Buffer.from(fx.b64, "base64"));
    const problems = [];

    if (!isPdf(bytes)) problems.push("not detected as a PDF");

    const meta = extractMetadata(bytes);
    for (const key of ["creation_date", "mod_date"]) {
      if ((meta[key] || null) !== (fx.python_metadata[key] || null)) {
        problems.push(`${key}: js ${meta[key]} != python ${fx.python_metadata[key]}`);
      }
    }
    if ((meta.software || null) !== (fx.python_metadata.software || null)) {
      problems.push(`software: js "${meta.software}" != python "${fx.python_metadata.software}"`);
    }
    if (meta.has_metadata !== fx.python_metadata.has_metadata) {
      problems.push("has_metadata differs");
    }

    let text = "";
    try {
      text = await extractText(bytes);
    } catch (e) {
      problems.push("text extraction threw: " + e.message);
    }

    // The date checks are what the text is for, so assert on those rather than
    // on exact string equality with pypdf's output.
    const jsResult = evaluateDocument(text, meta, fx.vendors, true);
    const jsBand = documentRiskBand(jsResult.score).band;

    if (jsResult.score !== fx.python_score) {
      problems.push(`score on extracted text: js ${jsResult.score} != python ${fx.python_score}`);
    }
    if (jsBand !== fx.python_band) {
      problems.push(`band: js ${jsBand} != python ${fx.python_band}`);
    }

    const ok = problems.length === 0;
    if (!ok) failures += 1;
    console.log(`  ${ok ? "ok  " : "FAIL"}  ${fx.name.padEnd(20)} `
      + `text ${String(text.length).padStart(4)} chars  score ${String(jsResult.score).padStart(3)}  ${jsBand}`);
    problems.forEach((p) => console.log(`        ${p}`));
  }

  console.log("=".repeat(66));
  console.log(failures === 0
    ? `${fixtures.length}/${fixtures.length} PDFs parsed consistently with pypdf.`
    : `${failures} of ${fixtures.length} failed.`);
  process.exit(failures ? 1 : 0);
})();
