"""Create all tables (idempotent) — the source of truth is db/models.py.

    python -m db.init_db
"""
from db.database import Base, engine
from db import models  # noqa: F401  (import registers the models with Base)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
    print("Tables created (or already existed).")
