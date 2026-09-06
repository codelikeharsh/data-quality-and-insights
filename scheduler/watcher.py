"""
Watch-folder job: simulates new monthly files arriving on their own, the
way a real state power department's submission would land in a shared
drive/SFTP folder rather than through someone clicking "upload" in a
dashboard. Each run of process_watch_folder() picks up every new file in
WATCH_FOLDER, runs it through the same ingest -> profile -> quality checks
-> health score -> store pipeline as the API's /ingest endpoint, then moves
the file out of the way so it isn't reprocessed next interval.
"""
import logging
import re
import shutil
from pathlib import Path

from config import FAILED_FOLDER, PROCESSED_FOLDER, WATCH_FOLDER
from db.database import SessionLocal
from db.store import store_pipeline_result
from ingest import load_structured, load_unstructured
from run_pipeline import run_pipeline
from scheduler.alerts import send_slack_alert

logger = logging.getLogger("scheduler.watcher")

STRUCTURED_EXTENSIONS = (".csv", ".xlsx", ".xls")
UNSTRUCTURED_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".tiff")

# Looks for a "YYYY-MM" token in the filename (e.g. "power_report_2026-04.pdf")
# — a scanned file carries no month in its own data, and unattended
# automation has no one to ask, so the filename is the only signal available.
_MONTH_IN_FILENAME = re.compile(r"(\d{4}-\d{2})")


def _infer_month(filename: str) -> str | None:
    match = _MONTH_IN_FILENAME.search(filename)
    return match.group(1) if match else None


def _move(path: Path, destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(destination_dir / path.name))


def process_file(path: Path) -> dict | None:
    """Run one file through the full pipeline and store the result.
    Returns the run result dict, or None if the file couldn't be processed
    (moved to FAILED_FOLDER instead of PROCESSED_FOLDER in that case).
    """
    suffix = path.suffix.lower()

    try:
        if suffix in STRUCTURED_EXTENSIONS:
            df = load_structured(path)
        elif suffix in UNSTRUCTURED_EXTENSIONS:
            month = _infer_month(path.name)
            if month is None:
                logger.warning(
                    "Skipping '%s': scanned file with no 'YYYY-MM' in its filename, "
                    "so the month can't be determined without a person to ask.",
                    path.name,
                )
                _move(path, Path(FAILED_FOLDER))
                return None
            df = load_unstructured(path, month=month)
            if df.empty:
                logger.warning("Skipping '%s': OCR extracted 0 rows.", path.name)
                _move(path, Path(FAILED_FOLDER))
                return None
            df = df.drop(columns=["extraction_confidence"])
        else:
            logger.warning("Skipping '%s': unsupported file type '%s'.", path.name, suffix)
            _move(path, Path(FAILED_FOLDER))
            return None

        result = run_pipeline(str(path), verbose=False, df=df)

        db = SessionLocal()
        try:
            store_pipeline_result(db, result, df)
        finally:
            db.close()

    except Exception:
        logger.exception("Failed to process '%s'", path.name)
        _move(path, Path(FAILED_FOLDER))
        return None

    _move(path, Path(PROCESSED_FOLDER))

    if send_slack_alert(result):
        logger.info(
            "Alert dispatched for run %s (score %s)",
            result["run_id"],
            result["health_score"]["score"],
        )

    return result


def process_watch_folder(watch_folder: str = WATCH_FOLDER) -> list[dict]:
    """Process every file currently sitting in the watch folder. This is
    the function APScheduler calls on its interval (see scheduler/main.py
    and api/main.py's lifespan)."""
    folder = Path(watch_folder)
    folder.mkdir(parents=True, exist_ok=True)

    results = []
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        result = process_file(path)
        if result is not None:
            results.append(result)

    if results:
        logger.info("Watch-folder run processed %d file(s).", len(results))

    return results
