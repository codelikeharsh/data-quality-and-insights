"""
FastAPI app wrapping the ingest -> profile -> quality checks -> health score
-> store pipeline (see run_pipeline.py, db/store.py) behind HTTP endpoints
for the React dashboard.

Run locally with:
    uvicorn api.main:app --reload
"""
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, Form, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc
from sqlalchemy.orm import Session

from config import SCHEDULER_ENABLED, SCHEDULER_INTERVAL_MINUTES, UPLOAD_DIR
from db.database import Base, engine, get_db
from db.models import QualityIssue, QualityRun
from db.store import store_pipeline_result
from ingest import load_structured, load_unstructured
from run_pipeline import run_pipeline
from scheduler.watcher import process_watch_folder
from api.insights import get_run_preview, get_run_profile
from api.schemas import (
    IngestResponse,
    IssueOut,
    RunProfileOut,
    RunSummaryOut,
)

_background_scheduler: BackgroundScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _background_scheduler

    # Idempotent: safe to call even if the tables already exist. Keeps the
    # API self-contained for local/demo use without a separate migration
    # step, while db/init_db.py remains available for explicit use.
    Base.metadata.create_all(bind=engine)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # Runs the watch-folder job automatically on an interval for as long as
    # the API process is up — this is what makes "docker-compose up" alone
    # give automated re-ingestion, with no separate scheduler process to
    # remember to start (scheduler/main.py remains available for running it
    # standalone, outside the API).
    if SCHEDULER_ENABLED:
        _background_scheduler = BackgroundScheduler()
        _background_scheduler.add_job(
            process_watch_folder, "interval", minutes=SCHEDULER_INTERVAL_MINUTES
        )
        _background_scheduler.start()

    yield

    if _background_scheduler is not None:
        _background_scheduler.shutdown(wait=False)


app = FastAPI(
    title="Data Quality & Insights Engine",
    description="Ingests any tabular dataset (CSV/Excel, or a scanned power-report PDF/image), checks it for quality/governance issues, scores it, and stores it.",
    version="1.0.0",
    lifespan=lifespan,
)

# Dev-friendly CORS: the React app runs on a different port (5173/3000).
# In a real deployment this would be locked down to the actual frontend origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "service": "data-quality-insights-engine"}


STRUCTURED_EXTENSIONS = (".csv", ".xlsx", ".xls")
UNSTRUCTURED_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".tiff")


@app.post("/ingest", response_model=IngestResponse)
async def ingest_file(
    file: UploadFile = File(...),
    month: str | None = Form(
        None, description="Required for scanned PDF/image uploads (e.g. '2026-04') — OCR can't read a month out of a table row."
    ),
    db: Session = Depends(get_db),
):
    """Upload a file and run the full pipeline against it, then store and
    return the result. Structured files (CSV/Excel) go through
    ingest.load_structured; scanned PDFs/images go through OCR via
    ingest.load_unstructured — both land in the same DataFrame shape, so
    everything downstream (profiling, quality rules, storage) is source-agnostic.
    """
    suffix = Path(file.filename).suffix.lower()
    if suffix not in STRUCTURED_EXTENSIONS + UNSTRUCTURED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{suffix}'. Expected one of "
                f"{STRUCTURED_EXTENSIONS + UNSTRUCTURED_EXTENSIONS}."
            ),
        )
    if suffix in UNSTRUCTURED_EXTENSIONS and not month:
        raise HTTPException(
            status_code=400,
            detail="'month' (e.g. '2026-04') is required when uploading a scanned PDF/image.",
        )

    dest_path = UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{file.filename}"
    with dest_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        if suffix in UNSTRUCTURED_EXTENSIONS:
            df = load_unstructured(dest_path, month=month)
            if df.empty:
                raise HTTPException(
                    status_code=422,
                    detail="OCR extracted 0 rows from this file (low confidence / unreadable scan).",
                )
            # extraction_confidence is metadata for the OCR path only — the
            # quality rules and storage schema don't know about it.
            df = df.drop(columns=["extraction_confidence"])
        else:
            df = load_structured(dest_path)

        result = run_pipeline(str(dest_path), verbose=False, df=df)
        store_pipeline_result(db, result, df)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to process file: {exc}") from exc

    return result


@app.get("/runs", response_model=list[RunSummaryOut])
def list_runs(db: Session = Depends(get_db)):
    """Past ingestion runs, most recent first — powers the health-score trend chart."""
    return db.query(QualityRun).order_by(desc(QualityRun.timestamp)).all()


@app.get("/runs/{run_id}/issues", response_model=list[IssueOut])
def get_run_issues(run_id: str, db: Session = Depends(get_db)):
    """Every flagged issue for one run."""
    run = db.query(QualityRun).filter_by(run_id=run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    issues = db.query(QualityIssue).filter_by(run_id=run_id).all()
    return [
        IssueOut(
            row_reference=i.row_reference,
            column=i.column,
            issue_type=i.issue_type,
            description=i.description,
            severity=i.severity,
        )
        for i in issues
    ]


@app.get("/runs/{run_id}/profile", response_model=RunProfileOut)
def run_profile(run_id: str, db: Session = Depends(get_db)):
    """The per-column profile (dtype, null rate, numeric/text summary stats)
    computed at ingest time for this run — works for any dataset shape."""
    run = db.query(QualityRun).filter_by(run_id=run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    profile = get_run_profile(run_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"No stored profile for run '{run_id}'")
    return profile


@app.get("/runs/{run_id}/preview")
def run_preview(run_id: str, limit: int = 50, db: Session = Depends(get_db)):
    """The first `limit` ingested rows for this run, as-uploaded — lets the
    dashboard show actual data regardless of what columns it has."""
    run = db.query(QualityRun).filter_by(run_id=run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    return get_run_preview(db, run_id, limit=limit)
