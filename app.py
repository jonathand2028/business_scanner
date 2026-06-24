"""
Cross-Modal Data Inconsistency Detection - Streamlit MVP
========================================================

A B2B forensics demo that flags likely document/image fraud by checking
whether a file's separate layers AGREE with each other:

    1. The text you can read (printed dates, amounts, vendor names)
    2. The hidden file data / metadata (creation date, editing software)
    3. The business context you already trust (an approved-vendor list)

It does NOT try to guess "was this made by AI." It catches logical lies,
e.g. an invoice that reads "January 2026" whose file data shows it was
exported from Photoshop in June 2026.

Run it:
    pip install streamlit pypdf Pillow
    streamlit run app.py

Pure logic (date finding, metadata reasoning) lives at the top of this file
with no Streamlit dependency, so it can be unit-tested on its own.
"""

import re
import io
from datetime import datetime, timezone

# ----------------------------------------------------------------------
# Configuration: signals we treat as suspicious
# ----------------------------------------------------------------------

# Software names that indicate a file was edited in an image/graphics editor.
# Seeing these on something that is supposed to be an untouched original is a flag.
EDITOR_SOFTWARE = [
    "photoshop", "gimp", "canva", "illustrator", "affinity", "pixelmator",
    "paint.net", "inkscape", "snapseed", "lightroom", "coreldraw",
    "figma", "sketch", "preview",  # 'Preview' on macOS often re-saves/edits
]

# How many days of gap between the printed date and the real file date
# we consider worth flagging.
DATE_GAP_DAYS = 30

# Month names for parsing things like "Invoice Date: January 2026"
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


# ----------------------------------------------------------------------
# Pure helpers (no Streamlit) - these are the testable core
# ----------------------------------------------------------------------

def find_dates(text):
    """Return a list of (raw_string, date) for dates found in free text.

    Handles: 2026-01-15, 01/15/2026, 15/01/2026, "January 2026",
    "March 3, 2026", "3 March 2026".
    """
    found = []
    if not text:
        return found

    # ISO: 2026-01-15
    for m in re.finditer(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", text):
        y, mo, d = map(int, m.groups())
        _try_add(found, m.group(0), y, mo, d)

    # Numeric slashes: 01/15/2026 or 15/01/2026 (assume month-first, fall back)
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        mo, d = (a, b) if a <= 12 else (b, a)
        _try_add(found, m.group(0), y, mo, d)

    # "Month DD, YYYY" or "Month YYYY"
    for m in re.finditer(
        r"\b([A-Za-z]{3,9})\.?\s+(?:(\d{1,2})(?:st|nd|rd|th)?,?\s+)?(\d{4})\b", text
    ):
        name = m.group(1).lower()
        if name in _MONTHS:
            d = int(m.group(2)) if m.group(2) else 1
            _try_add(found, m.group(0), int(m.group(3)), _MONTHS[name], d)

    # "DD Month YYYY"
    for m in re.finditer(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})\b", text):
        name = m.group(2).lower()
        if name in _MONTHS:
            _try_add(found, m.group(0), int(m.group(3)), _MONTHS[name], int(m.group(1)))

    return found


def _try_add(found, raw, y, mo, d):
    try:
        found.append((raw, datetime(y, mo, d)))
    except ValueError:
        pass


