"""
Labeled evaluation dataset for the fraud scanner.

Every case carries a ground-truth label, so the detector's output can be
measured instead of eyeballed. Cases are built as (text, metadata) pairs --
the same inputs `app.evaluate()` receives after extraction -- which keeps the
evaluation focused on the detection logic rather than on PDF parsing.

The set deliberately includes hard cases in both directions:

  * clean documents that trip a single heuristic (stripped metadata on a
    legitimate export, a genuine new vendor missing from the approved list)
  * fraudulent documents whose only tell is subtle (a small edit window)

A dataset where everything is obvious would report near-perfect scores and
tell us nothing useful.
"""

from datetime import datetime, timedelta

APPROVED_VENDORS = ["Acme Supply Co", "Northwind Traders", "Globex Corporation"]

_BASE = datetime(2026, 6, 15)


def _d(offset_days):
    return (_BASE + timedelta(days=offset_days)).strftime("%B %d, %Y")


def _pdf_date(offset_days):
    """PDF-style metadata timestamp, e.g. D:20260615120000Z"""
    return (_BASE + timedelta(days=offset_days)).strftime("D:%Y%m%d120000Z")


def _invoice(vendor, printed_date, number="INV-4471", total="$4,820.00"):
    return (
        f"{vendor}\n"
        f"123 Commerce Street, Chicago, IL 60601\n\n"
        f"INVOICE\n"
        f"Invoice Number: {number}\n"
        f"Invoice Date: {printed_date}\n\n"
        f"Description                Qty     Amount\n"
        f"Consulting services         40    {total}\n\n"
        f"Total Due: {total}\n"
    )


# ----------------------------------------------------------------------
# Cases
#
# Each: (case_id, text, metadata, approved_vendors, claims_original, label,
#        difficulty, note)
# label: "fraud" | "clean"
# ----------------------------------------------------------------------

CASES = []


def case(cid, text, metadata, label, difficulty="normal", note="",
         vendors=APPROVED_VENDORS, claims_original=True):
    CASES.append({
        "id": cid,
        "text": text,
        "metadata": metadata,
        "vendors": vendors,
        "claims_original": claims_original,
        "label": label,
        "difficulty": difficulty,
        "note": note,
    })


# ---------- CLEAN: straightforward legitimate documents ----------

case(
    "clean_standard_01",
    _invoice("Acme Supply Co", _d(0)),
    {"creation_date": _pdf_date(0), "mod_date": _pdf_date(0),
     "software": "Acme Billing System v4", "has_metadata": True},
    "clean", note="Printed date matches file date, approved vendor, system export.",
)

case(
    "clean_standard_02",
    _invoice("Northwind Traders", _d(-3), number="INV-8890"),
    {"creation_date": _pdf_date(-3), "mod_date": _pdf_date(-3),
     "software": "QuickBooks", "has_metadata": True},
    "clean", note="Small, plausible gap between print and file date.",
)

case(
    "clean_standard_03",
    _invoice("Globex Corporation", _d(-10), number="INV-2210"),
    {"creation_date": _pdf_date(-10), "mod_date": _pdf_date(-9),
     "software": "SAP Export", "has_metadata": True},
    "clean", note="Modified one day after creation -- within tolerance.",
)

# ---------- CLEAN but hard: legitimate documents that trip one heuristic ----------

case(
    "clean_hard_due_date",
    _invoice("Acme Supply Co", _d(0)) + f"\nPayment Due: {_d(30)}\n",
    {"creation_date": _pdf_date(0), "mod_date": _pdf_date(0),
     "software": "Acme Billing System v4", "has_metadata": True},
    "clean", difficulty="hard",
    note="Has a future due date. Tests that the earliest date is used as the "
         "invoice date rather than flagging a legitimate payment term.",
)

case(
    "clean_hard_stripped_meta",
    _invoice("Northwind Traders", _d(-1), number="INV-7712"),
    {"creation_date": None, "mod_date": None,
     "software": None, "has_metadata": False},
    "clean", difficulty="hard",
    note="Legitimate document whose metadata was stripped in transit (common "
         "with email gateways and print-to-PDF). Innocent but suspicious-looking.",
)

case(
    "clean_hard_new_vendor",
    _invoice("Initech Industries", _d(0), number="INV-3140"),
    {"creation_date": _pdf_date(0), "mod_date": _pdf_date(0),
     "software": "Xero", "has_metadata": True},
    "clean", difficulty="hard",
    note="Real invoice from a genuine new supplier not yet on the approved list.",
)

case(
    "clean_hard_scanned_original",
    _invoice("Globex Corporation", _d(-5), number="INV-5501"),
    {"creation_date": _pdf_date(-5), "mod_date": _pdf_date(-5),
     "software": "Canon ScanFront", "has_metadata": True},
    "clean", difficulty="hard",
    note="Scanner software in metadata -- must not be mistaken for an editor.",
)

case(
    "clean_hard_old_archived",
    _invoice("Acme Supply Co", _d(-400), number="INV-0091"),
    {"creation_date": _pdf_date(-400), "mod_date": _pdf_date(-400),
     "software": "Acme Billing System v3", "has_metadata": True},
    "clean", difficulty="hard",
    note="Genuinely old invoice pulled from the archive. Old is not fraudulent.",
)

# ---------- FRAUD: clear cases ----------

case(
    "fraud_backdated_01",
    _invoice("Acme Supply Co", _d(-120), number="INV-9001"),
    {"creation_date": _pdf_date(0), "mod_date": _pdf_date(0),
     "software": "Adobe Photoshop 2026", "has_metadata": True},
    "fraud", note="Backdated four months AND produced in Photoshop.",
)

