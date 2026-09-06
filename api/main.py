"""
FastAPI app wrapping the ingest -> profile -> quality checks -> health score
-> store pipeline (see run_pipeline.py, db/store.py) behind HTTP endpoints
for the React dashboard.

Run locally with:
    uvicorn api.main:app --reload
"""
import csv
import io
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, Form, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from config import ALLOWED_ORIGINS, SCHEDULER_ENABLED, SCHEDULER_INTERVAL_MINUTES, UPLOAD_DIR
from db.database import Base, engine, get_db
from db.models import QualityIssue, QualityRun
from db.queries import get_latest_profile
from db.store import store_pipeline_result
from ingest import load_structured, load_unstructured
from run_pipeline import run_pipeline, _default_dataset_name
from scheduler.watcher import process_watch_folder
from api.auth import require_api_key
from api.insights import (
    get_dataset_issue_history,
    get_dataset_run_history,
    get_dataset_summaries,
    get_issue_breakdown,
    get_run_preview,
    get_run_profile,
)
from api.schemas import (
    DatasetSummaryOut,
    IngestResponse,
    IssueBreakdownOut,
    IssueOut,
    RunProfileOut,
    RunSummaryOut,
)

_background_scheduler: BackgroundScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _background_scheduler

    # Schema is Alembic-managed (see migrations/) — the Docker image runs
    # `alembic upgrade head` before this process starts (see Dockerfile.api),
    # and `alembic upgrade head` is the documented step for running the API
    # locally too (see README). This create_all is ONLY a safety net for
    # someone running the API directly against a completely fresh DB without
    # having run migrations first — it's a no-op once the schema exists,
    # and does not replace running migrations for anything beyond that.
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

# Locked to config.ALLOWED_ORIGINS (env-driven) rather than "*" — a
# deployed environment sets ALLOWED_ORIGINS to its real frontend URL(s),
# see .env.example. Defaults to the local Vite dev ports so local dev needs
# no setup.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"status": "ok", "service": "data-quality-insights-engine"}


STRUCTURED_EXTENSIONS = (".csv", ".xlsx", ".xls")
UNSTRUCTURED_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".tiff")


@app.post("/ingest", response_model=IngestResponse, dependencies=[Depends(require_api_key)])
async def ingest_file(
    file: UploadFile = File(...),
    month: str | None = Form(
        None, description="Required for scanned PDF/image uploads (e.g. '2026-04') — OCR can't read a month out of a table row."
    ),
    dataset_name: str | None = Form(
        None,
        description=(
            "Groups this run with other runs of the same logical dataset "
            "(see db.models.QualityRun.dataset_name). Defaults to the "
            "uploaded filename's stem — set this explicitly when successive "
            "uploads won't share a filename (e.g. 'power_supply_2026-04.csv' "
            "vs '...2026-05.csv') but should still be tracked as one series."
        ),
    ),
    db: Session = Depends(get_db),
):
    """Upload a file and run the full pipeline against it, then store and
    return the result. Structured files (CSV/Excel) go through
    ingest.load_structured; scanned PDFs/images go through OCR via
    ingest.load_unstructured — both land in the same DataFrame shape, so
    everything downstream (profiling, quality rules, storage) is source-agnostic.
    Requires an X-API-Key header if config.API_KEY is set (see api/auth.py).
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

        resolved_dataset_name = dataset_name or _default_dataset_name(file.filename)
        # Baseline comes from Postgres, not local disk, so schema-drift
        # detection is correct regardless of how many backend instances are
        # running (see db.models.DatasetProfile / db.queries.get_latest_profile).
        baseline_profile = get_latest_profile(db, resolved_dataset_name)
        result = run_pipeline(
            str(dest_path),
            verbose=False,
            df=df,
            dataset_name=resolved_dataset_name,
            baseline_profile=baseline_profile,
            persist_profile_locally=False,
        )
        store_pipeline_result(db, result, df)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to process file: {exc}") from exc

    return result


@app.get("/runs", response_model=list[RunSummaryOut])
def list_runs(dataset_name: str | None = None, limit: int = 200, db: Session = Depends(get_db)):
    """Past ingestion runs, most recent first — powers the health-score trend
    chart. Pass `dataset_name` to scope this to one dataset's history; the
    dashboard always should, since mixing two unrelated datasets' scores
    onto one trend line is meaningless (see db.models.QualityRun.dataset_name)."""
    query = db.query(QualityRun)
    if dataset_name is not None:
        query = query.filter_by(dataset_name=dataset_name)
    return query.order_by(desc(QualityRun.timestamp)).limit(limit).all()


@app.get("/datasets", response_model=list[DatasetSummaryOut])
def list_datasets(db: Session = Depends(get_db)):
    """Every distinct dataset ingested so far, with its latest run and
    aggregate health-score stats — see db/queries.py for the SQL. This is
    what the dashboard's dataset picker is built from."""
    return get_dataset_summaries(db)


