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
from ingest.structured import guess_entity_column, guess_period_column
from profiling import profile_dataframe, save_profile, load_profile
from quality import run_all_rules, compute_health_score


def run_pipeline(file_path: str, verbose: bool = True, df=None) -> dict:
    """Run ingest -> profile -> quality checks -> health score.

    `df` lets a caller that already loaded the file (e.g.
    run_pipeline_and_store, or the future /ingest endpoint) pass it in
    directly instead of having this function re-read the file from disk.
    """
    run_id = str(uuid.uuid4())[:8]

    # 1. Ingest
    if df is None:
        df = load_structured(file_path)

    # 2. Profile (and load the prior run's profile as a schema-drift baseline)
    baseline_profile = load_profile("latest")
    profile = profile_dataframe(df)

    # 3. Quality checks. No column names are assumed — guess_entity_column /
    # guess_period_column best-effort pick a repeating categorical column
    # (e.g. a state, a store) and a reporting-period column (e.g. a month)
    # if the dataset has them, so outlier_rule can compare each entity
    # against its own history, and group_completeness_rule can catch an
    # entity silently missing from one period.
    period_column = guess_period_column(df)
    entity_column = guess_entity_column(df, exclude={period_column} if period_column else None)
    issues = run_all_rules(
        df, group_by=entity_column, period_by=period_column, baseline_profile=baseline_profile
    )

    # 4. Health score
    score_result = compute_health_score(issues)

    # Persist this run's profile so the *next* run has a schema-drift baseline.
    save_profile(profile, run_id)

    result = {
        "run_id": run_id,
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
    print(f"  DATA QUALITY RUN: {result['run_id']}")
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


def run_pipeline_and_store(file_path: str, verbose: bool = True) -> dict:
    """Same as run_pipeline(), but also persists the result to Postgres.
    Kept as a separate entry point so the DB-free pipeline stays usable on
    its own (see tests/test_pipeline_end_to_end.py) — this is what the
    FastAPI /ingest endpoint will call in stage 3.
    """
    from db.database import SessionLocal
    from db.store import store_pipeline_result

    df = load_structured(file_path)
    result = run_pipeline(file_path, verbose=verbose, df=df)

    db = SessionLocal()
    try:
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
