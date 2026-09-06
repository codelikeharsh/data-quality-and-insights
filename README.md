# Data Quality & Insights Engine

[![CI](https://github.com/codelikeharsh/data-quality-and-insights/actions/workflows/ci.yml/badge.svg)](https://github.com/codelikeharsh/data-quality-and-insights/actions/workflows/ci.yml)

**Live demo:** [dashboard](https://data-quality-and-insights-1.onrender.com) ·
[API docs](https://data-quality-and-insights.onrender.com/docs)
(hosted on Render's free tier — the backend spins down after 15 minutes of
inactivity, so the first request after a while can take 30-50s to wake up)

A full-stack data governance tool that ingests **any tabular dataset**
(CSV/Excel, or a scanned tabular report), automatically profiles and
quality-checks it against no fixed schema, scores it transparently, stores
it with lineage, and surfaces it on a dashboard — with SQL-backed reporting,
CSV export for downstream BI tools, and no manual re-running required once
new data arrives.

## The pitch

Any team that receives periodic data files — monthly submissions from
branches, states, vendors, sensors, whatever — eventually has to answer the
same questions before trusting a batch:

- Is everything that should be here, here?
- Are the values plausible, or is there an obvious decimal/unit error?
- Did the same real-world thing get spelled two different ways somewhere,
  quietly fragmenting every `GROUP BY` downstream?
- Has the file's shape changed since last time, unannounced?
- Given all of that, how much can we trust this batch, and exactly why —
  and can I hand that answer to someone in Excel or Power BI?

This project automates that check end to end — **ingest → profile → quality
rules → health score → store with lineage → dashboard/SQL reports → alert**
— for **whatever columns the file actually has**. Nothing in the rule
engine, storage layer, or API assumes a fixed schema; every rule either
works on any dataset by construction (a null-rate check needs no domain
knowledge) or auto-detects the shape it needs (e.g. "which column looks
like a reporting period?") rather than having it hardcoded.

The bundled demo dataset is Indian state-wise power supply data
([`data/samples/sample_power_data.csv`](data/samples/sample_power_data.csv),
with four intentionally planted problems — see below), because a concrete
example is easier to reason about than an abstract one. It is **one example
among many the engine handles**, not the thing the engine was built for —
see [Proof it's actually generic](#proof-its-actually-generic) below, where
the exact same code (zero changes) catches four different planted problems
in a completely different retail-sales dataset with different column names.

## Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │              React Dashboard                 │
                    │  Dataset picker · Health trend · Issue        │
                    │  breakdown (SQL) · Column profile · Data      │
                    │  preview · CSV export (Vite+Tailwind+Recharts)│
                    └───────────────────┬───────────────────────────┘
                                        │ HTTP (fetch, X-API-Key on writes)
                                        ▼
                    ┌─────────────────────────────────────────────┐
                    │                FastAPI (api/)                 │
                    │  POST /ingest  [auth]   GET /runs?dataset_name │
                    │  GET /datasets           GET /runs/{id}/issues │
                    │  GET /reports/issue-breakdown (raw SQL)        │
                    │  GET /runs/{id}/{profile,preview,export}       │
                    └───────┬───────────────────────────┬───────────┘
                            │                            │
              ┌─────────────▼─────────────┐   ┌──────────▼───────────┐
              │   Ingest → Profile →      │   │   APScheduler          │
              │   Quality Rules → Score   │   │   (in-process, runs    │
              │   (run_pipeline.py)       │   │   on an interval)      │
              │                            │   │                        │
              │  ingest/     structured    │   │  scheduler/watcher.py  │
              │              (any CSV/     │◄──┤  watches data/incoming/│
              │              Excel schema) │   │  runs the SAME         │
              │              unstructured  │   │  pipeline, then alerts │
              │              (OCR: PDF/PNG,│   │  Slack on low score /  │
              │               power-report │   │  high-severity issues  │
              │               shaped only) │   │  (scheduler/alerts.py) │
              │  profiling/  per-column    │   └────────────────────────┘
              │              stats, saved  │
              │              to Postgres   │
              │              PER DATASET   │
              │  quality/    7 rule        │
              │              functions +   │
              │              health score, │
              │              all schema-   │
              │              agnostic      │
              └─────────────┬──────────────┘
                            │
                            ▼
              ┌──────────────────────────────────────┐
              │      PostgreSQL, Alembic-managed       │
              │      (db/, migrations/)                │
              │  dataset_rows   — every row, as JSON   │
              │                    (any schema fits)   │
              │  quality_runs   — one row per run,      │
              │                    grouped by dataset   │
              │  quality_issues — every flagged issue   │
              │  data_lineage   — source → transforms   │
              │                    → destination        │
              │  dataset_profiles — per-run column      │
              │                    profile, per dataset  │
              │                    (schema-drift baseline│
              │                    shared across every   │
              │                    backend instance)     │
              └──────────────────────────────────────┘
```

Both ingestion paths (`ingest/structured.py` for CSV/Excel,
`ingest/unstructured.py` for OCR'd PDFs/images) produce the same shape of
output — a DataFrame — so profiling, quality rules, scoring, and storage
never know or care which kind of file the data came from. One deliberate
scope boundary: the **structured** path (CSV/Excel) is fully schema-
agnostic; the **OCR** path is not — extracting arbitrary table structure
from a scanned image is a much harder problem, so it stays narrowly scoped
to a "label, number, number" row shape (see `ingest/unstructured.py`'s
docstring). That limitation is stated up front rather than glossed over.

## How the engine stays schema-agnostic

Every rule in `quality/rules.py` either:

1. **Needs no domain knowledge at all** — `completeness_rule` (null-rate per
   column), `duplicate_rule` (exact duplicate rows), `outlier_rule`
   (median/MAD or IQR outliers per numeric column), `consistency_rule`
   (self-referential near-duplicate detection: cluster a categorical
   column's own observed values by fuzzy similarity and flag a rare variant
   that closely matches a much more common one — e.g. "Eastsidee" appearing
   once next to "Eastside" appearing many times — no external reference
   list required), and `schema_drift_rule` (compare this run's columns/
   dtypes against the previous run's, per dataset).
2. **Auto-detects the column it needs**, rather than requiring one by name:
   `guess_entity_column` and `guess_period_column`
   (`ingest/structured.py`) best-effort pick "the column that looks like a
   repeating entity" and "the column that looks like a reporting period"
   (name matches month/date/year/period/quarter/week/fiscal), so
   `outlier_rule` can compare each entity against its own history and
   `group_completeness_rule` can catch an entity silently missing from one
   period — both skip cleanly (no-op, not an error) on a dataset with
   neither shape.

Every run is also tagged with a **`dataset_name`** (defaults to the
filename, overridable), so uploading two unrelated files doesn't mix their
histories: the health-score trend, the SQL issue breakdown, and the
schema-drift baseline are all scoped to one dataset at a time. This isn't
cosmetic — a generic engine that let two different datasets' runs share one
timeline would silently produce a meaningless trend chart.

None of this requires configuration for a new dataset. Point it at a file
and it works; `config.py`'s `RULE_CONFIG` exists to let an analyst *tune*
thresholds (e.g. how aggressive outlier detection is), not to describe the
dataset's shape.

## Proof it's actually generic

```bash
python run_pipeline.py /tmp/retail_sales.csv
```

Run against a 14-row retail dataset (`month, store_name, units_sold,
revenue_usd` — completely different columns, zero code changes, zero
config changes) with four planted problems of its own, this reliably
catches all of them (exact scores/counts will vary slightly with rule
tuning, but the categories won't):

```
HEALTH SCORE: 48 / 100

Deductions:
  - validity       x2   @ -10 pts each = -20 pts
  - completeness   x3   @ -4  pts each = -12 pts
  - outlier        x2   @ -6  pts each = -12 pts
  - consistency    x1   @ -5  pts each = -5  pts
  - duplicate      x1   @ -3  pts each = -3  pts

  [HIGH]   completeness  'Eastside' missing from month=2026-02 despite reporting elsewhere
  [HIGH]   validity      -15 units_sold — 93% of the column is non-negative
  [MEDIUM] outlier       999,999 units_sold — statistical outlier vs. Downtown's own history
  [MEDIUM] consistency   'Eastsidee' closely matches the far more common 'Eastside' (94% similar)
  [MEDIUM] duplicate     exact duplicate row
```

Every one of those was auto-detected — no `store_name`/`units_sold` column
name appears anywhere in the rule engine.

## Tech stack

Python · FastAPI · React (plain fetch, Tailwind, Recharts) · PostgreSQL ·
SQLAlchemy + Alembic (migrations) · raw SQL (window functions/CTEs) for
reporting · pandas/numpy · rapidfuzz (near-duplicate detection) ·
pytesseract + pdf2image (OCR) · APScheduler (production automation) +
Apache Airflow (DAG, validated — see [`orchestration/`](orchestration/)) ·
Slack webhooks · Docker Compose · pytest · ruff · GitHub Actions CI

## Setup

### Option A — Docker Compose (everything at once)

```bash
docker-compose up --build
```

This starts three services: `db` (Postgres), `backend` (FastAPI — runs
`alembic upgrade head` on startup, then the scheduler in-process), and
`frontend` (the React dashboard, built and served via nginx). Because this
dev machine already had a native Postgres on 5432 and something else on
8000, the compose file maps to **host** ports `5433` (Postgres), `8001`
(API), `5173` (frontend) instead of the defaults — adjust in
[`docker-compose.yml`](docker-compose.yml) if your machine is free of those
conflicts. Once it's up:

- Dashboard: http://localhost:5173
- API docs: http://localhost:8001/docs

### Option B — run everything locally (what was used to build/verify this)

```bash
# 1. Postgres (only the db service, via Docker)
docker-compose up -d db

# 2. Backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt   # includes requirements.txt + ruff
python -m db.init_db          # applies Alembic migrations (idempotent)
uvicorn api.main:app --reload --port 8000

# 3. Frontend (separate terminal)
cd frontend
npm install
npm run dev                    # http://localhost:5173
```

Copy `.env.example` → `.env` (backend) and `frontend/.env.example` →
`frontend/.env.local` (frontend) and adjust ports/URLs if you changed the
Docker mapping. Set `API_KEY` in `.env` (and `VITE_API_KEY` in
`frontend/.env.local`) if you want the write path locked down — see
[Auth](#auth) below.

### Option C — CLI only, no DB/API (fastest way to see the rule engine work)

```bash
source venv/bin/activate
python run_pipeline.py data/samples/sample_power_data.csv
# or point it at any CSV/Excel file of your own — no setup needed:
python run_pipeline.py /path/to/your_data.csv
```

### Schema migrations (Alembic)

The schema lives in `migrations/`, not in a `create_all()` call — a real
team needs to see how a table changes over time, not just its final shape.

```bash
alembic upgrade head                              # apply pending migrations
alembic revision --autogenerate -m "add a column"  # after editing db/models.py
```

### Running the test suite

```bash
pytest tests/ -v      # 63 tests
ruff check .           # lint
```

Tests that need Postgres or `tesseract` self-skip when those aren't
available, so `pytest` still passes in a minimal environment — the DB/OCR
tests just won't run. CI (`.github/workflows/ci.yml`) runs the full suite
with both available, plus a frontend lint+build job, on every push/PR.

## Auth

`POST /ingest` (the only write endpoint) requires an `X-API-Key` header
matching `config.API_KEY` — **only if that env var is set**; unset, it's a
no-op so a fresh clone works with zero setup (see `api/auth.py`). Every
read endpoint (`/runs`, `/datasets`, `/runs/{id}/*`, `/reports/*`) stays
open, matching a typical internal reporting-dashboard posture: anyone can
view, only a known caller can write. This is a single shared secret, not a
user/session/OAuth system — deliberately small, not a claim of production-
grade auth.

## SQL-backed reporting

Most of this codebase goes through the ORM or pandas; `db/queries.py` is
the deliberate exception — hand-written, parameterized SQL for the two
things that are both clearer and faster to express directly than to
reconstruct through SQLAlchemy's query builder:

- **`GET /datasets`** — a `ROW_NUMBER() OVER (PARTITION BY dataset_name
  ORDER BY timestamp DESC)` window function joined against a `GROUP BY`
  CTE, in one query: each dataset's latest run plus its all-time run count
  and best/worst/average health score.
- **`GET /reports/issue-breakdown?dataset_name=...`** — issue-type ×
  severity counts across every stored run for a dataset, one aggregate
  query instead of paging through every run's issue list by hand.

**Query performance**, measured with `EXPLAIN ANALYZE` against 2,000 runs /
20 datasets / ~8,000 issues (a synthetic volume, well beyond the bundled
demo data, generated specifically to make the query plans meaningful):

| Query | Plan | Execution time |
|---|---|---|
| Dataset summary (window function + CTE) | `HashAggregate` → `WindowAgg` → `Hash Join` | **2.2ms** |
| Issue breakdown (join + `GROUP BY`) | `Hash Join` → `Sort` → `GroupAggregate` | **16.3ms** |

Both plans use sequential scans on `quality_runs`/`quality_issues` rather
than their indexes — and that's the *correct* choice at this table size
(a few thousand rows fits easily in one scan; an index lookup would add
overhead, not remove it). Stated honestly rather than claiming the indexes
are "helping" here: they exist for when `dataset_name`/`run_id` lookups
matter at a larger scale, not because they're doing anything at this one.

## Export

**`GET /runs/{id}/export`** returns a CSV quality report (one row per
flagged issue, run metadata repeated on each row) — meant for handing to
Excel, Power BI, or Tableau rather than re-deriving the same numbers there;
the dashboard link ("Export CSV report") calls this directly.

## The four seeded problems in the bundled demo (and what catches them)

| Problem | Where | Rule that catches it |
|---|---|---|
| Bihar missing entirely | `2026-02` | `group_completeness_rule` (auto-detected entity=`state_name`, period=`month`) |
| "Orissa" instead of "Odisha" | `2026-03` | `consistency_rule` (self-referential near-duplicate detection) |
| Negative `energy_availability_mu` | Jharkhand, `2026-01` | `validity_rule` |
| `energy_requirement_mu` = 999999 | Delhi, `2026-03` | `outlier_rule` (median/MAD z-score, per-state history) |

## Data governance concepts, mapped to features (interview talking points)

- **Data profiling** (`profiling/profiler.py`) — the "know your data before
  you judge it" step, computed for any column set. Every run's profile is
  saved as JSON, per dataset, and doubles as the baseline the next run of
  *that same dataset* compares against for schema drift.
- **Data quality dimensions, implemented as independent, schema-agnostic
  rules** (`quality/rules.py`): completeness (null-rate, plus "did this
  entity silently stop reporting"), validity (a numeric column that's
  almost always non-negative flags its rare negative values — a relative,
  data-driven check, not a hardcoded domain constant), accuracy/
  plausibility (outlier detection on every numeric column), consistency
  (self-referential near-duplicate detection, no external reference list
  needed), uniqueness (exact-duplicate-row detection), schema stability
  (drift detection, per dataset).
- **Transparent scoring, not a black box** (`quality/health_score.py`) — a
  data health score means nothing to a governance stakeholder if they can't
  see why it dropped. Every point deducted is itemized by issue type and
  weight, weights live in one config file, and a CSV export of that
  breakdown is one click away.
- **Lineage** (`db/models.py::DataLineage`) — every run records its source
  file, the transformations applied, and its destination table.
- **Schema-agnostic storage** (`db/models.py::DatasetRow`) — every ingested
  row is stored as JSON rather than fixed columns, so a new dataset shape
  needs zero migrations; the *structural* schema (the four tables
  themselves) still goes through proper Alembic migrations.
- **Automation with a human-legible audit trail** — the scheduler doesn't
  just "run stuff on a timer"; every automated run still produces the same
  scored, itemized, stored, exportable record a manual run would, plus a
  Slack alert when something needs attention.
- **Reporting for non-technical stakeholders** — the dashboard's dataset
  picker, SQL-backed issue-breakdown chart, and CSV export exist because a
  data quality signal that only a Python script can read isn't actually
  useful to a governance/ops audience.

## Known limitations

Written down deliberately, not because they came up in review, but because
an honest account of scope boundaries is worth more than pretending a
demo-sized project has none:

- **OCR ingestion is narrow.** It extracts "label, number, number" rows via
  regex, not arbitrary table structure — and tesseract itself starts
  laying text out in columns instead of rows once a scanned image has
  enough repeated lines, which can break the row-based extractor on a
  larger scan. Structured (CSV/Excel) ingestion has no such limit.
- **Statistical thresholds are hand-tuned, not empirically validated** (the
  90% non-negative ratio for validity, the 20% null threshold for
  completeness, a fuzzy-match score of 60 for consistency). They were
  iterated against test cases and real sample data, not derived from a
  formal study — reasonable for a v1, worth stating rather than implying
  otherwise.
- **No streaming ingestion.** A file is loaded into memory via pandas in
  full — several of the quality rules (duplicate detection, per-entity
  outlier grouping) fundamentally need the whole dataset in memory at once
  to compare rows against each other, so this isn't a small patch. Benchmarked
  at 1,000,000 rows / 28MB: ~2.5s, ~150MB peak memory on a base MacBook Air
  — comfortably fine at that size. `MAX_UPLOAD_SIZE_MB` (config.py, default
  500MB) rejects anything larger with a clear error before it risks an
  out-of-memory crash, rather than leaving that limit undocumented.
- **Auth is a single shared API key**, not per-user accounts or roles — see
  [Auth](#auth) above.

## Project layout

```
ingest/       structured.py (any CSV/Excel schema) + unstructured.py (OCR,
              scoped to power-report-shaped scans — see its docstring)
profiling/    per-column stats, persisted to Postgres per dataset (falls
              back to local flat files only for the DB-free CLI path)
quality/      7 schema-agnostic rule functions + health scoring, each
              independently testable
db/           SQLAlchemy models (JSON row storage), storage, queries.py
              (hand-written SQL for reporting), schema.sql reference
migrations/   Alembic migrations — the schema's actual source of truth
api/          FastAPI app, auth.py (API-key dependency), generic per-run
              profile/preview/export, SQL-backed dataset/report endpoints
frontend/     React + Tailwind + Recharts dashboard: dataset picker, health
              trend, issue breakdown, column profile, data preview, export
scheduler/    watch-folder automation + Slack alerting (actual production
              automation — in-process, via APScheduler)
orchestration/ the same watch-folder job as a real, Airflow-validated DAG
              (not deployed — see orchestration/README.md)
tests/        63 pytest tests (rule-engine/auth tests need no infra; DB/OCR
              tests self-skip without Postgres/tesseract)
.github/      CI: pytest + ruff (backend), oxlint + build (frontend)
data/samples/ demo power-sector CSV + synthetic scanned-report PNG/PDF for
              OCR testing
```
