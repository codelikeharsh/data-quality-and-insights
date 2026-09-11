#!/usr/bin/env python3
"""
CLI entry point for Stage 1: run the full ingest -> profile -> quality
checks -> health score pipeline against a file, with no database or API
involved yet. This is the fastest way to verify the rule engine end-to-end
before wrapping it in FastAPI/Postgres.

Usage:
    python run_pipeline.py data/samples/sample_power_data.csv
"""
import argparse
import sys
import uuid
from pathlib import Path

from ingest import load_structured
from ingest.structured import (
    guess_all_period_like_columns,
    guess_entity_column,
    guess_id_like_numeric_columns,
    guess_period_column,
)
from profiling import profile_dataframe, save_profile, load_profile
from quality import run_all_rules, compute_health_score


def _default_dataset_name(file_path: str) -> str:
    """The stable identity a batch of runs belongs to, e.g. "sample_power_data"
    for data/samples/sample_power_data.csv. Strips a leading 8-hex-char
    upload-dedup prefix (see api/main.py's f"{uuid4().hex[:8]}_{filename}")
    so two uploads of the same logical file group together instead of each
    getting its own dataset."""
    stem = Path(file_path).stem
    if len(stem) > 9 and stem[8] == "_" and all(c in "0123456789abcdef" for c in stem[:8]):
        stem = stem[9:]
    return stem or "default"


_UNSET = object()  # sentinel: distinguishes "caller didn't pass this" from "caller passed None"


def run_pipeline(
    file_path: str,
    verbose: bool = True,
    df=None,
    dataset_name: str | None = None,
    baseline_profile=_UNSET,
    persist_profile_locally: bool = True,
) -> dict:
    """Run ingest -> profile -> quality checks -> health score.

    `df` lets a caller that already loaded the file (e.g.
    run_pipeline_and_store, or the FastAPI /ingest endpoint) pass it in
    directly instead of having this function re-read the file from disk.
    `dataset_name` groups this run with other runs of the same logical
    dataset (see db.models.QualityRun.dataset_name) — defaults to the
    source filename's stem.

    `baseline_profile`, if given, is used as-is instead of looking one up
    from the local flat-file store — this is what lets a DB-aware caller
    (api/main.py) pass a baseline loaded from Postgres via
    db.queries.get_latest_profile, which works correctly across multiple
    backend instances; the flat-file lookup below only reflects THIS
    process's own disk, which is fine for the single-process CLI/test path
    this function was originally built for, but not for a scaled-out API.
    `persist_profile_locally=False` skips the matching local-disk write,
    for the same DB-backed caller (it persists the profile via
    db.store.store_pipeline_result instead — see db.models.DatasetProfile).
    """
    run_id = str(uuid.uuid4())[:8]
    dataset_name = dataset_name or _default_dataset_name(file_path)

    # 1. Ingest
    if df is None:
        df = load_structured(file_path)

    # 2. Profile (and load the prior run's profile, FOR THIS DATASET, as a
    # schema-drift baseline — a different dataset's profile is not a valid
    # baseline, see profiling.profiler.save_profile's docstring)
    if baseline_profile is _UNSET:
        baseline_profile = load_profile("latest", dataset_name=dataset_name)
    profile = profile_dataframe(df)

    # 3. Quality checks. No column names are assumed — guess_entity_column /
    # guess_period_column best-effort pick a repeating categorical column
    # (e.g. a state, a store) and a reporting-period column (e.g. a month)
    # if the dataset has them, so outlier_rule can compare each entity
    # against its own history, and group_completeness_rule can catch an
    # entity silently missing from one period.
    period_column = guess_period_column(df)
    # Exclude every date-like column from entity candidacy, not just the
    # one chosen as THE period — a dataset can have more than one (e.g.
    # "order_date" and "ship_date"); neither should ever become "the entity".
    entity_column = guess_entity_column(df, exclude=guess_all_period_like_columns(df))
    id_columns = guess_id_like_numeric_columns(df)
    issues = run_all_rules(
        df,
        group_by=entity_column,
        period_by=period_column,
        baseline_profile=baseline_profile,
        id_columns=id_columns,
    )

    # 4. Health score
    score_result = compute_health_score(issues)

    # Persist this run's profile locally so the *next* run of THIS dataset
    # has a schema-drift baseline — skipped when the caller will persist it
    # to Postgres instead (see db.models.DatasetProfile).
    if persist_profile_locally:
        save_profile(profile, run_id, dataset_name=dataset_name)

    result = {
        "run_id": run_id,
        "dataset_name": dataset_name,
        "source_file": str(file_path),
        "rows_processed": len(df),
        "rows_flagged": len({i.row_reference for i in issues}),
        "health_score": score_result,
        "issues": [i.to_dict() for i in issues],
        "profile": profile,
    }

    if verbose:
        _print_report(result)

    return result


