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
import csv
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

# Image container fields that exist in every file of that format and therefore
# carry no information about where the file came from.
_CONTAINER_INFO_KEYS = {
    "jfif", "jfif_version", "jfif_unit", "jfif_density", "dpi",
    "adobe", "adobe_transform", "progression", "progressive",
    "icc_profile", "exif", "gamma", "srgb", "interlace", "compression",
}

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

    # 1b. Invoice date is AFTER the file was created (dated in the future).
    # Use the earliest date (the invoice date) so a later due date does not
    # trip this, since due dates are legitimately in the future.
    if doc_dates and meta_create:
        earliest_printed = min(doc_dates)
        ahead = (earliest_printed - meta_create).days
        if ahead > 1:
            score += 20
            findings.append({
                "level": "medium",
                "title": "Dated after the file was created",
                "detail": (
                    f"The document is dated {earliest_printed.date()}, but the "
                    f"file was created earlier, on {meta_create.date()}. A "
                    f"future-dated invoice can be a sign of a fabricated record."
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


_INV_RE = re.compile(
    r'invoice\s*(?:#|no\.?|number)\s*:?\s*([A-Za-z0-9][A-Za-z0-9\-/]{3,})', re.I)


def find_invoice_number(text):
    """Pull an invoice number out of document text, or None."""
    m = _INV_RE.search(text or "")
    return m.group(1).strip() if m else None


def duplicate_invoice_numbers(pairs):
    """pairs: list of (filename, invoice_number). Returns the set of numbers
    that appear on more than one file (a classic double-billing sign)."""
    from collections import Counter
    counts = Counter(num for _, num in pairs if num)
    return {num for num, c in counts.items() if c > 1}


# ----------------------------------------------------------------------
# Phishing / scam email heuristics  (pure, testable)
# ----------------------------------------------------------------------

_URL_RE = re.compile(r'https?://[^\s<>"\')]+', re.I)
_SHORTENERS = ["bit.ly", "tinyurl", "t.co", "goo.gl", "ow.ly", "is.gd",
               "buff.ly", "rebrand.ly", "cutt.ly"]
_URGENCY = ["urgent", "immediately", "act now", "final notice", "within 24 hours",
            "suspended", "verify your account", "confirm your account",
            "account has been", "limited time", "expire", "last warning",
            "as soon as possible", "failure to", "avoid suspension"]
_SENSITIVE = ["password", "log in", "login", "ssn", "social security",
              "bank account", "routing number", "wire transfer", "gift card",
              "credit card", "cvv", "one-time code", "verification code",
              "seed phrase", "update your payment", "confirm your payment"]
_GENERIC = ["dear customer", "dear user", "dear account holder",
            "valued customer", "dear sir/madam", "dear member"]


def check_email(text, sender=""):
    """Flag common phishing/scam signals in an email. Returns (findings, score)."""
    findings, score = [], 0
    low = (text or "").lower()

    urgency = sorted({w for w in _URGENCY if w in low})
    if urgency:
        score += 22
        findings.append({"level": "medium", "title": "Pressure / urgency language",
                         "detail": "Phrases pushing you to act fast: "
                                   + ", ".join(urgency) + "."})

    sensitive = sorted({w for w in _SENSITIVE if w in low})
    if sensitive:
        score += 28
        findings.append({"level": "high", "title": "Asks for credentials or payment",
                         "detail": "Legitimate companies rarely ask for these by "
                                   "email: " + ", ".join(sensitive) + "."})

    urls = _URL_RE.findall(text or "")
    ip_urls = [u for u in urls if re.search(r'https?://\d{1,3}(?:\.\d{1,3}){3}', u)]
    shortened = [u for u in urls if any(s in u.lower() for s in _SHORTENERS)]
    http_urls = [u for u in urls if u.lower().startswith("http://")]
    if ip_urls:
        score += 28
        findings.append({"level": "high", "title": "Link points to a raw IP address",
                         "detail": "Real companies use domain names, not numeric "
                                   "IPs: " + ", ".join(ip_urls[:3]) + "."})
    if shortened:
        score += 16
        findings.append({"level": "medium", "title": "Shortened / hidden links",
                         "detail": "Shortened links hide their true destination: "
                                   + ", ".join(shortened[:3]) + "."})
    if http_urls:
        score += 10
        findings.append({"level": "low", "title": "Insecure (http) link",
                         "detail": "Links use http, not https: "
                                   + ", ".join(http_urls[:3]) + "."})

    if any(g in low for g in _GENERIC):
        score += 8
        findings.append({"level": "low", "title": "Generic greeting",
                         "detail": "A vague greeting like 'Dear customer' suggests "
                                   "a mass send, not a real relationship."})

    # sender domain vs link domains
    if sender and "@" in sender and urls:
        sdom = sender.split("@")[-1].strip().lower().strip(">")
        link_doms = set()
        for u in urls:
            m = re.search(r'https?://([^/]+)/?', u.lower())
            if m:
                link_doms.add(m.group(1).split(":")[0])
        if sdom and link_doms and all(sdom not in d and d not in sdom
                                      for d in link_doms):
            score += 12
            findings.append({"level": "medium", "title": "Links do not match the sender",
                             "detail": f"The sender is @{sdom} but the links point "
                                       "elsewhere, a common spoofing sign."})

    return findings, min(score, 100)


SAMPLE_PHISHING = """Subject: URGENT: Your account has been suspended

Dear Customer,

We detected unusual activity and your account has been suspended. You must
verify your account immediately to avoid permanent closure within 24 hours.

Confirm your password and payment details here: http://198.51.100.23/secure-login

Failure to act now will result in loss of access.

Account Security Team"""


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

    # Enable HEIC/HEIF support if pillow-heif is installed (iPhone photos).
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass

    img = Image.open(io.BytesIO(file_bytes))
    exif_raw = {}
    try:
        raw = img.getexif()
        for tag_id, value in raw.items():
            exif_raw[TAGS.get(tag_id, str(tag_id))] = value
        # getexif() returns only IFD0. DateTimeOriginal - when the shutter
        # actually fired - lives in the EXIF sub-IFD (0x8769), so without this
        # every photo's "created" date was really its last-modified date, and
        # an image edited months after it was taken looked internally consistent.
        try:
            for tag_id, value in raw.get_ifd(0x8769).items():
                exif_raw.setdefault(TAGS.get(tag_id, str(tag_id)), value)
        except Exception:
            pass
    except Exception:
        pass

    # PNGs and AI tools sometimes stash data in img.info instead of EXIF.
    # Container-level fields (JFIF version, density, colour profile) say nothing
    # about a file's origin; counting them as metadata meant the
    # "metadata stripped" check could never fire on a JPEG.
    info = {k: v for k, v in (img.info or {}).items()
            if isinstance(v, (str, int, float))
            and k.lower() not in _CONTAINER_INFO_KEYS}

    software = exif_raw.get("Software") or info.get("Software")
    create = exif_raw.get("DateTimeOriginal") or exif_raw.get("DateTime")
    mod = exif_raw.get("DateTime")
    has_meta = bool(exif_raw) or bool(info)

    # OCR: read the printed text off the image so photos/scans get the full
    # cross-check (dates, vendor, etc.). Requires tesseract-ocr on the system
    # and the pytesseract package; degrades gracefully if either is missing.
    ocr_text = ""
    try:
        import pytesseract
        ocr_text = pytesseract.image_to_string(img) or ""
    except Exception:
        ocr_text = ""

    readable = (ocr_text + " " + " ".join(str(v) for v in info.values())).strip()
    return readable, {
        "creation_date": create,
        "mod_date": mod,
        "software": software,
        "has_metadata": has_meta,
        "raw": {**{k: str(v) for k, v in exif_raw.items()},
                **{k: str(v) for k, v in info.items()}},
    }


# ----------------------------------------------------------------------
# Built-in sample generator: random clean OR fraudulent invoices
# ----------------------------------------------------------------------

import random as _random

_VENDORS = [
    "Northwind Trading Co.", "Globex Logistics", "Initech Supplies",
    "Umbrella Freight", "Stark Materials", "Wayne Hauling",
    "Soylent Foods Co.", "Hooli Hardware", "Vandelay Imports",
]
_BILL_TO = [
    "Acme Logistics LLC", "Pied Piper Inc.", "Wonka Distribution",
    "Cyberdyne Systems", "Gekko & Co.", "Bluth Company",
]
_LEGIT_PRODUCERS = [
    "QuickBooks 2026", "Xero Invoicing", "FreshBooks", "SAP Invoicing",
    "Microsoft Word", "Zoho Invoice",
]
_EDITORS = ["Adobe Photoshop 25.0", "GIMP 2.10", "Adobe Illustrator", "Canva"]
_LINE_ITEMS = [
    "Freight services", "Fuel surcharge", "Handling fee", "Pallet rental",
    "Customs brokerage", "Warehousing", "Last-mile delivery", "Insurance",
]
_MON_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_STREETS = ["Commerce St", "Industrial Ave", "Harbor Blvd", "Madison Ave",
            "Logistics Pkwy", "Warehouse Rd", "Market St", "Dockside Way"]
_CITIES = ["Chicago, IL 60601", "Newark, NJ 07102", "Houston, TX 77002",
           "Atlanta, GA 30303", "Columbus, OH 43215", "Reno, NV 89501",
           "Tampa, FL 33602", "Memphis, TN 38103"]


def build_sample_invoice_bytes(kind="fraud"):
    """Generate a randomized dummy invoice PDF for testing.

    kind="fraud"  -> plant at least one contradiction (date mismatch and/or
                     an image-editor producer tag).
    kind="clean"  -> metadata agrees with the page and uses billing software.

    Returns (pdf_bytes, info) where info = {"label", "planted": [...]}.
    Requires reportlab (listed in requirements.txt).
    """
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader, PdfWriter

    vendor = _random.choice(_VENDORS)
    bill_to = _random.choice(_BILL_TO)
    inv_no = f"INV-2026-{_random.randint(1000, 9999)}"
    printed_month_idx = _random.randint(0, 7)          # Jan..Aug
    printed_date = f"{_MON_ABBR[printed_month_idx]} 2026"

    # build itemized lines: (description, qty, unit_price, amount)
    items, subtotal = [], 0.0
    for _ in range(_random.randint(4, 7)):
        qty = _random.randint(1, 12)
        unit = _random.choice([45, 75, 120, 180, 250, 300, 450, 600, 90, 150])
        amt = qty * unit
        subtotal += amt
        items.append((_random.choice(_LINE_ITEMS), qty, unit, amt))
    tax = round(subtotal * 0.08, 2)
    total = subtotal + tax

    vslug = vendor.split()[0].lower()
    street = f"{_random.randint(100, 9899)} {_random.choice(_STREETS)}"
    city = _random.choice(_CITIES)
    po_no = f"PO-{_random.randint(10000, 99999)}"
    due_idx = min(printed_month_idx + 1, 11)
    due_date = f"{_MON_ABBR[due_idx]} 2026"

    # ---- draw the visible page ----
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    w, h = LETTER
    left, right = 0.9 * inch, w - 0.9 * inch

    # header
    c.setFont("Helvetica-Bold", 26)
    c.drawString(left, h - 0.95 * inch, "INVOICE")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(left, h - 1.4 * inch, vendor)
    c.setFont("Helvetica", 9.5)
    c.drawString(left, h - 1.6 * inch, street)
    c.drawString(left, h - 1.76 * inch, city)
    c.drawString(left, h - 1.92 * inch, f"billing@{vslug}-example.com")
    c.drawString(left, h - 2.08 * inch, f"(555) {_random.randint(200,999)}-{_random.randint(1000,9999)}")

    # invoice meta box (right side)
    mx = 4.7 * inch
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(mx, h - 1.4 * inch, "Invoice #:")
    c.drawString(mx, h - 1.6 * inch, "Invoice Date:")
    c.drawString(mx, h - 1.8 * inch, "Due Date:")
    c.drawString(mx, h - 2.0 * inch, "PO Number:")
    c.drawString(mx, h - 2.2 * inch, "Terms:")
    c.setFont("Helvetica", 9.5)
    c.drawString(mx + 1.1 * inch, h - 1.4 * inch, inv_no)
    c.drawString(mx + 1.1 * inch, h - 1.6 * inch, printed_date)
    c.drawString(mx + 1.1 * inch, h - 1.8 * inch, due_date)
    c.drawString(mx + 1.1 * inch, h - 2.0 * inch, po_no)
    c.drawString(mx + 1.1 * inch, h - 2.2 * inch, "Net 30")

    # bill-to
    c.setFont("Helvetica-Bold", 10)
    c.drawString(left, h - 2.7 * inch, "BILL TO")
    c.setFont("Helvetica", 9.5)
    c.drawString(left, h - 2.9 * inch, bill_to)
    c.drawString(left, h - 3.06 * inch,
                 f"{_random.randint(100,9899)} {_random.choice(_STREETS)}")
    c.drawString(left, h - 3.22 * inch, _random.choice(_CITIES))

    # table header
    ty = h - 3.8 * inch
    c.setFillGray(0.92)
    c.rect(left, ty - 4, right - left, 0.26 * inch, fill=1, stroke=0)
    c.setFillGray(0)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(left + 4, ty, "Description")
    c.drawRightString(right - 2.7 * inch, ty, "Qty")
    c.drawRightString(right - 1.4 * inch, ty, "Unit Price")
    c.drawRightString(right - 4, ty, "Amount")

    # table rows
    c.setFont("Helvetica", 9.5)
    ry = ty - 0.3 * inch
    for desc, qty, unit, amt in items:
        c.drawString(left + 4, ry, desc)
        c.drawRightString(right - 2.7 * inch, ry, str(qty))
        c.drawRightString(right - 1.4 * inch, ry, f"${unit:,.2f}")
        c.drawRightString(right - 4, ry, f"${amt:,.2f}")
        c.setStrokeGray(0.85)
        c.line(left, ry - 5, right, ry - 5)
        ry -= 0.28 * inch

    # totals
    c.setFont("Helvetica", 10)
    c.drawRightString(right - 1.4 * inch, ry - 6, "Subtotal:")
    c.drawRightString(right - 4, ry - 6, f"${subtotal:,.2f}")
    c.drawRightString(right - 1.4 * inch, ry - 0.22 * inch - 6, "Tax (8%):")
    c.drawRightString(right - 4, ry - 0.22 * inch - 6, f"${tax:,.2f}")
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(right - 1.4 * inch, ry - 0.5 * inch - 6, "TOTAL:")
    c.drawRightString(right - 4, ry - 0.5 * inch - 6, f"${total:,.2f}")

    # footer
    c.setFont("Helvetica-Oblique", 8.5)
    c.drawString(left, 1.0 * inch,
                 "Payment due within 30 days. Make checks payable to "
                 f"{vendor}. Thank you for your business.")
    c.showPage()
    c.save()
    buf.seek(0)

    # decide metadata
    planted = []
    if kind == "fraud":
        choices = _random.choice([["date"], ["software"], ["date", "software"]])
        if "date" in choices:
            # creation 2-6 months after the printed date -> clear mismatch
            cm = min(printed_month_idx + _random.randint(2, 6), 11) + 1
            creation = f"D:2026{cm:02d}15120000Z"
            planted.append(f"creation date 2026-{cm:02d} vs printed {printed_date}")
        else:
            creation = f"D:2026{printed_month_idx + 1:02d}10120000Z"
        if "software" in choices:
            producer = _random.choice(_EDITORS)
            planted.append(f"producer '{producer}'")
        else:
            producer = _random.choice(_LEGIT_PRODUCERS)
        label = "fraudulent"
    else:
        creation = f"D:2026{printed_month_idx + 1:02d}{_random.randint(1, 9):02d}120000Z"
        producer = _random.choice(_LEGIT_PRODUCERS)
        label = "clean"

    reader = PdfReader(buf)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata({
        "/Title": f"Invoice {inv_no}",
        "/Author": "billing@" + vendor.split()[0].lower() + "-example.com",
        "/Producer": producer,
        "/Creator": producer,
        "/CreationDate": creation,
        "/ModDate": creation,
    })
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), {"label": label, "planted": planted}


# ----------------------------------------------------------------------
# Theme: custom CSS for a polished, branded look
# ----------------------------------------------------------------------

THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stMarkdown, button, input, textarea, select { font-family: 'Inter', sans-serif !important; }
.stApp { background: #f6f8fc; }
.block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 880px; }
#MainMenu, [data-testid="stToolbar"], [data-testid="stDecoration"] { display:none !important; }
header { visibility:hidden; height:0; }
footer { visibility:hidden; }

/* hero */
.hero {
  background: linear-gradient(135deg, #16306b 0%, #2E75B6 62%, #3a8fd0 100%);
  color:#fff; padding: 38px 36px 32px; border-radius: 22px; margin-bottom: 26px;
  box-shadow: 0 16px 40px rgba(22,48,107,.30); position:relative; overflow:hidden;
}
.hero::after { content:""; position:absolute; right:-60px; top:-60px; width:260px; height:260px;
  background:radial-gradient(circle, rgba(255,255,255,.16), transparent 70%); }
.hero-badge { display:inline-block; background:rgba(255,255,255,.18); color:#fff; font-size:11px;
  font-weight:700; letter-spacing:.14em; padding:6px 13px; border-radius:20px; margin-bottom:16px; }
.hero h1 { color:#fff !important; margin:0; font-weight:800; font-size:2.15rem; line-height:1.12; letter-spacing:-.02em; }
.hero p { color:#dce8f7; margin:14px 0 0; font-size:1.02rem; max-width:600px; line-height:1.55; }
.pills { margin-top:20px; display:flex; flex-wrap:wrap; gap:9px; position:relative; z-index:1; }
.pills span { background:rgba(255,255,255,.15); color:#fff; font-size:12.5px; font-weight:600;
  padding:7px 13px; border-radius:20px; border:1px solid rgba(255,255,255,.14); }

/* headings */
h1,h2,h3 { letter-spacing:-.01em; }
.stMarkdown h3 { color:#16306b; font-weight:700; }

/* tabs as a segmented control */
.stTabs [data-baseweb="tab-list"] { gap:6px; background:#e9eff8; padding:6px; border-radius:14px; }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display:none; }
.stTabs [data-baseweb="tab"] { border-radius:10px; padding:9px 20px; font-weight:600; color:#4a5a70; }
.stTabs [aria-selected="true"] { background:#fff; color:#16306b !important; box-shadow:0 2px 8px rgba(22,48,107,.12); }

/* buttons */
.stButton>button { border-radius:11px; font-weight:600; padding:9px 20px; border:1px solid #d7e2f0;
  background:#fff; color:#1f3c88; transition:all .15s ease; }
.stButton>button:hover { border-color:#2E75B6; transform:translateY(-1px); box-shadow:0 6px 16px rgba(46,117,182,.18); }
.stButton>button[kind="primary"] { background:linear-gradient(135deg,#2E75B6,#16306b); color:#fff; border:none;
  box-shadow:0 6px 16px rgba(22,48,107,.28); }
.stDownloadButton>button { border-radius:11px; font-weight:600; }

/* inputs */
.stTextInput input, .stTextArea textarea, .stNumberInput input, .stSelectbox div[data-baseweb="select"] > div {
  border-radius:11px !important; }
[data-testid="stFileUploaderDropzone"] { border-radius:14px; border:1.5px dashed #b9cde4; background:#f7fafd; }

/* cards: expanders + metrics */
div[data-testid="stExpander"] { border:1px solid #e6ecf3; border-radius:16px; background:#fff;
  box-shadow:0 1px 3px rgba(20,40,80,.04); overflow:hidden; }
div[data-testid="stExpander"] summary { font-weight:600; padding:4px 2px; }
div[data-testid="stMetric"] { background:#fff; padding:16px 18px; border-radius:16px; border:1px solid #e2e9f3;
  box-shadow:0 1px 3px rgba(20,40,80,.04); }

.app-foot { text-align:center; color:#8a97a6; font-size:12px; margin-top:34px; padding-top:14px; border-top:1px solid #e6ecf2; }
</style>
"""

HERO_HTML = """
<div class="hero">
  <div class="hero-badge">FRAUD DETECTION</div>
  <h1>Catch fake documents before they cost you.</h1>
  <p>Upload an invoice, ID, or receipt. The engine cross-checks the visible text, the hidden metadata, and your records, and flags exactly what does not add up.</p>
  <div class="pills"><span>PDF &amp; image OCR</span><span>Metadata forensics</span><span>Phishing email check</span><span>Instant risk report</span></div>
</div>
"""


# ----------------------------------------------------------------------
# Streamlit UI
# ----------------------------------------------------------------------

def _document_scan_ui(st):
    st.caption("Upload a document (PDF or image, including iPhone HEIC), or "
               "click the sample button below to test it instantly.")

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

    st.markdown("**No file handy? Generate a random test invoice:**")
    sc1, sc2 = st.columns([2, 1])
    kind_label = sc1.selectbox(
        "Sample type", ["Fraudulent", "Clean", "Surprise me"],
        label_visibility="collapsed")
    if sc2.button("🧪 Generate & scan"):
        kind = {"Fraudulent": "fraud", "Clean": "clean"}.get(
            kind_label, _random.choice(["fraud", "clean"]))
        try:
            pdf_bytes, info = build_sample_invoice_bytes(kind)
            st.session_state["sample_pdf"] = pdf_bytes
            st.session_state["sample_info"] = info
        except Exception as e:
            st.error(f"Could not build sample: {e}")

    sample_pdf = st.session_state.get("sample_pdf")
    if sample_pdf:
        info = st.session_state.get("sample_info", {})
        truth = info.get("label", "unknown")
        st.download_button(
            "Download this sample (test_invoice.pdf)", sample_pdf,
            file_name="test_invoice.pdf", mime="application/pdf")
        if truth == "fraudulent":
            st.caption("Planted (this invoice IS fraudulent): "
                       + "; ".join(info.get("planted", [])) +
                       ". The scan below should flag it (MEDIUM for one "
                       "anomaly, HIGH for two).")
        elif truth == "clean":
            st.caption("This invoice is genuine: metadata agrees with the page "
                       "and uses billing software. The scan below should read LOW.")

    IMG_TYPES = ["pdf", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp",
                 "gif", "heic", "heif"]

    with st.expander("📚 Batch scan (several files at once)"):
        batch = st.file_uploader("Upload multiple documents", type=IMG_TYPES,
                                 accept_multiple_files=True, key="batch_files")
        if batch:
            approved_b = vendor_text.splitlines() if vendor_text else None
            rows, inv_pairs = [], []
            for bf in batch:
                try:
                    bdata = bf.read()
                    if bf.name.lower().endswith(".pdf"):
                        btext, bmeta = extract_from_pdf(bdata)
                    else:
                        btext, bmeta = extract_from_image(bdata)
                except Exception as e:
                    rows.append({"File": bf.name, "Risk": "ERROR", "Score": 0,
                                 "Invoice #": "-", "Top issue": str(e)[:40]})
                    continue
                bfind, bscore = evaluate(btext, bmeta, approved_vendors=approved_b,
                                         claims_to_be_original=claims_original)
                inv = find_invoice_number(btext)
                inv_pairs.append((bf.name, inv))
                rows.append({
                    "File": bf.name, "Risk": risk_band(bscore)[0],
                    "Score": bscore, "Invoice #": inv or "-",
                    "Top issue": bfind[0]["title"] if bfind else "none"})
            dups = duplicate_invoice_numbers(inv_pairs)
            if dups:
                st.warning("Duplicate invoice numbers across files (possible "
                           "double billing): " + ", ".join(sorted(dups)))
            st.dataframe(rows, use_container_width=True)
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
            st.download_button("Download results (CSV)", buf.getvalue(),
                               file_name="scan_results.csv", mime="text/csv")

    st.markdown("**Or scan one file in detail:**")
    uploaded = st.file_uploader(
        "Upload an invoice, receipt, ID, or record", type=IMG_TYPES,
        help="PDFs and images (including iPhone HEIC) are supported.",
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
    mc1, mc2 = st.columns([1, 2])
    mc1.metric("Risk score", f"{score}/100")
    mc2.markdown(f"### :{color}[{band}]")
    mc2.write(summary)
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


def _email_check_ui(st):
    st.caption("Paste a suspicious email (subject and body). This flags common "
               "phishing signals: urgent language, requests for passwords or "
               "payment, and risky links. It is a heuristic aid, not proof.")

    if st.button("Load a sample phishing email"):
        st.session_state["email_text"] = SAMPLE_PHISHING

    email_text = st.text_area("Email text", height=220, key="email_text")
    sender = st.text_input("Sender address (optional)",
                           placeholder="support@paypa1-security.com")

    if not (email_text or "").strip():
        st.info("Paste an email, or load the sample above, to check it.")
        return

    findings, score = check_email(email_text, sender)
    band, summary = risk_band(score)
    color = {"HIGH": "red", "MEDIUM": "orange", "LOW": "green"}[band]
    mc1, mc2 = st.columns([1, 2])
    mc1.metric("Phishing risk", f"{score}/100")
    mc2.markdown(f"### :{color}[{band}]")
    mc2.write(summary)
    st.progress(score / 100)

    st.subheader("Signals")
    if not findings:
        st.success("No common phishing signals found.")
    else:
        for f in findings:
            icon = {"high": "🔴", "medium": "🟠", "low": "🟡"}[f["level"]]
            with st.expander(f"{icon}  {f['title']}", expanded=f["level"] == "high"):
                st.write(f["detail"])

    st.caption("A clean result is not a guarantee. When unsure, do not click "
               "links or reply. Verify with the sender through a known channel.")


def main():
    import streamlit as st

    st.set_page_config(page_title="Fraud Scanner", page_icon="🔎",
                       layout="centered")
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    st.markdown(HERO_HTML, unsafe_allow_html=True)

    doc_tab, email_tab = st.tabs(["📄 Document scan", "📧 Email check"])
    with doc_tab:
        _document_scan_ui(st)
    with email_tab:
        _email_check_ui(st)

    st.markdown(
        '<div class="app-foot">Cross-Modal Inconsistency Scanner · '
        'fraud-ai-detection.com · a signal, not a verdict — always review.</div>',
        unsafe_allow_html=True)


if __name__ == "__main__":
    main()
