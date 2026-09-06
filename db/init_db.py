"""Apply every pending Alembic migration (idempotent) — the source of truth
for the schema is migrations/, not this file (see db/models.py's docstring
and migrations/env.py). This is a thin, memorable wrapper around
`alembic upgrade head` for local dev convenience:

    python -m db.init_db
"""
from pathlib import Path

from alembic import command
from alembic.config import Config

REPO_ROOT = Path(__file__).resolve().parent.parent


def init_db() -> None:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    command.upgrade(cfg, "head")


if __name__ == "__main__":
    init_db()
    print("Migrations applied (or already up to date).")