@app.get("/reports/issue-breakdown", response_model=list[IssueBreakdownOut])
def issue_breakdown(dataset_name: str | None = None, db: Session = Depends(get_db)):
    """Issue-type x severity counts across every stored run, optionally
    scoped to one dataset — "what kinds of problems show up most."""
    return get_issue_breakdown(db, dataset_name=dataset_name)


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

    profile = get_run_profile(db, run_id)
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


@app.get("/runs/{run_id}/export")
def export_run_report(run_id: str, db: Session = Depends(get_db)):
    """A CSV quality report for one run (one row per flagged issue, with the
    run's dataset/score/timestamp repeated on every row) — meant for
    handing to a spreadsheet or BI tool (Excel, Power BI, Tableau) rather
    than the dashboard itself, which already renders this data directly."""
    run = db.query(QualityRun).filter_by(run_id=run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    issues = db.query(QualityIssue).filter_by(run_id=run_id).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "dataset_name", "run_id", "run_timestamp", "health_score",
            "rows_processed", "rows_flagged", "severity", "issue_type",
            "row_reference", "column", "description",
        ]
    )
    if issues:
        for issue in issues:
            writer.writerow(
                [
                    run.dataset_name, run.run_id, run.timestamp.isoformat(), run.health_score,
                    run.rows_processed, run.rows_flagged, issue.severity, issue.issue_type,
                    issue.row_reference, issue.column, issue.description,
                ]
            )
    else:
        writer.writerow(
            [
                run.dataset_name, run.run_id, run.timestamp.isoformat(), run.health_score,
                run.rows_processed, run.rows_flagged, "", "", "", "", "no issues flagged",
            ]
        )

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{run.dataset_name}_{run_id}_report.csv"'},
    )


def _rows_to_csv_response(rows: list[dict], filename: str) -> StreamingResponse:
    """dict rows (from db/queries.py, already ordered) -> a downloadable CSV
    response. Column headers come from the first row's keys, so the caller's
    SQL SELECT list is the only place the CSV's shape is defined."""
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/datasets/{dataset_name}/export/runs")
def export_dataset_run_history(dataset_name: str, db: Session = Depends(get_db)):
    """Every run of one dataset, chronological, as CSV — the fact table a
    BI tool (Power BI, Tableau, Excel) plots as a health-score-over-time
    trend, built there instead of re-deriving the dashboard's own chart."""
    rows = get_dataset_run_history(db, dataset_name)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No runs found for dataset '{dataset_name}'")
    return _rows_to_csv_response(rows, f"{dataset_name}_run_history.csv")


@app.get("/datasets/{dataset_name}/export/issues")
def export_dataset_issue_history(dataset_name: str, db: Session = Depends(get_db)):
    """Every issue from every run of one dataset, as one flat CSV (run
    metadata joined onto each issue row) — the table a BI tool pivots by
    run/date/severity/issue type. Unlike GET /runs/{id}/export, this is the
    FULL history, not just the latest run."""
    rows = get_dataset_issue_history(db, dataset_name)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No issues found for dataset '{dataset_name}'")
    return _rows_to_csv_response(rows, f"{dataset_name}_issue_history.csv")
