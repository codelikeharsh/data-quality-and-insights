"""
Generic per-run insights: a column profile and a raw-row preview, both
built from whatever columns the ingested dataset actually has — no
assumption about dataset shape. This is what the dashboard reads instead of
a domain-specific aggregation (e.g. "deficit states"), so it works for any
uploaded file.
"""
from sqlalchemy.orm import Session

from db.models import DatasetRow
from profiling.profiler import load_profile


def get_run_profile(run_id: str) -> dict | None:
    """The per-column profile computed at ingest time for this run (dtype,
    null rate, and numeric or text summary stats — see profiling/profiler.py)."""
    return load_profile(run_id)


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
