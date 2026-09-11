from pathlib import Path

import pytest

from ingest import load_structured

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "samples" / "sample_power_data.csv"


def test_load_structured_shape():
    df = load_structured(SAMPLE)
    assert list(df.columns) == [
        "month",
        "state_name",
        "energy_requirement_mu",
        "energy_availability_mu",
    ]
    assert len(df) == 62  # 21 states x 3 months, minus Bihar missing in Feb


def test_load_structured_strips_whitespace(tmp_path):
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "month,state_name,energy_requirement_mu,energy_availability_mu\n"
        "2026-01, Bihar ,100,95\n"
    )
    df = load_structured(csv_path)
    assert df.loc[0, "state_name"] == "Bihar"


def test_load_structured_coerces_numeric():
    df = load_structured(SAMPLE)
    assert df["energy_requirement_mu"].dtype.kind == "f"
    assert df["energy_availability_mu"].dtype.kind == "f"


def test_load_structured_accepts_arbitrary_schema(tmp_path):
    """The loader has no fixed expected columns — any CSV shape works."""
    csv_path = tmp_path / "retail_sales.csv"
    csv_path.write_text(
        "Store Name,Units Sold,Revenue (USD)\n"
        "Downtown, 120, 3400.50\n"
        "Uptown, 80, 2100.00\n"
    )
    df = load_structured(csv_path)
    assert list(df.columns) == ["store_name", "units_sold", "revenue_usd"]
    assert df["units_sold"].dtype.kind == "f"
    assert df["revenue_usd"].dtype.kind == "f"
    assert df.loc[0, "store_name"] == "Downtown"


def test_load_structured_rejects_oversized_file(tmp_path, monkeypatch):
    """A file over the configured size limit fails fast with a clear error
    instead of risking an out-of-memory crash partway through loading it —
    see ingest/structured.py::load_structured's docstring."""
    import ingest.structured as structured_module

    monkeypatch.setattr(structured_module, "MAX_UPLOAD_SIZE_MB", 0.0001)  # ~100 bytes
    csv_path = tmp_path / "too_big.csv"
    csv_path.write_text("a,b,c\n" + "1,2,3\n" * 100)

    with pytest.raises(ValueError, match="exceeds"):
        load_structured(csv_path)


def test_load_structured_handles_windows_1252_encoding(tmp_path):
    """A CSV exported from Excel on Windows is commonly cp1252, not UTF-8 —
    this regressed in production: a file containing '(TM)' (byte 0x99 in
    cp1252) failed with 'utf-8 codec can't decode byte 0x99'."""
    csv_path = tmp_path / "windows_export.csv"
    content = "product,price\nSuperWidget™,19.99\n"  # ™ = (TM) symbol
    csv_path.write_bytes(content.encode("cp1252"))

    df = load_structured(csv_path)
    assert df.loc[0, "product"] == "SuperWidget™"
    assert df.loc[0, "price"] == 19.99
