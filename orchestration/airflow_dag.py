"""
Airflow DAG: the same watch-folder automation as scheduler/watcher.py and
scheduler/main.py, expressed as an Airflow DAG instead of an in-process
APScheduler job.

This exists specifically to demonstrate real orchestrator syntax and
concepts (DAGs, the TaskFlow API, dynamic task mapping, XCom, retries,
`schedule`/`catchup`) rather than to replace the APScheduler-based
automation that's actually wired into the running app (see api/main.py's
lifespan and scheduler/main.py) — this project's production automation
stays APScheduler; this DAG is the "here's what the same job looks like
under a dedicated orchestrator" answer, kept alongside it rather than in
place of it.

Not deployed/running anywhere — validated by parsing only (see
orchestration/README.md for how). To actually run it: `pip install
apache-airflow`, point AIRFLOW_HOME's dags folder at this file (or this
directory), and `airflow standalone`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag, task

# Reuses this project's own pipeline code — same ingest -> profile ->
# quality checks -> health score -> store logic the API/scheduler use,
# just triggered by Airflow instead of APScheduler.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_ARGS = {
    "owner": "data-quality-engine",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


@dag(
    dag_id="data_quality_watch_folder",
    description="Ingest any new files in the watch folder through the quality pipeline, then alert on low scores.",
    schedule="0 * * * *",  # hourly, matching config.SCHEDULER_INTERVAL_MINUTES's default
    start_date=datetime(2026, 1, 1),
    catchup=False,  # this is a "process what's new right now" job, not a backfill-able one
    default_args=DEFAULT_ARGS,
    tags=["data-quality", "governance"],
)
def data_quality_watch_folder():
    @task
    def discover_files() -> list[str]:
        """Every unprocessed file currently sitting in the watch folder."""
        from config import WATCH_FOLDER

        folder = Path(WATCH_FOLDER)
        if not folder.exists():
            return []
        return [str(p) for p in folder.iterdir() if p.is_file()]

    @task
    def process_file(file_path: str) -> dict:
        """Run one file through the full pipeline and store the result —
        the same work scheduler/watcher.py::process_file does, called
        directly here since Airflow's own retry/logging infra replaces the
        try/except-and-move-to-FAILED_FOLDER pattern that function uses to
        stay safe under APScheduler's fire-and-forget execution model."""
        from run_pipeline import run_pipeline_and_store

        result = run_pipeline_and_store(file_path, verbose=False)
        return {
            "run_id": result["run_id"],
            "dataset_name": result["dataset_name"],
            "health_score": result["health_score"]["score"],
            "high_severity_issues": [i for i in result["issues"] if i["severity"] == "high"],
        }

    @task
    def alert_on_low_scores(results: list[dict]) -> None:
        """Slack-alert (or log, if no webhook configured) for any run that
        needs one — mirrors scheduler/alerts.py::should_alert's logic."""
        from config import ALERT_HEALTH_SCORE_THRESHOLD
        from scheduler.alerts import send_slack_alert

        for r in results:
            needs_alert = r["health_score"] < ALERT_HEALTH_SCORE_THRESHOLD or r["high_severity_issues"]
            if needs_alert:
                send_slack_alert(
                    {
                        "run_id": r["run_id"],
                        "source_file": r["dataset_name"],
                        "health_score": {"score": r["health_score"]},
                        "rows_processed": 0,
                        "rows_flagged": len(r["high_severity_issues"]),
                        "issues": r["high_severity_issues"],
                    }
                )

    # Dynamic task mapping: one process_file task instance per discovered
    # file, run in parallel by Airflow's executor — this is what lets a
    # month with 5 new files and a month with 50 use the same DAG
    # definition without hand-writing a task per file.
    files = discover_files()
    results = process_file.expand(file_path=files)
    alert_on_low_scores(results)


data_quality_watch_folder()
