"""
Generate PDF fixtures for the JavaScript reader test.

Builds real PDFs with the app's own sample generator, records what pypdf
extracts and what the Python detector scores, and writes it all to
pdf_fixtures.json for extension/test/pdf_test.js to check against.

    python extension/test/make_pdf_fixtures.py
"""

import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

import app  # noqa: E402

VENDORS = ["Vandelay Industries", "Acme Supply Co", "Northwind Traders"]


def build(kind):
    result = app.build_sample_invoice_bytes(kind)
    return result[0] if isinstance(result, tuple) else result


def build_jpegs():
    """Real JPEGs with and without EXIF, plus what Pillow reads from them.

    The tags that matter for a photographed receipt are Software and the
    DateTime pair, so those are what the browser reader is checked against.
    """
    from PIL import Image
    import io as _io

    out = []

    def record(name, img_bytes):
        text, meta = app.extract_from_image(img_bytes)
        findings, score = app.evaluate(text, meta, approved_vendors=[],
                                       claims_to_be_original=True)
        out.append({
            "name": name,
            "b64": base64.b64encode(img_bytes).decode("ascii"),
            "python_metadata": {
                "creation_date": meta.get("creation_date"),
                "mod_date": meta.get("mod_date"),
                "software": meta.get("software"),
                "has_metadata": meta.get("has_metadata", False),
            },
            "python_score": score,
            "python_band": app.risk_band(score)[0],
            "python_titles": [f["title"] for f in findings],
        })
        print(f"{name}: score {score} ({app.risk_band(score)[0]}) "
              f"software={meta.get('software')!r}")

    # Edited in Photoshop, modified months after the shot was taken.
    img = Image.new("RGB", (60, 40), (200, 200, 200))
    ex = Image.Exif()
    ex[0x0131] = "Adobe Photoshop 2026"        # Software
    ex[0x0132] = "2026:06:20 14:30:00"         # DateTime (last write)
    ex.get_ifd(0x8769)[0x9003] = "2026:01:15 09:00:00"  # DateTimeOriginal
    buf = _io.BytesIO()
    img.save(buf, format="JPEG", exif=ex)
    record("jpeg_photoshopped", buf.getvalue())

    # No EXIF at all — the "stripped metadata" case.
    buf = _io.BytesIO()
    Image.new("RGB", (60, 40), (180, 180, 180)).save(buf, format="JPEG")
    record("jpeg_no_exif", buf.getvalue())

    return out


def main():
    fixtures = []
    for kind in ("fraud", "clean"):
        data = build(kind)
        text, meta = app.extract_from_pdf(data)
        findings, score = app.evaluate(text, meta, approved_vendors=VENDORS,
                                       claims_to_be_original=True)
        fixtures.append({
            "name": f"sample_{kind}",
            "b64": base64.b64encode(data).decode("ascii"),
            "vendors": VENDORS,
            "python_metadata": {
                "creation_date": meta.get("creation_date"),
                "mod_date": meta.get("mod_date"),
                "software": meta.get("software"),
                "has_metadata": meta.get("has_metadata", False),
            },
            "python_text_len": len(text),
            "python_score": score,
            "python_band": app.risk_band(score)[0],
            "python_titles": [f["title"] for f in findings],
        })
        print(f"{kind}: {len(data)} bytes, text {len(text)} chars, "
              f"score {score} ({app.risk_band(score)[0]})")

    out = os.path.join(HERE, "pdf_fixtures.json")
    with open(out, "w") as fh:
        json.dump(fixtures, fh, indent=2)
    print("wrote", out)

    try:
        jpegs = build_jpegs()
    except Exception as exc:          # Pillow missing, or no JPEG support
        print("skipping JPEG fixtures:", exc)
        jpegs = []
    if jpegs:
        out = os.path.join(HERE, "jpeg_fixtures.json")
        with open(out, "w") as fh:
            json.dump(jpegs, fh, indent=2)
        print("wrote", out)


if __name__ == "__main__":
    main()
