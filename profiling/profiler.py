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


def save_profile(profile: dict, run_id: str, profile_dir: Path = PROFILE_DIR) -> Path:
    """Persist a profile as JSON, keyed by run_id, so the schema-drift rule
    can load the most recent prior profile as a baseline."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    out_path = profile_dir / f"{run_id}.json"
    out_path.write_text(json.dumps(profile, indent=2))

    latest_path = profile_dir / "latest.json"
    latest_path.write_text(json.dumps(profile, indent=2))

    return out_path


def load_profile(run_id: str = "latest", profile_dir: Path = PROFILE_DIR) -> dict | None:
    path = profile_dir / f"{run_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())
