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


if __name__ == "__main__":
    main()
