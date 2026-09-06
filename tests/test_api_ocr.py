"""
API-level test for the OCR upload path (POST /ingest with a scanned image),
exercised through the real FastAPI app + Postgres. Skips if either
tesseract or Postgres isn't available in this environment.
"""
import shutil

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from db.database import Base, engine
from api.main import app
from tests.conftest import report_font


def _db_available() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    shutil.which("tesseract") is None or not _db_available(),
    reason="requires both tesseract and a reachable Postgres",
)


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


def _render_scan(tmp_path):
    font = report_font()
    img = Image.new("RGB", (700, 100), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((15, 15), "Assam 1600 1580", fill="black", font=font)
    path = tmp_path / "scan.png"
    img.save(path)
    return path


def test_ingest_ocr_scan_without_month_returns_400(tmp_path):
    client = TestClient(app)
    path = _render_scan(tmp_path)
    with path.open("rb") as f:
        response = client.post("/ingest", files={"file": ("scan.png", f, "image/png")})
    assert response.status_code == 400


def test_ingest_ocr_scan_with_month_succeeds(tmp_path):
    client = TestClient(app)
    path = _render_scan(tmp_path)
    with path.open("rb") as f:
        response = client.post(
            "/ingest",
            files={"file": ("scan.png", f, "image/png")},
            data={"month": "2026-04"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["rows_processed"] == 1
