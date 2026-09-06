# Airflow DAG (not deployed — validated only)

`airflow_dag.py` is the watch-folder automation (see `scheduler/watcher.py`)
expressed as a real Airflow DAG, to demonstrate actual orchestrator syntax
— DAGs, the TaskFlow API (`@dag`/`@task`), dynamic task mapping
(`.expand()`), XCom, retries, `schedule`/`catchup` — rather than claim
Airflow experience with nothing to back it.

**This project's actual production automation stays APScheduler**
(`scheduler/`, wired into `api/main.py`'s lifespan) — this DAG is kept
alongside it, not in place of it, and is not deployed anywhere.

## How this was validated

Installed Airflow 2.10.3 in an isolated venv (kept separate from this
project's own `requirements.txt` — Airflow pins many transitive
dependencies that would otherwise fight this project's own versions) and
confirmed:

```bash
python3 -m venv /tmp/airflow_validate && source /tmp/airflow_validate/bin/activate
pip install "apache-airflow==2.10.3" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.10.3/constraints-3.12.txt"

export AIRFLOW_HOME=/tmp/airflow_home
export PYTHONPATH="/path/to/this/repo:$PYTHONPATH"
mkdir -p "$AIRFLOW_HOME/dags" && cp orchestration/airflow_dag.py "$AIRFLOW_HOME/dags/"
airflow db migrate

airflow dags list-import-errors   # -> "No data found" (zero import errors)
airflow dags list                 # -> data_quality_watch_folder, owner "data-quality-engine"
airflow tasks list data_quality_watch_folder
# -> alert_on_low_scores, discover_files, process_file
```

All three tasks were recognized correctly, with zero import errors — this
is a real, Airflow-validated DAG, not just Python that looks like one.

## To actually run it

```bash
pip install apache-airflow  # or the pinned version + constraints above
export AIRFLOW_HOME=~/airflow
airflow standalone  # scaffolds a local instance, prints an admin password
# copy/symlink airflow_dag.py into $AIRFLOW_HOME/dags/, it'll appear in the UI
```

It needs this project's own dependencies importable too (`pip install -r
requirements.txt` from the repo root, or run from an environment that has
both installed) since its tasks call straight into `run_pipeline`,
`ingest`, and `scheduler.alerts`.
