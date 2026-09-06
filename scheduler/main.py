"""
Standalone scheduler process: runs process_watch_folder() on a fixed
interval, forever. This is what "repeat automatically every month with no
manual re-running" means in practice for the demo — point WATCH_FOLDER at a
real drop folder and this keeps picking up new files without anyone
re-running a script.

The same job also runs in-process inside the FastAPI app (see
api/main.py's lifespan) so `docker-compose up` alone gets automation with
no separate process to remember to start. This standalone entrypoint exists
for running the scheduler independently of the API, e.g.:

    python -m scheduler.main
"""
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from config import SCHEDULER_INTERVAL_MINUTES, WATCH_FOLDER
from scheduler.watcher import process_watch_folder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("scheduler.main")


def main() -> None:
    scheduler = BlockingScheduler()
    scheduler.add_job(
        process_watch_folder,
        "interval",
        minutes=SCHEDULER_INTERVAL_MINUTES,
    )

    logger.info(
        "Scheduler started: watching '%s' every %d minute(s).",
        WATCH_FOLDER,
        SCHEDULER_INTERVAL_MINUTES,
    )

    # Run once immediately on startup, then let the interval trigger take over.
    process_watch_folder()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