def _print_report(result: dict) -> None:
    print(f"\n{'=' * 60}")
    print(f"  DATA QUALITY RUN: {result['run_id']}  (dataset: {result['dataset_name']})")
    print(f"{'=' * 60}")
    print(f"Source file:     {result['source_file']}")
    print(f"Rows processed:  {result['rows_processed']}")
    print(f"Rows flagged:    {result['rows_flagged']}")

    score = result["health_score"]
    print(f"\nHEALTH SCORE: {score['score']} / 100")
    if score["deductions"]:
        print("\nDeductions:")
        for d in score["deductions"]:
            print(
                f"  - {d['issue_type']:<14} x{d['count']:<3} "
                f"@ -{d['penalty_weight']} pts each = -{d['points_deducted']} pts"
            )

    if result["issues"]:
        print(f"\nFLAGGED ISSUES ({len(result['issues'])}):")
        for issue in result["issues"]:
            print(
                f"  [{issue['severity'].upper():<6}] {issue['issue_type']:<12} "
                f"row={issue['row_reference']} col={issue['column']}: {issue['description']}"
            )
    else:
        print("\nNo issues flagged.")
    print(f"{'=' * 60}\n")


def run_pipeline_and_store(file_path: str, verbose: bool = True, dataset_name: str | None = None) -> dict:
    """Same as run_pipeline(), but also persists the result to Postgres —
    including the schema-drift baseline lookup/persistence, which comes
    from and goes to Postgres here (db.queries.get_latest_profile /
    db.models.DatasetProfile) rather than local disk, so this works
    correctly no matter how many backend instances are running. Kept as a
    separate entry point so the DB-free pipeline stays usable on its own
    (see tests/test_pipeline_end_to_end.py) — this is what the FastAPI
    /ingest endpoint effectively does (see api/main.py).
    """
    from db.database import SessionLocal
    from db.queries import get_latest_profile
    from db.store import store_pipeline_result

    df = load_structured(file_path)
    resolved_dataset_name = dataset_name or _default_dataset_name(file_path)

    db = SessionLocal()
    try:
        baseline_profile = get_latest_profile(db, resolved_dataset_name)
        result = run_pipeline(
            file_path,
            verbose=verbose,
            df=df,
            dataset_name=resolved_dataset_name,
            baseline_profile=baseline_profile,
            persist_profile_locally=False,
        )
        store_pipeline_result(db, result, df)
    finally:
        db.close()

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the data quality pipeline on a file.")
    parser.add_argument("file", help="Path to a CSV/Excel file to ingest")
    parser.add_argument(
        "--store", action="store_true", help="Also persist the result to Postgres"
    )
    args = parser.parse_args()

    if not Path(args.file).exists():
        print(f"File not found: {args.file}", file=sys.stderr)
        sys.exit(1)

    if args.store:
        run_pipeline_and_store(args.file)
    else:
        run_pipeline(args.file)
