"""
Generic per-run insights: a column profile and a raw-row preview, both
built from whatever columns the ingested dataset actually has — no
assumption about dataset shape. This is what the dashboard reads instead of
a domain-specific aggregation (e.g. "deficit states"), so it works for any
uploaded file.
"""
from sqlalchemy.orm import Session

from db.models import DatasetProfile, DatasetRow
from db.queries import (
    get_dataset_issue_history,
    get_dataset_run_history,
    get_dataset_summaries,
    get_issue_breakdown,
)

__all__ = [
    "get_run_profile",
    "get_run_preview",
    "get_dataset_summaries",
    "get_issue_breakdown",
    "get_dataset_run_history",
    "get_dataset_issue_history",
]


def get_run_profile(db: Session, run_id: str) -> dict | None:
    """The per-column profile computed at ingest time for this run (dtype,
    null rate, and numeric or text summary stats — see profiling/profiler.py).
    Read from Postgres (db.models.DatasetProfile), not local disk — see that
    model's docstring for why."""
    row = db.query(DatasetProfile).filter_by(run_id=run_id).first()
    return row.profile if row else None


def get_run_preview(db: Session, run_id: str, limit: int = 50) -> list[dict]:
    """The first `limit` ingested rows for a run, in original row order —
    lets the dashboard show actual data, not just aggregate stats."""
    rows = (
        db.query(DatasetRow)
        .filter_by(source_run_id=run_id)
        .order_by(DatasetRow.row_index)
        .limit(limit)
        .all()
    )
    return [r.data for r in rows]
