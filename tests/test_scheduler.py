"""
Tests for the watch-folder job and Slack alerting logic. The DB-touching
tests skip if Postgres isn't reachable, same pattern as the other
integration tests in this suite.
"""
import shutil
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

import scheduler.watcher as watcher_module
from db.database import Base, engine
from scheduler.alerts import build_alert_message, should_alert
from scheduler.watcher import _infer_month, process_watch_folder

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "samples" / "sample_power_data.csv"


def _db_available() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False


# --- alerts.py: pure logic, no DB needed -------------------------------


def test_should_alert_on_low_score():
    result = {"health_score": {"score": 40}, "issues": []}
    assert should_alert(result) is True


def test_should_alert_on_high_severity_issue():
    result = {
        "health_score": {"score": 95},
        "issues": [{"severity": "high", "issue_type": "validity", "description": "bad"}],
    }
    assert should_alert(result) is True


def test_should_not_alert_when_healthy():
    result = {"health_score": {"score": 95}, "issues": [{"severity": "low", "issue_type": "x", "description": "y"}]}
    assert should_alert(result) is False


def test_build_alert_message_includes_score_and_issues():
    result = {
        "run_id": "abc123",
        "source_file": "test.csv",
        "health_score": {"score": 40},
        "rows_processed": 10,
        "rows_flagged": 3,
        "issues": [{"severity": "high", "issue_type": "validity", "description": "bad value"}],
    }
    message = build_alert_message(result)
    assert "40/100" in message
    assert "bad value" in message
    assert "abc123" in message


# --- watcher.py: month inference (pure) -------------------------------


def test_infer_month_from_filename():
    assert _infer_month("power_report_2026-04.pdf") == "2026-04"
    assert _infer_month("scan.png") is None


# --- watcher.py: file processing (needs DB) -------------------------------


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


@pytest.fixture
def watch_dirs(tmp_path, monkeypatch):
    incoming = tmp_path / "incoming"
    processed = tmp_path / "processed"
    failed = tmp_path / "failed"
    incoming.mkdir()

    monkeypatch.setattr(watcher_module, "PROCESSED_FOLDER", str(processed))
    monkeypatch.setattr(watcher_module, "FAILED_FOLDER", str(failed))
    return {"incoming": incoming, "processed": processed, "failed": failed}


def test_process_watch_folder_moves_processed_file(watch_dirs, monkeypatch):
    # Alerts aren't the point of this test; avoid noisy log output for the
    # expected below-threshold sample data.
    monkeypatch.setattr(watcher_module, "send_slack_alert", lambda result: False)

    shutil.copy(SAMPLE, watch_dirs["incoming"] / "sample_power_data.csv")
    results = process_watch_folder(str(watch_dirs["incoming"]))

    assert len(results) == 1
    assert results[0]["rows_processed"] == 62
    assert not (watch_dirs["incoming"] / "sample_power_data.csv").exists()
    assert (watch_dirs["processed"] / "sample_power_data.csv").exists()


def test_process_watch_folder_moves_unsupported_file_to_failed(watch_dirs):
    (watch_dirs["incoming"] / "notes.txt").write_text("not a data file")
    results = process_watch_folder(str(watch_dirs["incoming"]))

    assert results == []
    assert (watch_dirs["failed"] / "notes.txt").exists()


def test_process_watch_folder_empty_folder_is_noop(watch_dirs):
    assert process_watch_folder(str(watch_dirs["incoming"])) == []