def parse_metadata_date(value):
    """Parse the many date formats found in PDF/EXIF metadata into a datetime."""
    if not value:
        return None
    s = str(value).strip()
    # PDF style: D:20260610153000  or  D:20260610
    m = re.match(r"D?:?(\d{4})(\d{2})(\d{2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    # EXIF style: 2026:06:10 15:30:00
    m = re.match(r"(\d{4})[:\-](\d{2})[:\-](\d{2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def software_is_editor(software):
    """True if a software string names a known image/graphics editor."""
    if not software:
        return False
    s = str(software).lower()
    return any(name in s for name in EDITOR_SOFTWARE)


def evaluate(text, metadata, approved_vendors=None, claims_to_be_original=True):
    """Core cross-check. Returns (findings, score).

    findings: list of dicts {level, title, detail}
    score:    0-100 risk number
    metadata: dict that may contain creation_date, mod_date, software,
              has_metadata (bool)
    """
    findings = []
    score = 0

    doc_dates = [d for _, d in find_dates(text)]
    meta_create = parse_metadata_date(metadata.get("creation_date"))
    meta_mod = parse_metadata_date(metadata.get("mod_date"))
    software = metadata.get("software")

    # 1. Printed date vs. real file creation date
    if doc_dates and meta_create:
        earliest_printed = min(doc_dates)
        gap = (meta_create - earliest_printed).days
        if gap > DATE_GAP_DAYS:
            score += 35
            findings.append({
                "level": "high",
                "title": "Printed date is older than the file itself",
                "detail": (
                    f"The document shows a date of "
                    f"{earliest_printed.date()}, but the file was actually "
                    f"created on {meta_create.date()} "
                    f"({gap} days later). A genuine document is normally "
                    f"created on or near its printed date."
                ),
            })

    # 2. Editing software on a supposed original
    if claims_to_be_original and software_is_editor(software):
        score += 30
        findings.append({
            "level": "high",
            "title": "Edited in image/graphics software",
            "detail": (
                f"The file reports it was produced or last saved with "
                f"'{software}'. An untouched original (a real system export "
                f"or camera photo) would not normally pass through an editor."
            ),
        })

    # 3. Created and modified at clearly different times
    if meta_create and meta_mod:
        moddiff = (meta_mod - meta_create).days
        if moddiff > 1:
            score += 15
            findings.append({
                "level": "medium",
                "title": "Modified after it was created",
                "detail": (
                    f"Created {meta_create.date()} but last modified "
                    f"{meta_mod.date()}. Worth checking what changed."
                ),
            })

    # 4. Missing / stripped metadata
    if not metadata.get("has_metadata", True):
        score += 20
        findings.append({
            "level": "medium",
            "title": "Hidden file data is missing",
            "detail": (
                "This file has little or no metadata. That can be innocent, "
                "but fraudsters often strip it to hide where a file really "
                "came from, so treat a 'clean' file with mild suspicion."
            ),
        })

    # 5. Vendor not on the approved list (business-context check)
    if approved_vendors:
        vendors = [v.strip().lower() for v in approved_vendors if v.strip()]
        if vendors and text:
            low = text.lower()
            if not any(v in low for v in vendors):
                score += 25
                findings.append({
                    "level": "medium",
                    "title": "No approved vendor found in the document",
                    "detail": (
                        "None of your approved vendor names appear in this "
                        "document. If this is supposed to be from a known "
                        "supplier, that is a problem."
                    ),
                })

    # 6. Conflicting dates inside the document
    if len(doc_dates) >= 2:
        spread = (max(doc_dates) - min(doc_dates)).days
        if spread > 365 * 2:
            score += 10
            findings.append({
                "level": "low",
                "title": "Dates inside the document are far apart",
                "detail": (
                    f"The document mentions dates spanning {spread} days, "
                    f"which can indicate copy-paste from another file."
                ),
            })

    score = min(score, 100)
    return findings, score


def risk_band(score):
    if score >= 50:
        return "HIGH", "Likely fraud - review before trusting"
    if score >= 20:
        return "MEDIUM", "Some inconsistencies - worth a human check"
    return "LOW", "No strong inconsistencies found"


# ----------------------------------------------------------------------
# Extraction (needs pypdf / Pillow) - imported lazily so the pure logic
# above can be tested without those libraries installed.
# ----------------------------------------------------------------------

def extract_from_pdf(file_bytes):
    """Return (text, metadata) for a PDF using pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    text = ""
    for page in reader.pages:
        try:
            text += (page.extract_text() or "") + "\n"
        except Exception:
            pass

    meta = reader.metadata or {}
    has_meta = bool(meta) and any(meta.values())
    return text, {
        "creation_date": meta.get("/CreationDate"),
        "mod_date": meta.get("/ModDate"),
        "software": meta.get("/Producer") or meta.get("/Creator"),
        "author": meta.get("/Author"),
        "has_metadata": has_meta,
        "raw": {k: str(v) for k, v in meta.items()} if meta else {},
    }


def extract_from_image(file_bytes):
    """Return (text, metadata) for an image using Pillow.

    No OCR in this MVP, so 'text' is whatever readable strings the file
    embeds (rare). The fraud signal here is the metadata, not the pixels.
    """
    from PIL import Image
    from PIL.ExifTags import TAGS

    img = Image.open(io.BytesIO(file_bytes))
    exif_raw = {}
    try:
        raw = img.getexif()
        for tag_id, value in raw.items():
            exif_raw[TAGS.get(tag_id, str(tag_id))] = value
    except Exception:
        pass

    # PNGs and AI tools sometimes stash data in img.info instead of EXIF.
    info = {k: v for k, v in (img.info or {}).items()
            if isinstance(v, (str, int, float))}

    software = exif_raw.get("Software") or info.get("Software")
    create = exif_raw.get("DateTimeOriginal") or exif_raw.get("DateTime")
    mod = exif_raw.get("DateTime")
    has_meta = bool(exif_raw) or bool(info)

    readable = " ".join(str(v) for v in info.values())
    return readable, {
        "creation_date": create,
        "mod_date": mod,
        "software": software,
        "has_metadata": has_meta,
        "raw": {**{k: str(v) for k, v in exif_raw.items()},
                **{k: str(v) for k, v in info.items()}},
    }


# ----------------------------------------------------------------------
# Built-in sample: a fraudulent invoice for one-click testing
# ----------------------------------------------------------------------

def build_sample_invoice_bytes():
    """Create a dummy invoice PDF with a planted contradiction:
    the page reads 'Invoice Date: Jan 2026' but the hidden metadata says it
    was created June 2026 and produced by 'Adobe Photoshop'. Returns bytes.

    Requires reportlab (listed in requirements.txt).
    """
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader, PdfWriter

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    w, h = LETTER
    c.setFont("Helvetica-Bold", 22)
    c.drawString(1 * inch, h - 1 * inch, "INVOICE")
    c.setFont("Helvetica", 11)
    c.drawString(1 * inch, h - 1.5 * inch, "Northwind Trading Co.")
    c.drawString(1 * inch, h - 1.7 * inch, "billing@northwind-example.com")
    c.setFont("Helvetica-Bold", 11)
    c.drawString(5 * inch, h - 1.5 * inch, "Invoice Date: Jan 2026")
    c.setFont("Helvetica", 11)
    c.drawString(5 * inch, h - 1.7 * inch, "Invoice #: INV-2026-0042")
    c.drawString(1 * inch, h - 2.4 * inch, "Bill To: Acme Logistics LLC")
    c.drawString(1 * inch, h - 3.0 * inch, "Freight services - Q1 .............. $3,000")
    c.drawString(1 * inch, h - 3.3 * inch, "Fuel surcharge .................... $450")
    c.drawString(1 * inch, h - 3.6 * inch, "Handling fee ...................... $550")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1 * inch, h - 4.1 * inch, "Total: $4,000")
    c.showPage()
    c.save()
    buf.seek(0)

    reader = PdfReader(buf)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata({
        "/Title": "Invoice INV-2026-0042",
        "/Producer": "Adobe Photoshop 25.0",      # anomaly
        "/Creator": "Adobe Photoshop",            # anomaly
        "/CreationDate": "D:20260615120000Z",     # June, text says January
        "/ModDate": "D:20260615120000Z",
    })
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# ----------------------------------------------------------------------
# Streamlit UI
# ----------------------------------------------------------------------

def main():
    import streamlit as st

    st.set_page_config(page_title="Inconsistency Scanner", page_icon="🔎",
                       layout="centered")
    st.title("Cross-Modal Data Inconsistency Scanner")
    st.caption(
        "Catches fraud by checking whether a file's printed text, its hidden "
        "metadata, and your business records all agree. It does not guess "
        "whether AI made the file."
    )

    with st.sidebar:
        st.header("Business context (optional)")
        vendor_text = st.text_area(
            "Approved vendors (one per line)",
            placeholder="Acme Supplies\nGlobex Corp\nInitech",
            help="If none of these names show up in the document, that is flagged.",
        )
        claims_original = st.checkbox(
            "File should be an untouched original", value=True,
            help="Turn off if it is expected to have been edited or re-saved.",
        )
        st.markdown("---")
        st.caption("Pasting raw text instead? Use the box at the bottom.")

    st.markdown("**No file handy? Test it instantly:**")
    if st.button("🧪 Try a sample fraudulent invoice"):
        try:
            st.session_state["sample_pdf"] = build_sample_invoice_bytes()
        except Exception as e:
            st.error(f"Could not build sample: {e}")
    sample_pdf = st.session_state.get("sample_pdf")
    if sample_pdf:
        st.download_button(
            "Download this sample (test_invoice.pdf)", sample_pdf,
            file_name="test_invoice.pdf", mime="application/pdf")
        st.caption("Generated invoice reads 'Jan 2026' but its metadata says "
                   "June 2026 + Adobe Photoshop. Scanned automatically below.")

    uploaded = st.file_uploader(
        "Upload an invoice, receipt, ID, or record (PDF, PNG, JPG)",
        type=["pdf", "png", "jpg", "jpeg"],
    )

    pasted = st.text_area("...or paste document text directly", height=120)

    if not uploaded and not pasted.strip() and not sample_pdf:
        st.info("Upload a file, paste text, or try the sample invoice above.")
        return

    approved = vendor_text.splitlines() if vendor_text else None

    text, metadata = "", {"has_metadata": True}
    if uploaded:
        data = uploaded.read()
        try:
            if uploaded.name.lower().endswith(".pdf"):
                text, metadata = extract_from_pdf(data)
            else:
                text, metadata = extract_from_image(data)
        except Exception as e:
            st.error(f"Could not read the file: {e}")
            return
    elif sample_pdf:
        text, metadata = extract_from_pdf(sample_pdf)
    if pasted.strip():
        text = (text + "\n" + pasted).strip()

    findings, score = evaluate(
        text, metadata, approved_vendors=approved,
        claims_to_be_original=claims_original,
    )
    band, summary = risk_band(score)

    color = {"HIGH": "red", "MEDIUM": "orange", "LOW": "green"}[band]
    st.markdown(f"### Risk: :{color}[{band}] ({score}/100)")
    st.write(summary)
    st.progress(score / 100)

    st.subheader("Findings")
    if not findings:
        st.success("No inconsistencies detected in the layers we can read.")
    else:
        for f in findings:
            icon = {"high": "🔴", "medium": "🟠", "low": "🟡"}[f["level"]]
            with st.expander(f"{icon}  {f['title']}", expanded=f["level"] == "high"):
                st.write(f["detail"])

    with st.expander("What the scanner extracted"):
        dates = [raw for raw, _ in find_dates(text)]
        st.write("**Dates found in text:**", ", ".join(dates) or "none")
        st.write("**Detected software:**", metadata.get("software") or "none")
        st.write("**File creation date:**",
                 str(metadata.get("creation_date") or "none"))
        st.write("**Raw metadata:**")
        st.json(metadata.get("raw", {}))

    st.caption(
        "Every flag is a signal, not a verdict. A person should make the "
        "final call."
    )


if __name__ == "__main__":
    main()
