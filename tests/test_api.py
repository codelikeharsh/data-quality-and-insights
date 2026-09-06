"""
API integration tests — exercise the FastAPI app with a real Postgres
(docker-compose up -d db), via FastAPI's TestClient. Skipped automatically
if the DB isn't reachable, same as tests/test_db_store.py.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from db.database import Base, engine
from api.main import app

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


@pytest.fixture
def client():
    return TestClient(app)


def _ingest_sample(client) -> dict:
    with SAMPLE.open("rb") as f:
        response = client.post(
            "/ingest", files={"file": ("sample_power_data.csv", f, "text/csv")}
        )
    assert response.status_code == 200
    return response.json()


def test_root():
    client = TestClient(app)
    assert client.get("/").status_code == 200


def test_ingest_returns_seeded_issues(client):
    result = _ingest_sample(client)
    assert result["rows_processed"] == 62
    assert 0 <= result["health_score"]["score"] < 100
    issue_types = {i["issue_type"] for i in result["issues"]}
    assert issue_types == {"completeness", "validity", "outlier", "consistency"}


def test_ingest_rejects_unsupported_file_type(client):
    response = client.post(
        "/ingest", files={"file": ("data.txt", b"not a real file", "text/plain")}
    )
    assert response.status_code == 400


def test_runs_lists_ingested_run(client):
    result = _ingest_sample(client)
    response = client.get("/runs")
    assert response.status_code == 200
    run_ids = [r["run_id"] for r in response.json()]
    assert result["run_id"] in run_ids


def test_run_issues_returns_404_for_unknown_run(client):
    response = client.get("/runs/doesnotexist/issues")
    assert response.status_code == 404


def test_run_issues_matches_ingest_response(client):
    result = _ingest_sample(client)
    response = client.get(f"/runs/{result['run_id']}/issues")
    assert response.status_code == 200
    assert len(response.json()) == len(result["issues"])


def test_run_profile_returns_column_stats(client):
    result = _ingest_sample(client)
    response = client.get(f"/runs/{result['run_id']}/profile")
    assert response.status_code == 200
    profile = response.json()
    assert profile["row_count"] == 62
    assert "state_name" in profile["columns"]
    assert "energy_requirement_mu" in profile["columns"]


def test_run_profile_404_for_unknown_run(client):
    response = client.get("/runs/doesnotexist/profile")
    assert response.status_code == 404


def test_run_preview_returns_raw_rows(client):
    result = _ingest_sample(client)
    response = client.get(f"/runs/{result['run_id']}/preview?limit=5")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 5
    assert "state_name" in rows[0]


def test_ingest_defaults_dataset_name_to_filename(client):
    result = _ingest_sample(client)
    assert result["dataset_name"] == "sample_power_data"


def test_ingest_accepts_explicit_dataset_name(client):
    with SAMPLE.open("rb") as f:
        response = client.post(
            "/ingest",
            files={"file": ("sample_power_data.csv", f, "text/csv")},
            data={"dataset_name": "power_supply_series"},
        )
    assert response.status_code == 200
    assert response.json()["dataset_name"] == "power_supply_series"


def test_runs_filter_scopes_to_one_dataset(client):
    """Two uploads under different dataset names must not mix in /runs —
    this is the exact bug a health-score trend chart would otherwise hit
    (see db.models.QualityRun.dataset_name)."""
    with SAMPLE.open("rb") as f:
        client.post(
            "/ingest",
            files={"file": ("sample_power_data.csv", f, "text/csv")},
            data={"dataset_name": "dataset_a"},
        )
    with SAMPLE.open("rb") as f:
        client.post(
            "/ingest",
            files={"file": ("sample_power_data.csv", f, "text/csv")},
            data={"dataset_name": "dataset_b"},
        )

    response = client.get("/runs", params={"dataset_name": "dataset_a"})
    assert response.status_code == 200
    runs = response.json()
    assert len(runs) == 1
    assert all(r["dataset_name"] == "dataset_a" for r in runs)


def test_datasets_endpoint_lists_distinct_datasets(client):
    _ingest_sample(client)  # dataset_name defaults to "sample_power_data"
    response = client.get("/datasets")
    assert response.status_code == 200
    datasets = {d["dataset_name"] for d in response.json()}
    assert "sample_power_data" in datasets


def test_issue_breakdown_scoped_to_dataset(client):
    result = _ingest_sample(client)
    response = client.get(
        "/reports/issue-breakdown", params={"dataset_name": result["dataset_name"]}
    )
    assert response.status_code == 200
    breakdown = response.json()
    assert len(breakdown) > 0
    assert all("issue_type" in row and "issue_count" in row for row in breakdown)


def test_export_run_report_returns_csv(client):
    result = _ingest_sample(client)
    response = client.get(f"/runs/{result['run_id']}/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    body = response.text
    assert "issue_type" in body.splitlines()[0]  # header row
    assert result["run_id"] in body


def test_export_dataset_run_history_returns_csv(client):
    result = _ingest_sample(client)
    response = client.get(f"/datasets/{result['dataset_name']}/export/runs")
    assert response.status_code == 200
    body = response.text
    assert body.splitlines()[0] == "run_id,timestamp,health_score,rows_processed,rows_flagged"
    assert result["run_id"] in body


def test_export_dataset_run_history_404_for_unknown_dataset(client):
    response = client.get("/datasets/doesnotexist/export/runs")
    assert response.status_code == 404


def test_export_dataset_issue_history_returns_csv(client):
    result = _ingest_sample(client)
    response = client.get(f"/datasets/{result['dataset_name']}/export/issues")
    assert response.status_code == 200
    body = response.text
    assert "issue_type" in body.splitlines()[0]
    assert result["run_id"] in body
