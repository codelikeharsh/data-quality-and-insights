"""
Hand-written analytical SQL for the reporting endpoints (api/insights.py).

Everything elsewhere in this codebase goes through the ORM or pandas —
these are the exceptions, deliberately: some things (a per-dataset latest
run via a window function, an issue-type breakdown across every run) are
both clearer and faster to express directly in SQL than to reconstruct
through SQLAlchemy's query builder or by pulling rows into pandas first.
Every query here is read-only and parameterized (SQLAlchemy `text()` bind
parameters, never string interpolation) against user-supplied values.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from db.models import DatasetProfile

# One row per dataset: its most recent run (via ROW_NUMBER, not a slower
# correlated subquery per dataset) plus aggregate stats across ALL of that
# dataset's runs (via a second CTE), joined together. This is what powers
# GET /datasets — "which datasets have been ingested, and how healthy is
# each one right now, and has it been getting better or worse over time."
_DATASET_SUMMARY_SQL = text(
    """
    WITH ranked_runs AS (
        SELECT
            run_id, dataset_name, timestamp, health_score,
            rows_processed, rows_flagged,
            ROW_NUMBER() OVER (
                PARTITION BY dataset_name ORDER BY timestamp DESC
            ) AS rn
        FROM quality_runs
    ),
    dataset_stats AS (
        SELECT
            dataset_name,
            COUNT(*)                AS run_count,
            ROUND(AVG(health_score)::numeric, 1) AS avg_health_score,
            MIN(health_score)       AS worst_health_score,
            MAX(health_score)       AS best_health_score
        FROM quality_runs
        GROUP BY dataset_name
    )
    SELECT
        r.dataset_name,
        r.run_id          AS latest_run_id,
        r.timestamp        AS latest_run_at,
        r.health_score      AS latest_health_score,
        r.rows_processed,
        r.rows_flagged,
        s.run_count,
        s.avg_health_score,
        s.worst_health_score,
        s.best_health_score
    FROM ranked_runs r
    JOIN dataset_stats s ON s.dataset_name = r.dataset_name
    WHERE r.rn = 1
    ORDER BY r.timestamp DESC
    """
)

# Issue-type x severity breakdown, optionally scoped to one dataset, across
# every stored run — "what kinds of problems show up most, and how bad are
# they" as one aggregate rather than having to page through every run's
# issue list by hand.
_ISSUE_BREAKDOWN_SQL = text(
    """
    SELECT
        qi.issue_type,
        qi.severity,
        COUNT(*) AS issue_count,
        COUNT(DISTINCT qi.run_id) AS runs_affected
    FROM quality_issues qi
    JOIN quality_runs qr ON qr.run_id = qi.run_id
    WHERE (:dataset_name IS NULL OR qr.dataset_name = :dataset_name)
    GROUP BY qi.issue_type, qi.severity
    ORDER BY issue_count DESC
    """
)


def get_dataset_summaries(db: Session) -> list[dict]:
    """One row per distinct dataset ingested so far, most recently active
    first — see _DATASET_SUMMARY_SQL above for what each field means."""
    rows = db.execute(_DATASET_SUMMARY_SQL).mappings().all()
    return [dict(row) for row in rows]


def get_issue_breakdown(db: Session, dataset_name: str | None = None) -> list[dict]:
    """Issue-type x severity counts across every stored run, optionally
    scoped to one dataset."""
    rows = db.execute(_ISSUE_BREAKDOWN_SQL, {"dataset_name": dataset_name}).mappings().all()
    return [dict(row) for row in rows]


# Every run for one dataset, chronological — the shape a BI tool wants for
# a health-score-over-time line chart (one fact table, not the dashboard's
# already-aggregated JSON).
_DATASET_RUN_HISTORY_SQL = text(
    """
    SELECT run_id, timestamp, health_score, rows_processed, rows_flagged
    FROM quality_runs
    WHERE dataset_name = :dataset_name
    ORDER BY timestamp
    """
)

# Every issue from every run of one dataset, with the run's own metadata
# joined onto each row — a flat, denormalized table that's exactly what a
# BI tool wants to pivot/filter by run, date, severity, or issue type
# without a second query. Deliberately NOT limited to the latest run (that's
# what GET /runs/{id}/export is for) — this is the full history.
_DATASET_ISSUE_HISTORY_SQL = text(
    """
    SELECT
        qr.run_id, qr.timestamp AS run_timestamp, qr.health_score,
        qi.severity, qi.issue_type, qi.row_reference, qi."column", qi.description
    FROM quality_issues qi
    JOIN quality_runs qr ON qr.run_id = qi.run_id
    WHERE qr.dataset_name = :dataset_name
    ORDER BY qr.timestamp, qi.id
    """
)


def get_dataset_run_history(db: Session, dataset_name: str) -> list[dict]:
    """Every run of one dataset, chronological — for a health-score trend
    chart built in an external BI tool rather than the dashboard's own."""
    rows = db.execute(_DATASET_RUN_HISTORY_SQL, {"dataset_name": dataset_name}).mappings().all()
    return [dict(row) for row in rows]


def get_dataset_issue_history(db: Session, dataset_name: str) -> list[dict]:
    """Every issue from every run of one dataset, with run metadata joined
    on — the flat table a BI tool pivots against."""
    rows = db.execute(_DATASET_ISSUE_HISTORY_SQL, {"dataset_name": dataset_name}).mappings().all()
    return [dict(row) for row in rows]


# The most recent profile for a dataset — the schema-drift baseline lookup.
# Plain SQLAlchemy ORM (not raw SQL like the queries above) is the right
# tool here: it's a single indexed lookup, not an aggregation, so the ORM
# query builder is exactly as clear and no slower.
def get_latest_profile(db: Session, dataset_name: str) -> dict | None:
    """The most recently stored profile for a dataset, or None if this
    dataset has never been ingested before (first-ever run — nothing to
    compare against, which schema_drift_rule already treats as a no-op)."""
    row = (
        db.query(DatasetProfile)
        .filter_by(dataset_name=dataset_name)
        .order_by(DatasetProfile.created_at.desc())
        .first()
    )
    return row.profile if row else None
