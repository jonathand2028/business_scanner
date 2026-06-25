"""
create_test_invoice.py
======================

Generates a dummy PDF invoice for testing the Cross-Modal Inconsistency
Scanner, with a deliberate, planted contradiction:

  * The VISIBLE text says   ->  "Invoice Date: Jan 2026"
  * The HIDDEN metadata says ->  created June 2026, and produced by
                                 "Adobe Photoshop" (not a billing system)

A genuine invoice's printed date matches its file creation date and is
produced by accounting software. This file fails both checks, so feeding it
into the scanner should light up as HIGH risk.

Usage:
    pip install reportlab pypdf
    python create_test_invoice.py            # writes test_invoice.pdf
    python create_test_invoice.py clean.pdf  # custom output name

Then in the scanner, upload the generated PDF (leave "untouched original"
checked) and you should see the date and software flags fire.
"""

import sys
import io

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from pypdf import PdfReader, PdfWriter

# What the human reads on the page (note the January date):
VISIBLE_INVOICE_DATE = "Jan 2026"

# What we secretly stamp into the file's metadata (the contradiction):
FAKE_CREATION_DATE = "D:20260615120000Z"   # June 15 2026
FAKE_PRODUCER = "Adobe Photoshop 25.0"
FAKE_CREATOR = "Adobe Photoshop"


def _draw_invoice(buf):
    """Draw a simple, realistic-looking invoice onto a PDF in `buf`."""
    c = canvas.Canvas(buf, pagesize=LETTER)
    w, h = LETTER

    c.setFont("Helvetica-Bold", 22)
    c.drawString(1 * inch, h - 1 * inch, "INVOICE")

    c.setFont("Helvetica", 11)
    c.drawString(1 * inch, h - 1.5 * inch, "Northwind Trading Co.")
    c.drawString(1 * inch, h - 1.7 * inch, "123 Commerce Street")
    c.drawString(1 * inch, h - 1.9 * inch, "billing@northwind-example.com")

    # The visible (and contradictory) date and details:
    c.setFont("Helvetica-Bold", 11)
    c.drawString(5 * inch, h - 1.5 * inch, f"Invoice Date: {VISIBLE_INVOICE_DATE}")
    c.setFont("Helvetica", 11)
    c.drawString(5 * inch, h - 1.7 * inch, "Invoice #: INV-2026-0042")
    c.drawString(5 * inch, h - 1.9 * inch, "Due Date: Feb 2026")

    c.drawString(1 * inch, h - 2.6 * inch, "Bill To: Acme Logistics LLC")

    # line items
    y = h - 3.3 * inch
    c.setFont("Helvetica-Bold", 11)
    c.drawString(1 * inch, y, "Description")
    c.drawString(4.5 * inch, y, "Qty")
    c.drawString(5.5 * inch, y, "Unit")
    c.drawString(6.5 * inch, y, "Amount")
    c.line(1 * inch, y - 4, 7.2 * inch, y - 4)

    c.setFont("Helvetica", 11)
    items = [
        ("Freight services - Q1", "10", "$300", "$3,000"),
        ("Fuel surcharge", "1", "$450", "$450"),
        ("Handling fee", "5", "$110", "$550"),
    ]
    y -= 0.3 * inch
    for desc, qty, unit, amt in items:
        c.drawString(1 * inch, y, desc)
        c.drawString(4.5 * inch, y, qty)
        c.drawString(5.5 * inch, y, unit)
        c.drawString(6.5 * inch, y, amt)
        y -= 0.3 * inch

    c.line(1 * inch, y, 7.2 * inch, y)
    y -= 0.3 * inch
    c.setFont("Helvetica-Bold", 12)
    c.drawString(5.5 * inch, y, "Total: $4,000")

    c.setFont("Helvetica-Oblique", 9)
    c.drawString(1 * inch, 1 * inch,
                 "Thank you for your business. Payment due within 30 days.")
    c.showPage()
    c.save()


def create_invoice(out_path="test_invoice.pdf"):
    # 1. Build the visible PDF with reportlab.
    buf = io.BytesIO()
    _draw_invoice(buf)
    buf.seek(0)

    # 2. Rewrite the metadata with the planted anomaly using pypdf.
    reader = PdfReader(buf)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    writer.add_metadata({
        "/Title": "Invoice INV-2026-0042",
        "/Author": "billing@northwind-example.com",
        "/Subject": "Invoice",
        "/Producer": FAKE_PRODUCER,     # anomaly: image editor, not billing sw
        "/Creator": FAKE_CREATOR,       # anomaly
        "/CreationDate": FAKE_CREATION_DATE,  # anomaly: June, text says January
        "/ModDate": FAKE_CREATION_DATE,
    })

    with open(out_path, "wb") as f:
        writer.write(f)

    print(f"Wrote {out_path}")
    print(f"  Visible invoice date : {VISIBLE_INVOICE_DATE}")
    print(f"  Metadata creation    : {FAKE_CREATION_DATE}  (June 2026)")
    print(f"  Metadata producer    : {FAKE_PRODUCER}")
    print("Upload this to the scanner - it should flag HIGH risk.")
    return out_path


if __name__ == "__main__":
    # Optional: reuse the app's randomized generator if available so the CLI
    # and the in-app button produce the same variety. Falls back to the fixed
    # invoice above if the app module can't be imported.
    args = [a for a in sys.argv[1:]]
    want_clean = "--clean" in args
    paths = [a for a in args if not a.startswith("--")]
    out = paths[0] if paths else "test_invoice.pdf"
    try:
        from app import build_sample_invoice_bytes
        data, info = build_sample_invoice_bytes("clean" if want_clean else "fraud")
        with open(out, "wb") as f:
            f.write(data)
        print(f"Wrote {out}  ({info['label']})")
        if info["planted"]:
            print("  planted: " + "; ".join(info["planted"]))
    except Exception:
        create_invoice(out)
