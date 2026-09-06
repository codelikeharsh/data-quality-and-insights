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