case(
    "fraud_photoshop_01",
    _invoice("Northwind Traders", _d(-2), number="INV-9002"),
    {"creation_date": _pdf_date(-2), "mod_date": _pdf_date(-2),
     "software": "Adobe Photoshop 2026", "has_metadata": True},
    "fraud", note="Dates line up, but a supposed original came out of an editor.",
)

case(
    "fraud_canva_backdated",
    _invoice("Globex Corporation", _d(-90), number="INV-9003"),
    {"creation_date": _pdf_date(0), "mod_date": _pdf_date(1),
     "software": "Canva", "has_metadata": True},
    "fraud", note="Backdated, built in Canva, and edited after creation.",
)

case(
    "fraud_unknown_vendor_edited",
    _invoice("Definitely Real Supplies LLC", _d(-60), number="INV-9004"),
    {"creation_date": _pdf_date(0), "mod_date": _pdf_date(0),
     "software": "GIMP", "has_metadata": True},
    "fraud", note="Unknown vendor, backdated, edited in GIMP.",
)

case(
    "fraud_future_dated",
    _invoice("Acme Supply Co", _d(45), number="INV-9005"),
    {"creation_date": _pdf_date(0), "mod_date": _pdf_date(0),
     "software": "Acme Billing System v4", "has_metadata": True},
    "fraud", note="Invoice dated well after the file was created.",
)

case(
    "fraud_copy_paste_dates",
    _invoice("Northwind Traders", _d(-1), number="INV-9006")
    + "\nOriginal agreement dated March 12, 2019\nRenewed January 5, 2020\n",
    {"creation_date": _pdf_date(-1), "mod_date": _pdf_date(0),
     "software": "Adobe Illustrator", "has_metadata": True},
    "fraud", note="Editor software plus wildly inconsistent internal dates.",
)

# ---------- FRAUD but hard: subtle tells ----------

case(
    "fraud_hard_subtle_edit",
    _invoice("Acme Supply Co", _d(-2), number="INV-9007"),
    {"creation_date": _pdf_date(-2), "mod_date": _pdf_date(20),
     "software": "Acme Billing System v4", "has_metadata": True},
    "fraud", difficulty="hard",
    note="Only tell is that the file was modified 22 days after creation. "
         "Expected to be a hard miss -- documents the detector's blind spot.",
)

case(
    "fraud_hard_stripped_and_unknown",
    _invoice("Vertex Global Trading", _d(-4), number="INV-9008"),
    {"creation_date": None, "mod_date": None,
     "software": None, "has_metadata": False},
    "fraud", difficulty="hard",
    note="Metadata wiped and vendor unknown, but nothing internally contradicts.",
)

case(
    "fraud_hard_mild_backdate",
    _invoice("Globex Corporation", _d(-40), number="INV-9009"),
    {"creation_date": _pdf_date(0), "mod_date": _pdf_date(0),
     "software": "Globex ERP", "has_metadata": True},
    "fraud", difficulty="hard",
    note="Backdated just past the 30-day threshold, no other signal.",
)


# ----------------------------------------------------------------------
# Phishing email cases
# ----------------------------------------------------------------------

EMAIL_CASES = []


def email_case(cid, text, sender, label, difficulty="normal", note=""):
    EMAIL_CASES.append({
        "id": cid, "text": text, "sender": sender,
        "label": label, "difficulty": difficulty, "note": note,
    })


email_case(
    "phish_classic",
    "Subject: URGENT: Your account has been suspended\n\n"
    "We detected unusual activity. You must verify your account immediately "
    "to avoid permanent closure within 24 hours.\n"
    "Confirm your password here: http://198.51.100.23/secure-login\n"
    "Failure to act now will result in loss of access.",
    "security@paypa1-alerts.com", "phishing",
    note="Urgency, credential request, raw-IP link, lookalike sender.",
)

email_case(
    "phish_invoice_scam",
    "Subject: Outstanding payment - final notice\n\n"
    "Your invoice is overdue. Please make payment immediately via the link "
    "below to avoid suspension of services.\n"
    "https://bit.ly/pay-now-secure\n"
    "Wire transfer details attached. Act now.",
    "billing@acme-supply-invoices.net", "phishing",
    note="Urgency, payment request, URL shortener.",
)

email_case(
    "phish_credential_harvest",
    "Subject: Action required: confirm your account\n\n"
    "Dear user, our records show your login credentials expire today. "
    "Please log in and confirm your password as soon as possible.\n"
    "http://secure-login-verify.example.com/session",
    "it-helpdesk@uchicago-support.co", "phishing",
    note="Credential harvesting with plain-HTTP link.",
)

email_case(
    "legit_newsletter",
    "Subject: Your monthly statement is ready\n\n"
    "Hello Jonathan,\n\nYour June statement is now available. You can view it "
    "by signing in to your account through our website at your convenience.\n\n"
    "Thank you,\nAccounts Team",
    "statements@northwindtraders.com", "legitimate",
    note="No urgency, no link, no credential request.",
)

email_case(
    "legit_vendor_followup",
    "Subject: Following up on invoice INV-4471\n\n"
    "Hi Jonathan,\n\nJust checking in on the invoice we sent last week. "
    "Let me know if you need anything else from our side.\n\n"
    "Best,\nSarah\nAcme Supply Co",
    "sarah@acmesupply.com", "legitimate",
    note="Ordinary business correspondence.",
)

email_case(
    "legit_hard_urgent_real",
    "Subject: Time-sensitive: contract signature needed within 24 hours\n\n"
    "Hi Jonathan,\n\nOur legal team needs the signed contract back within "
    "24 hours to keep the project on schedule. Sorry for the short notice.\n\n"
    "Thanks,\nMichael",
    "michael@globexcorp.com", "legitimate", difficulty="hard",
    note="Legitimate email that genuinely is urgent. Tests over-reliance on "
         "urgency keywords.",
)
