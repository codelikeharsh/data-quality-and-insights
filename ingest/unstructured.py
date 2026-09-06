"""
Loader for unstructured sources: scanned/handwritten PDF or image reports.

Real-world motivation: not every state submits a clean CSV. Some send a
scanned tabular report (a photographed register page, a faxed PDF). This
loader OCRs the document and heuristically extracts rows so they can flow
into the same pipeline as a structured file. OCR is inherently unreliable,
so every row extracted this way is tagged with an extraction_confidence
column instead of being silently trusted like a CSV row would be.
"""
import re
from pathlib import Path

import pandas as pd

from config import CANONICAL_STATES

# This OCR path is deliberately narrow (see module docstring): it extracts
# "entity, number, number" rows shaped like a power-supply report, not
# arbitrary table structure. EXPECTED_COLUMNS here describes only ITS output
# shape, unlike ingest.structured.load_structured, which accepts any schema.
EXPECTED_COLUMNS = ["month", "state_name", "energy_requirement_mu", "energy_availability_mu"]

# Matches a line like: "Odisha 4560 4490" or "Odisha, 4560, 4490"
# i.e. a state name followed by two numbers (int or float, optionally
# negative — a negative energy_availability_mu is exactly the kind of
# invalid value the validity rule needs to see, not silently drop).
_ROW_PATTERN = re.compile(
    r"([A-Za-z][A-Za-z .&]+?)[\s,]+(-?[\d,]+(?:\.\d+)?)[\s,]+(-?[\d,]+(?:\.\d+)?)"
)

# Sorted longest-first so "Andaman and Nicobar Islands" matches before "Delhi"
# style substrings could confuse a shorter greedy match.
_CANONICAL_SORTED = sorted(CANONICAL_STATES, key=len, reverse=True)


def _closest_state_hint(raw_name: str) -> str:
    """Best-effort cleanup of an OCR'd state name: trims noise characters.
    Full fuzzy resolution against the canonical list happens later in the
    consistency quality rule — this loader only needs to produce a plausible
    string, not a definitive one.
    """
    return re.sub(r"\s+", " ", raw_name).strip(" .,-")


def _extract_rows_from_text(text: str, month: str | None) -> list[dict]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _ROW_PATTERN.search(line)
        if not match:
            continue
        raw_state, raw_req, raw_avail = match.groups()
        state_name = _closest_state_hint(raw_state)
        try:
            requirement = float(raw_req.replace(",", ""))
            availability = float(raw_avail.replace(",", ""))
        except ValueError:
            continue

        rows.append(
            {
                "month": month or "unknown",
                "state_name": state_name,
                "energy_requirement_mu": requirement,
                "energy_availability_mu": availability,
                "extraction_confidence": "low",
            }
        )
    return rows


def _ocr_text(file_path: Path) -> str:
    """Run OCR over an image or PDF. Isolated in its own function so it's the
    single point of failure to catch — missing tesseract/poppler binaries or
    a corrupt file shouldn't crash the pipeline, just yield zero rows."""
    suffix = file_path.suffix.lower()

    import pytesseract

    if suffix == ".pdf":
        from pdf2image import convert_from_path

        pages = convert_from_path(str(file_path))
        return "\n".join(pytesseract.image_to_string(page) for page in pages)

    from PIL import Image

    image = Image.open(file_path)
    return pytesseract.image_to_string(image)


def load_unstructured(file_path: str | Path, month: str | None = None) -> pd.DataFrame:
    """OCR a scanned PDF/image tabular report and extract rows into the same
    DataFrame shape as load_structured, plus an extraction_confidence column.

    Never raises on OCR/extraction failure — a scan that can't be read
    yields an empty-but-correctly-shaped DataFrame so the caller can report
    "0 rows extracted, low confidence" instead of crashing the ingest run.
    """
    file_path = Path(file_path)

    try:
        text = _ocr_text(file_path)
    except Exception:
        return pd.DataFrame(columns=EXPECTED_COLUMNS + ["extraction_confidence"])

    rows = _extract_rows_from_text(text, month)

    if not rows:
        return pd.DataFrame(columns=EXPECTED_COLUMNS + ["extraction_confidence"])

    df = pd.DataFrame(rows)
    return df.reset_index(drop=True)
