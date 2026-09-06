"""
Tests for the OCR ingestion path (ingest/unstructured.py). Require
tesseract/poppler to be installed on the system — same as production would
need for this feature — so they self-skip when those binaries aren't
available, rather than failing pytest in an environment that never installed
them (e.g. a minimal CI image without the OCR system packages).
"""
import shutil

import pytest
from PIL import Image, ImageDraw

from ingest.unstructured import load_unstructured, EXPECTED_COLUMNS
from quality.rules import consistency_rule, validity_rule
from tests.conftest import report_font as _report_font

pytestmark = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="tesseract not installed"
)


def _render_report(lines, path):
    font = _report_font()
    img = Image.new("RGB", (800, 50 * (len(lines) + 1)), color="white")
    draw = ImageDraw.Draw(img)
    y = 15
    for line in lines:
        draw.text((15, y), line, fill="black", font=font)
        y += 50
    img.save(path)
    return path


def test_load_unstructured_extracts_clean_rows(tmp_path):
    path = _render_report(
        ["Assam 1600 1580", "Bihar 4300 4100"], tmp_path / "report.png"
    )
    df = load_unstructured(path, month="2026-04")

    assert list(df.columns) == EXPECTED_COLUMNS + ["extraction_confidence"]
    assert len(df) == 2
    assert set(df["state_name"]) == {"Assam", "Bihar"}
    assert (df["extraction_confidence"] == "low").all()


def test_load_unstructured_captures_negative_values(tmp_path):
    """A negative reading must survive extraction so validity_rule can catch
    it — this regressed once (the regex didn't allow a leading '-')."""
    path = _render_report(["Jharkhand 2400 -50"], tmp_path / "report.png")
    df = load_unstructured(path, month="2026-04")

    assert len(df) == 1
    assert df.loc[0, "energy_availability_mu"] == -50.0

    issues = validity_rule(df)
    assert len(issues) == 1
    assert issues[0].column == "energy_availability_mu"


def test_load_unstructured_naming_variant_flows_into_consistency_rule(tmp_path):
    # consistency_rule does self-referential near-duplicate detection (no
    # external reference list — see quality/rules.py), so it needs to see
    # the common spelling repeated before a rare variant reads as a likely
    # typo of it, same as the CSV-ingestion equivalent of this scenario.
    # Keep this to 3 lines: tesseract's layout analysis starts grouping text
    # into columns instead of rows once there are enough repeated lines,
    # which would break the row-based regex extractor being tested here —
    # that's a real limitation of this deliberately narrow OCR path (see
    # ingest/unstructured.py's module docstring), not something to paper
    # over in the test.
    path = _render_report(
        ["Odisha 4560 4490", "Odisha 4560 4490", "Orissa 4600 4550"],
        tmp_path / "report.png",
    )
    df = load_unstructured(path, month="2026-04")

    issues = consistency_rule(df)
    assert len(issues) == 1
    assert "Orissa" in issues[0].description


def test_load_unstructured_handles_corrupt_file_gracefully(tmp_path):
    bad_file = tmp_path / "corrupt.png"
    bad_file.write_bytes(b"not a real image")

    df = load_unstructured(bad_file, month="2026-04")

    assert df.empty
    assert list(df.columns) == EXPECTED_COLUMNS + ["extraction_confidence"]


def test_load_unstructured_pdf_path(tmp_path):
    png_path = _render_report(["Goa 430 425"], tmp_path / "report.png")
    pdf_path = tmp_path / "report.pdf"
    Image.open(png_path).convert("RGB").save(pdf_path, "PDF")

    df = load_unstructured(pdf_path, month="2026-04")
    assert len(df) == 1
    assert df.loc[0, "state_name"] == "Goa"
