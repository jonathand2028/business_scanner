"""
Unit tests for the cross-modal inconsistency scanner.

Run:  pytest -q
These cover the pure logic (date parsing, metadata reasoning, scoring) and the
built-in sample generator, with no Streamlit needed.
"""

import app


def test_find_dates_formats():
    found = app.find_dates(
        "Invoice Date: Jan 2026, also March 3, 2026 and 06/10/2026 and 2026-02-15")
    raws = [r for r, _ in found]
    assert "Jan 2026" in raws
    assert "March 3, 2026" in raws
    assert "06/10/2026" in raws
    assert "2026-02-15" in raws


def test_parse_metadata_date_pdf_and_exif():
    assert app.parse_metadata_date("D:20260615120000Z").date().isoformat() == "2026-06-15"
    assert app.parse_metadata_date("2026:03:03 10:00:00").date().isoformat() == "2026-03-03"
    assert app.parse_metadata_date("") is None


def test_software_is_editor():
    assert app.software_is_editor("Adobe Photoshop 25.0")
    assert app.software_is_editor("GIMP 2.10")
    assert not app.software_is_editor("Microsoft Word")
    assert not app.software_is_editor(None)


def test_evaluate_flags_fraud_case():
    text = "Invoice Date: January 2026  Vendor: Shady LLC  Total: $5,000"
    meta = {"creation_date": "D:20260610000000", "software": "Adobe Photoshop",
            "has_metadata": True}
    findings, score = app.evaluate(text, meta, approved_vendors=["Acme"])
    titles = {f["title"] for f in findings}
    assert "Printed date is older than the file itself" in titles
    assert "Edited in image/graphics software" in titles
    assert app.risk_band(score)[0] == "HIGH"


def test_evaluate_clean_case_scores_low():
    text = "Invoice Date: June 2026  Vendor: Acme Supplies  Total: $200"
    meta = {"creation_date": "D:20260605000000", "software": "QuickBooks",
            "has_metadata": True}
    findings, score = app.evaluate(text, meta, approved_vendors=["Acme Supplies"])
    assert score == 0
    assert app.risk_band(score)[0] == "LOW"


def test_missing_metadata_is_flagged():
    findings, score = app.evaluate("hello", {"has_metadata": False})
    assert any("Hidden file data is missing" in f["title"] for f in findings)


def test_sample_fraud_invoice_flags_and_clean_does_not():
    for _ in range(8):
        data, info = app.build_sample_invoice_bytes("fraud")
        text, meta = app.extract_from_pdf(data)
        _, score = app.evaluate(text, meta, claims_to_be_original=True)
        assert info["label"] == "fraudulent"
        assert score >= 20  # at least MEDIUM

    for _ in range(8):
        data, info = app.build_sample_invoice_bytes("clean")
        text, meta = app.extract_from_pdf(data)
        _, score = app.evaluate(text, meta, claims_to_be_original=True)
        assert info["label"] == "clean"
        assert score == 0
