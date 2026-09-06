"""
Loader for "clean" structured sources: CSV and Excel files.

This is domain-agnostic: it does not require any particular column names.
The output shape (columns, dtypes) is whatever the source file actually
contains — every downstream module (profiling, quality rules, storage)
works against that inferred shape rather than a fixed schema, so both this
loader and ingest.unstructured.load_unstructured only need to agree on
"a DataFrame", not on specific column names.
"""
import re
from pathlib import Path

import pandas as pd

from config import MAX_UPLOAD_SIZE_MB

# A column is auto-coerced from text to numeric only when at least this
# fraction of its non-null values successfully parse as numbers — this is
# what lets "energy_requirement_mu" (all numeric) get typed correctly while
# a genuinely textual column like "state_name" or "notes" (which will fail
# to parse almost entirely) is left as text, without needing to know either
# column's name in advance.
_NUMERIC_COERCION_THRESHOLD = 0.9


def _standardize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase, strip, and snake_case column names so minor header drift
    (' Energy Requirement (MU) ' vs 'energy_requirement_mu') doesn't break
    downstream code that references columns by name."""
    df = df.copy()
    df.columns = (
        df.columns.str.strip()
        .str.lower()
        .str.replace(r"[^\w]+", "_", regex=True)
        .str.strip("_")
    )
    return df


def _auto_coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Try to convert every text column to numeric; keep the conversion only
    if it captures the great majority of the column's non-null values, so a
    handful of stray non-numeric entries become nulls the quality rules can
    flag, rather than the whole column silently staying text-typed.

    Also normalizes every already-numeric column to float64 — pandas would
    otherwise type a column int64 or float64 depending on whether THIS
    particular batch happens to contain a null, which would make
    schema_drift_rule fire on a batch that changed nothing but its null
    count.
    """
    df = df.copy()
    for col in df.select_dtypes(include="object").columns:
        non_null = df[col].dropna()
        if non_null.empty:
            continue
        coerced = pd.to_numeric(non_null, errors="coerce")
        if coerced.notna().mean() >= _NUMERIC_COERCION_THRESHOLD:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")

    for col in df.select_dtypes(include="number").columns:
        df[col] = df[col].astype("float64")

    return df


_PERIOD_NAME_PATTERN = re.compile(r"(month|date|year|period|quarter|week|fiscal)", re.IGNORECASE)


def guess_period_column(df: pd.DataFrame) -> str | None:
    """Best-effort guess at which column (if any) represents a reporting
    period ("month", "date", "fiscal_year", ...) — used together with
    guess_entity_column so run_pipeline can check "did every entity that
    ever reports also report THIS period?" without hardcoding either
    column's name. Name-based only (not a real date-parser) since a
    generic dataset's period column can be a plain label ("2026-02", "Q1")
    rather than a parseable date."""
    for col in df.columns:
        if _PERIOD_NAME_PATTERN.search(col):
            return col
    return None


def guess_entity_column(df: pd.DataFrame, exclude: set[str] | None = None) -> str | None:
    """Best-effort guess at which column (if any) identifies "the thing this
    row is about" — e.g. a state, a store, a product — so outlier detection
    can compare each entity against its own history instead of the whole
    column. Heuristic: the text column with the lowest unique-value ratio
    that still has more than one distinct value (a column where every value
    is unique is an ID, not a repeating entity — and one where every value
    is the SAME isn't a grouping dimension either).

    `exclude` should be given the result of guess_period_column(df) when
    both are used together (see run_pipeline.py) — a reporting-period
    column (e.g. "month") is very likely to ALSO have low cardinality, and
    without excluding it explicitly this heuristic would pick the period
    over the actual entity purely because it repeats even more.
    """
    exclude = exclude or set()
    best_col, best_ratio = None, 1.0
    n = len(df)
    if n == 0:
        return None

    for col in df.select_dtypes(include="object").columns:
        if col in exclude:
            continue
        nunique = df[col].nunique(dropna=True)
        if nunique <= 1 or nunique == n:
            continue
        ratio = nunique / n
        if ratio < best_ratio:
            best_col, best_ratio = col, ratio

    return best_col


def load_structured(file_path: str | Path) -> pd.DataFrame:
    """Load a CSV or Excel file into a DataFrame, whatever columns it has.

    - Strips whitespace from every string cell (a common source of
      consistency issues, e.g. "Odisha " vs "Odisha").
    - Standardizes column names.
    - Auto-detects and coerces numeric-looking text columns to numeric, so
      a stray non-numeric value becomes a null the quality rules can catch,
      rather than the whole column staying text-typed or raising deep in
      some later computation.

    The whole file is loaded into memory via pandas — no chunking/streaming
    (see README's "Known limitations"). Benchmarked at 1,000,000 rows / 28MB:
    ~2.5s wall time, ~150MB peak memory on a base MacBook Air. A file above
    MAX_UPLOAD_SIZE_MB fails fast with a clear error instead of risking an
    out-of-memory crash partway through — a real limit stated up front is
    better than an undocumented one discovered by a crash.
    """
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()

    size_mb = file_path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_UPLOAD_SIZE_MB:
        raise ValueError(
            f"File is {size_mb:.1f}MB, which exceeds the {MAX_UPLOAD_SIZE_MB}MB limit "
            f"(ingest/structured.py loads the whole file into memory — no streaming support "
            f"yet). Split the file, or raise MAX_UPLOAD_SIZE_MB in config.py if you have the "
            f"memory headroom to back it."
        )

    if suffix == ".csv":
        df = pd.read_csv(file_path)
    elif suffix in (".xlsx", ".xls"):
        df = pd.read_excel(file_path)
    else:
        raise ValueError(f"Unsupported structured file type: {suffix}")

    df = _standardize_columns(df)

    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()

    df = _auto_coerce_numeric(df)

    return df.reset_index(drop=True)
