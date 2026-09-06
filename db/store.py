"""
Persistence layer: takes the output of run_pipeline() (see run_pipeline.py)
and writes it to Postgres as a single transaction — the run record, every
ingested row (as JSON, so any dataset shape is storable without a schema
migration), every flagged issue, and a lineage record.

Kept separate from run_pipeline.py so the core pipeline logic stays testable
without a database (see tests/test_pipeline_end_to_end.py, which runs with
no DB involved at all).
"""
import math

import pandas as pd
from sqlalchemy.orm import Session

from db.models import DatasetRow, QualityRun, QualityIssue, DataLineage, DatasetProfile


def store_pipeline_result(db: Session, result: dict, df: pd.DataFrame) -> QualityRun:
    """Persist one pipeline run. `result` is the dict returned by
    run_pipeline.run_pipeline(); `df` is the ingested DataFrame (needed here
    because run_pipeline() doesn't return raw rows, only issues/score/profile).

    Runs as one transaction: either everything commits, or nothing does —
    a partially-stored run (e.g. rows but no matching quality_run) would
    corrupt the lineage this table exists to provide.
    """
    dataset_name = result.get("dataset_name", "default")

    run = QualityRun(
        run_id=result["run_id"],
        dataset_name=dataset_name,
        source_file=result["source_file"],
        health_score=result["health_score"]["score"],
        rows_processed=result["rows_processed"],
        rows_flagged=result["rows_flagged"],
    )
    db.add(run)

    # Stored so the NEXT run of this dataset's schema-drift baseline comes
    # from Postgres (shared across every backend instance) rather than this
    # process's own local disk — see db.models.DatasetProfile's docstring.
    if "profile" in result:
        db.add(
            DatasetProfile(
                run_id=result["run_id"],
                dataset_name=dataset_name,
                profile=result["profile"],
            )
        )

    for idx, row in df.iterrows():
        db.add(
            DatasetRow(
                row_index=int(idx),
                data=_json_safe_record(row.to_dict()),
                source_run_id=result["run_id"],
            )
        )

    for issue in result["issues"]:
        db.add(
            QualityIssue(
                run_id=result["run_id"],
                row_reference=str(issue["row_reference"]),
                column=issue["column"],
                issue_type=issue["issue_type"],
                description=issue["description"],
                severity=issue["severity"],
            )
        )

    db.add(
        DataLineage(
            source_file=result["source_file"],
            transformations_applied=[
                "load_structured",
                "profile_dataframe",
                "run_all_rules",
                "compute_health_score",
            ],
            destination_table="dataset_rows",
            run_id=result["run_id"],
        )
    )

    db.commit()
    db.refresh(run)
    return run


def _json_safe_record(record: dict) -> dict:
    """A DataFrame row's .to_dict() can contain NaN/NaT and numpy scalar
    types, neither of which round-trip cleanly through JSON — NaN in
    particular serializes to invalid JSON. Convert to plain None/str/float."""
    safe = {}
    for key, value in record.items():
        if value is None:
            safe[key] = None
        elif isinstance(value, float) and math.isnan(value):
            safe[key] = None
        elif pd.isna(value):
            safe[key] = None
        elif hasattr(value, "item"):
            # numpy scalar (int64, float64, bool_, ...) -> native Python type
            safe[key] = value.item()
        else:
            safe[key] = value
    return safe
