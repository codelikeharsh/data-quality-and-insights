# Data Quality & Insights Engine

A full-stack data governance tool that ingests **any tabular dataset**
(CSV/Excel, or a scanned tabular report), automatically profiles and
quality-checks it against no fixed schema, scores it, stores it with
lineage, and surfaces the result on a dashboard — with no manual re-running
required once new data arrives.

## The pitch

Any team that receives periodic data files — monthly submissions from
branches, states, vendors, sensors, whatever — eventually has to answer the
same questions before trusting a batch:

- Is everything that should be here, here?
- Are the values plausible, or is there an obvious decimal/unit error?
- Did the same real-world thing get spelled two different ways somewhere,
  quietly fragmenting every `GROUP BY` downstream?
- Has the file's shape changed since last time, unannounced?
- Given all of that, how much can we trust this batch, and exactly why?

This project automates that check end to end — **ingest → profile → quality
rules → health score → store with lineage → dashboard → alert** — for
**whatever columns the file actually has**. Nothing in the rule engine,
storage layer, or API assumes a fixed schema; every rule either works on
any dataset by construction (a null-rate check needs no domain knowledge)
or auto-detects the shape it needs (e.g. "which column looks like a
reporting period?") rather than having it hardcoded.

The bundled demo dataset is Indian state-wise power supply data
([`data/samples/sample_power_data.csv`](data/samples/sample_power_data.csv),
Ministry-of-Power-style, with four intentionally planted problems — see
below), because a concrete example is easier to reason about than an
abstract one. It is **one example among many the engine handles**, not the
thing the engine was built for — see [Proof it's actually generic](#proof-its-actually-generic)
below, where the exact same code (zero changes) catches four different
planted problems in a completely different retail-sales dataset with
different column names.

## Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │              React Dashboard                 │
                    │  Upload · Health trend · Column profile ·     │
                    │  Data preview · Issues (Vite+Tailwind+Recharts)│
                    └───────────────────┬───────────────────────────┘
                                        │ HTTP (fetch)
                                        ▼
                    ┌─────────────────────────────────────────────┐
                    │                FastAPI (api/)                 │
                    │  POST /ingest    GET /runs                    │
                    │  GET /runs/{id}/issues                        │
                    │  GET /runs/{id}/profile                       │
                    │  GET /runs/{id}/preview                       │
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
              │              stats + JSON  │
              │  quality/    7 rule        │
              │              functions +   │
              │              health score, │
              │              all schema-   │
              │              agnostic      │
              └─────────────┬──────────────┘
                            │
                            ▼
              ┌──────────────────────────────────────┐
              │            PostgreSQL (db/)            │
              │  dataset_rows   — every row, as JSON   │
              │                    (any schema fits)   │
              │  quality_runs   — one row per run       │
              │  quality_issues — every flagged issue   │
              │  data_lineage   — source → transforms   │
              │                    → destination        │
              └──────────────────────────────────────┘
```

Both ingestion paths (`ingest/structured.py` for CSV/Excel,
`ingest/unstructured.py` for OCR'd PDFs/images) produce the same shape of
output — a DataFrame — so profiling, quality rules, scoring, and storage
never know or care which kind of file the data came from. Note the one
deliberate scope boundary: the **structured** path (CSV/Excel) is fully
schema-agnostic; the **OCR** path is not — extracting arbitrary table
structure from a scanned image is a much harder problem, so it stays
narrowly scoped to a "label, number, number" row shape (see
`ingest/unstructured.py`'s docstring). That limitation is stated up front
rather than glossed over.

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
   dtypes against the previous run's).
2. **Auto-detects the column it needs**, rather than requiring one by name:
   `guess_entity_column` and `guess_period_column`
   (`ingest/structured.py`) best-effort pick "the column that looks like a
   repeating entity" (lowest unique-ratio categorical column) and "the
   column that looks like a reporting period" (name matches
   month/date/year/period/quarter/week/fiscal), so `outlier_rule` can
   compare each entity against its own history and
   `group_completeness_rule` can catch an entity silently missing from one
   period — both skip cleanly (no-op, not an error) on a dataset with
   neither shape.

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
config changes) with four planted problems of its own:

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

Python · FastAPI · React (plain fetch, Tailwind) · PostgreSQL · SQLAlchemy ·
pandas/numpy · rapidfuzz (near-duplicate detection) · pytesseract + pdf2image
(OCR) · APScheduler · Slack webhooks · Docker Compose · pytest

## Setup

### Option A — Docker Compose (everything at once)

```bash
docker-compose up --build
```

This starts three services: `db` (Postgres), `backend` (FastAPI, with the
scheduler running in-process), and `frontend` (the React dashboard, built
and served via nginx). Because this dev machine already had a native
Postgres on 5432 and something else on 8000, the compose file maps to
**host** ports `5433` (Postgres), `8001` (API), `5173` (frontend) instead of
the defaults — adjust in [`docker-compose.yml`](docker-compose.yml) if your
machine is free of those conflicts. Once it's up:

- Dashboard: http://localhost:5173
- API docs: http://localhost:8001/docs

### Option B — run everything locally (what was used to build/verify this)

```bash
# 1. Postgres (only the db service, via Docker)
docker-compose up -d db

# 2. Backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python -m db.init_db          # creates tables (idempotent)
uvicorn api.main:app --reload --port 8000

# 3. Frontend (separate terminal)
cd frontend
npm install
npm run dev                    # http://localhost:5173
```

Copy `.env.example` → `.env` (backend) and `frontend/.env.example` →
`frontend/.env.local` (frontend) and adjust ports/URLs if you changed the
Docker mapping.

### Option C — CLI only, no DB/API (fastest way to see the rule engine work)

```bash
source venv/bin/activate
python run_pipeline.py data/samples/sample_power_data.csv
# or point it at any CSV/Excel file of your own — no setup needed:
python run_pipeline.py /path/to/your_data.csv
```

### Running the test suite

```bash
pytest tests/ -v
```

Tests that need Postgres or `tesseract` self-skip when those aren't
available, so `pytest` still passes in a minimal environment — the DB/OCR
tests just won't run. 53 tests total.

## The four seeded problems in the bundled demo (and what catches them)

| Problem | Where | Rule that catches it |
|---|---|---|
| Bihar missing entirely | `2026-02` | `group_completeness_rule` (auto-detected entity=`state_name`, period=`month`) |
| "Orissa" instead of "Odisha" | `2026-03` | `consistency_rule` (self-referential near-duplicate detection) |
| Negative `energy_availability_mu` | Jharkhand, `2026-01` | `validity_rule` |
| `energy_requirement_mu` = 999999 | Delhi, `2026-03` | `outlier_rule` (median/MAD z-score, per-state history) |

Running the CLI against the sample data scores it **65/100** and lists all
four issues with a transparent, itemized point breakdown.

## Data governance concepts, mapped to features (interview talking points)

- **Data profiling** (`profiling/profiler.py`) — the "know your data before
  you judge it" step, computed for any column set. Every run's profile is
  saved as JSON and doubles as the baseline the next run's schema-drift
  check compares against.
- **Data quality dimensions, implemented as independent, schema-agnostic
  rules** (`quality/rules.py`):
  - *Completeness* — null-rate per column, plus (when an entity+period
    shape is detected) "did this entity silently stop reporting?"
  - *Validity* — a numeric column that's almost always non-negative
    flags its rare negative values as likely data-entry/unit errors — a
    relative, data-driven check, not a hardcoded domain constant.
  - *Accuracy / plausibility* — outlier detection catches decimal/unit
    errors a schema check alone would miss, on every numeric column.
  - *Consistency* — self-referential near-duplicate detection catches the
    exact kind of naming drift that silently fragments a `GROUP BY` or
    breaks a join, without needing an external reference list.
  - *Uniqueness* — exact-duplicate-row detection.
  - *Schema stability* — drift detection flags a new/missing/retyped
    column before it breaks something downstream.
- **Transparent scoring, not a black box** (`quality/health_score.py`) — a
  data health score means nothing to a governance stakeholder if they can't
  see why it dropped. Every point deducted is itemized by issue type and
  weight, and weights live in one config file an analyst can tune without
  reading code.
- **Lineage** (`db/models.py::DataLineage`) — every run records its source
  file, the transformations applied, and its destination table. This is the
  minimum viable answer to "where did this number in the dashboard actually
  come from?"
- **Schema-agnostic storage** (`db/models.py::DatasetRow`) — every ingested
  row is stored as JSON rather than fixed columns, so a new dataset shape
  needs zero migrations.
- **Source-agnostic structured ingestion** — the rule engine, profiler, and
  storage layer don't know or care what columns a CSV/Excel file has.
- **Automation with a human-legible audit trail** — the scheduler doesn't
  just "run stuff on a timer"; every automated run still produces the same
  scored, itemized, stored record a manual run would, plus an alert when
  something needs attention.

## Configuration

Every rule's on/off switch and penalty weight lives in [`config.py`](config.py)
(`RULE_CONFIG`), not scattered through the codebase — an analyst should be
able to retune thresholds without touching rule logic. See
[`.env.example`](.env.example) for runtime config (DB connection, Slack
webhook, alert threshold, scheduler interval).

## Project layout

```
ingest/       structured.py (any CSV/Excel schema) + unstructured.py (OCR,
              scoped to power-report-shaped scans — see its docstring)
profiling/    per-column stats -> JSON, for any column set
quality/      7 schema-agnostic rule functions + health scoring, each
              independently testable
db/           SQLAlchemy models (JSON row storage), storage, schema.sql
api/          FastAPI app + generic per-run profile/preview aggregation
frontend/     React + Tailwind + Recharts dashboard (renders whatever
              columns a run's profile/preview actually returns)
scheduler/    watch-folder automation + Slack alerting
tests/        pytest suite (rule-engine tests need no infra; DB/OCR tests
              self-skip)
data/samples/ demo power-sector CSV + synthetic scanned-report PNG/PDF for
              OCR testing
```
