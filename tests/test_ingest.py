from pathlib import Path

import pandas as pd
import pytest

from ingest import load_structured
from ingest.structured import (
    guess_all_period_like_columns,
    guess_entity_column,
    guess_id_like_numeric_columns,
    guess_period_column,
)

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


def test_guess_entity_column_ignores_low_cardinality_status_flags():
    """Regression test: a real orders dataset had several near-worthless
    3-5-value 'status flag' columns (shipping mode, region, segment)
    alongside a genuinely meaningful 17-value product-subcategory column.
    Picking 'lowest ratio wins' with no floor chose a 3-value column,
    grouping outlier detection into 3 giant, unrelated buckets and
    producing thousands of false-positive outliers."""
    n = 300
    df = pd.DataFrame(
        {
            "ship_mode": (["Air", "Truck", "Mail"] * n)[:n],  # 3 unique — a status flag
            "region": (["East", "West", "North", "South"] * n)[:n],  # 4 unique
            # 15 unique, evenly spread — the genuinely meaningful grouping dimension
            "product_sub_category": [f"Category {i % 15}" for i in range(n)],
        }
    )
    assert guess_entity_column(df) == "product_sub_category"


def test_guess_period_column_rejects_near_continuous_dates():
    """Regression test: a real dataset's 'order_date' column had 1,419
    distinct individual calendar dates across 9,426 rows — matched the
    period name pattern, but treating individual days as 'the reporting
    period' made group_completeness_rule check whether every product
    subcategory had an order on literally every single day, producing
    17,571 false 'missing' flags. A column this fine-grained isn't a
    reporting period."""
    n = 500
    df = pd.DataFrame(
        {
            # ~450 distinct dates across 500 rows — a per-row timestamp, not a period
            "order_date": [f"2026-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}-{i}" for i in range(n)],
        }
    )
    assert guess_period_column(df) is None


def test_guess_period_column_accepts_coarse_period():
    df = pd.DataFrame({"month": ["2026-01"] * 20 + ["2026-02"] * 20 + ["2026-03"] * 20})
    assert guess_period_column(df) == "month"


def test_guess_all_period_like_columns_finds_every_match():
    df = pd.DataFrame({"order_date": ["2026-01-01"], "ship_date": ["2026-01-02"], "amount": [10]})
    assert guess_all_period_like_columns(df) == {"order_date", "ship_date"}


def test_guess_id_like_numeric_columns_excludes_identifiers():
    """An ID column isn't a measurement — 'statistically far from other
    IDs' is meaningless. Regression test: a real dataset's sequential
    'row_id' column got flagged with hundreds of false outlier issues."""
    df = pd.DataFrame(
        {
            "row_id": range(100),
            "customer_id": range(1000, 1100),
            "postal_code": [90210 + i for i in range(100)],
            "unit_price": [i * 1.5 for i in range(100)],
        }
    )
    id_like = guess_id_like_numeric_columns(df)
    assert id_like == {"row_id", "customer_id", "postal_code"}
    assert "unit_price" not in id_like
