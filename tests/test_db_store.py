"""
Integration tests for the storage layer — require a running Postgres
(docker-compose up -d db). Skipped automatically if the DB isn't reachable,
so `pytest` still passes in an environment with no Docker (e.g. the Stage 1
rule-engine tests should never depend on infrastructure being up).
"""
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from db.database import SessionLocal, engine, Base
from db.models import DatasetRow, QualityRun, QualityIssue, DataLineage
from db.store import store_pipeline_result
from ingest import load_structured
from run_pipeline import run_pipeline

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "samples" / "sample_power_data.csv"


def _db_available() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")


@pytest.fixture(autouse=True)
def _clean_tables():
    Base.metadata.create_all(bind=engine)
    yield
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE quality_issues, dataset_rows, data_lineage, quality_runs CASCADE"
            )
        )


def test_store_pipeline_result_writes_all_four_tables():
    df = load_structured(SAMPLE)
    result = run_pipeline(str(SAMPLE), verbose=False, df=df)

    db = SessionLocal()
    try:
        run = store_pipeline_result(db, result, df)

        assert db.query(QualityRun).filter_by(run_id=run.run_id).count() == 1
        assert db.query(DatasetRow).filter_by(source_run_id=run.run_id).count() == len(df)
        assert db.query(QualityIssue).filter_by(run_id=run.run_id).count() == len(result["issues"])
        assert db.query(DataLineage).filter_by(run_id=run.run_id).count() == 1

        stored_run = db.query(QualityRun).filter_by(run_id=run.run_id).one()
        assert stored_run.health_score == result["health_score"]["score"]
    finally:
        db.close()


def test_stored_rows_include_seeded_delhi_outlier():
    """The stored JSON payload preserves every ingested field, whatever the
    dataset's actual columns are — no fixed schema needed to round-trip it."""
    df = load_structured(SAMPLE)
    result = run_pipeline(str(SAMPLE), verbose=False, df=df)

    db = SessionLocal()
    try:
        store_pipeline_result(db, result, df)
        rows = db.query(DatasetRow).filter_by(source_run_id=result["run_id"]).all()
        delhi_march = next(
            r for r in rows if r.data.get("state_name") == "Delhi" and r.data.get("month") == "2026-03"
        )
        assert delhi_march.data["energy_requirement_mu"] == 999999.0
    finally:
        db.close()
