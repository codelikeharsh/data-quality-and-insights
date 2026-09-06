"""
Data profiling: a per-column statistical summary of any DataFrame.

This is the "know your data" step every governance process needs before
judging it — it's also what the schema-drift quality rule compares against
run-to-run (see quality/rules.py::schema_drift_rule).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from config import PROFILE_DIR


def _numeric_summary(series: pd.Series) -> dict:
    clean = series.dropna()
    if clean.empty:
        return {"min": None, "max": None, "mean": None, "std": None}
    return {
        "min": float(clean.min()),
        "max": float(clean.max()),
        "mean": round(float(clean.mean()), 2),
        "std": round(float(clean.std()), 2) if len(clean) > 1 else 0.0,
    }


def _text_summary(series: pd.Series) -> dict:
    clean = series.dropna().astype(str)
    return {
        "unique_count": int(clean.nunique()),
        "unique_values": sorted(clean.unique().tolist()),
    }


def profile_dataframe(df: pd.DataFrame) -> dict:
    """Compute a per-column profile: dtype, null count/%, plus numeric
    (min/max/mean/std) or text (unique count/values) stats as appropriate.
    """
    n_rows = len(df)
    columns = {}

    for col in df.columns:
        series = df[col]
        null_count = int(series.isna().sum())
        col_profile = {
            "dtype": str(series.dtype),
            "null_count": null_count,
            "null_pct": round((null_count / n_rows) * 100, 2) if n_rows else 0.0,
        }

        if pd.api.types.is_numeric_dtype(series):
            col_profile.update(_numeric_summary(series))
        else:
            col_profile.update(_text_summary(series))

        columns[col] = col_profile

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "row_count": n_rows,
        "columns": columns,
    }


def _safe_dataset_key(dataset_name: str) -> str:
    """Filesystem-safe stand-in for a dataset name, used only for the
    per-dataset "latest" pointer file — collisions here just mean two very
    similarly-named datasets share a schema-drift baseline, not data loss."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in dataset_name) or "default"


def save_profile(
    profile: dict, run_id: str, dataset_name: str = "default", profile_dir: Path = PROFILE_DIR
) -> Path:
    """Persist a profile as JSON, keyed by run_id, and update that
    dataset's "latest" pointer so the NEXT run of the SAME dataset (not
    just any dataset) has an accurate schema-drift baseline. Without the
    per-dataset pointer, ingesting dataset B right after dataset A would
    make schema_drift_rule compare B's columns against A's — a false
    positive on every column, not a real schema change.
    """
    profile_dir.mkdir(parents=True, exist_ok=True)
    out_path = profile_dir / f"{run_id}.json"
    out_path.write_text(json.dumps(profile, indent=2))

    latest_path = profile_dir / f"latest__{_safe_dataset_key(dataset_name)}.json"
    latest_path.write_text(json.dumps(profile, indent=2))

    return out_path


def load_profile(
    run_id: str = "latest", dataset_name: str = "default", profile_dir: Path = PROFILE_DIR
) -> dict | None:
    """Load a stored profile by run_id, or the given dataset's most recent
    profile when run_id == "latest" (the default)."""
    if run_id == "latest":
        path = profile_dir / f"latest__{_safe_dataset_key(dataset_name)}.json"
    else:
        path = profile_dir / f"{run_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())
