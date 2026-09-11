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


# Real-world CSVs aren't always UTF-8 — a file exported from Excel on
# Windows is commonly Windows-1252, which trips pandas' UTF-8 default the
# moment it contains a curly quote, em-dash, or a (TM)/(R) symbol. Tried in
# order: utf-8-sig (plain UTF-8, and handles a leading BOM some tools add),
# then the common Windows export encoding, then latin-1 as a guaranteed-to-
# succeed last resort (it maps every byte 0-255 to a character, so it never
# raises — better to risk a mis-decoded rare character than to fail the
# whole ingest on an encoding guess).
_CSV_ENCODING_FALLBACKS = ("utf-8-sig", "cp1252", "latin-1")


def _read_csv_with_encoding_fallback(file_path: Path) -> pd.DataFrame:
    last_error: UnicodeDecodeError | None = None
    for encoding in _CSV_ENCODING_FALLBACKS:
        try:
            return pd.read_csv(file_path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    # Unreachable in practice — latin-1 never raises — but keeps this
    # honest about what happens if every fallback somehow fails.
    raise last_error


_PERIOD_NAME_PATTERN = re.compile(r"(month|date|year|period|quarter|week|fiscal)", re.IGNORECASE)


def guess_period_column(df: pd.DataFrame, max_unique_count: int = 60) -> str | None:
    """Best-effort guess at which column (if any) represents a reporting
    period ("month", "date", "fiscal_year", ...) — used together with
    guess_entity_column so run_pipeline can check "did every entity that
    ever reports also report THIS period?" without hardcoding either
    column's name. Name-based only (not a real date-parser) since a
    generic dataset's period column can be a plain label ("2026-02", "Q1")
    rather than a parseable date.

    `max_unique_count` caps how many distinct values a column can have and
    still count as a "period" — this matters because a name match alone
    doesn't distinguish a genuine reporting period (a handful of months or
    quarters) from a per-row timestamp (an "order_date" column with a
    near-distinct value for almost every row). This regressed in
    production: a real orders dataset's "order_date" column had 1,419
    distinct individual calendar dates, and group_completeness_rule
    dutifully checked whether every product subcategory had at least one
    order on literally every one of those 1,419 days — a nonsensical bar
    that produced 17,571 false "missing" flags. 60 covers the realistic
    range of genuine reporting periods (daily for ~2 months, weekly for a
    year, monthly for 5 years, quarterly, yearly) while excluding anything
    that's really a per-row date.
    """
    for col in df.columns:
        if _PERIOD_NAME_PATTERN.search(col):
            if df[col].nunique(dropna=True) > max_unique_count:
                continue  # too fine-grained to be a genuine reporting period
            return col
    return None


_ID_NAME_PATTERN = re.compile(r"(^id$|_id$|^id_|postal.?code|zip.?code)", re.IGNORECASE)


def guess_id_like_numeric_columns(df: pd.DataFrame) -> set[str]:
    """Numeric columns whose name looks like an identifier ("row_id",
    "customer_id", "postal_code", ...) rather than a measurement — these
    get excluded from outlier_rule's default column set. "This ID number
    is statistically far from other ID numbers" isn't a data quality
    signal; IDs aren't drawn from a distribution, they're just labels that
    happen to be numbers. This regressed in production: a real dataset's
    sequential "row_id" column got flagged as having hundreds of
    "statistical outliers" simply because grouping split the roughly-
    uniform 1..9426 range into uneven chunks, each with its own median —
    numerically true, semantically meaningless.

    Deliberately narrower than "every numeric column with a near-unique
    ratio" — a genuine measurement (e.g. a precise sensor reading) can also
    be near-unique, and un-flagging every such column would silently
    disable outlier detection on real measurements too. Name-based, same
    approach as guess_period_column, so it only fires on the specific
    pattern that actually means "this is a label, not a measurement".
    """
    numeric_cols = set(df.select_dtypes(include="number").columns)
    return {col for col in numeric_cols if _ID_NAME_PATTERN.search(col)}


def guess_all_period_like_columns(df: pd.DataFrame) -> set[str]:
    """Every column name matching the period pattern, not just the one
    guess_period_column picks as THE period — a dataset can have more than
    one date-ish column (e.g. "order_date" and "ship_date"), and every one
    of them should be excluded from guess_entity_column's candidates, not
    just the first. A date column becoming "the entity" makes no sense —
    the whole point of an entity column is a repeating identity to compare
    each group against its own history."""
    return {col for col in df.columns if _PERIOD_NAME_PATTERN.search(col)}


def guess_entity_column(
    df: pd.DataFrame, exclude: set[str] | None = None, min_unique_count: int = 10
) -> str | None:
    """Best-effort guess at which column (if any) identifies "the thing this
    row is about" — e.g. a state, a store, a product — so outlier detection
    can compare each entity against its own history instead of the whole
    column. Heuristic: among columns with AT LEAST `min_unique_count`
    distinct values, pick the one with the lowest unique-value ratio (still
    excluding a column where every value is unique — that's an ID, not a
    repeating entity).

    The min_unique_count floor matters more than it looks: a real dataset
    often has several very-low-cardinality "status flag" columns (a
    shipping mode with 3 values, a region with 4, a customer segment with
    4) sitting alongside a genuinely meaningful grouping dimension (a
    product subcategory with 17 values, a state with 49). Minimizing the
    ratio with NO floor picks whichever status flag happens to have the
    fewest values — grouping outlier detection into 3 giant, semantically
    meaningless buckets, which is *worse* than not grouping at all (it
    mixes unrelated sub-populations into one "normal" baseline and floods
    the result with false-positive outliers). This regressed in production
    on a real 9,426-row orders dataset: it picked a 3-value shipping-mode
    column over a 17-value product-subcategory column sitting right next
    to it, and outlier_rule flagged 7,660 issues as a result.

    `exclude` should be given the result of guess_period_column(df) — and
    ideally every OTHER column that also looks like a period, not just the
    one chosen as THE period (see run_pipeline.py) — when both are used
    together. A reporting-period column (e.g. "month") is very likely to
    ALSO have low cardinality, and without excluding it explicitly this
    heuristic would pick the period over the actual entity purely because
    it repeats even more.
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
        if nunique < min_unique_count or nunique == n:
            continue
        ratio = nunique / n
        if ratio < best_ratio:
            best_col, best_ratio = col, ratio

    return best_col


def load_structured(file_path: str | Path) -> pd.DataFrame:
    """Load a CSV or Excel file into a DataFrame, whatever columns it has.

    - Reads CSV with an encoding fallback chain (utf-8-sig -> cp1252 ->
      latin-1) instead of pandas' strict UTF-8 default, so a Windows/Excel-
      exported file with a curly quote or (TM) symbol doesn't hard-fail.
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
        df = _read_csv_with_encoding_fallback(file_path)
    elif suffix in (".xlsx", ".xls"):
        df = pd.read_excel(file_path)
    else:
        raise ValueError(f"Unsupported structured file type: {suffix}")

    df = _standardize_columns(df)

    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()

    df = _auto_coerce_numeric(df)

    return df.reset_index(drop=True)
