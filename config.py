"""
Central configuration for the Data Quality & Insights Engine.

Values here are meant to be tuned without touching rule logic — a data
governance analyst should be able to change a threshold in this file (or the
matching .env var) without reading Python.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# --- Database -------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    # Port 5433 (not 5432) — the docker-compose Postgres service is mapped
    # there to avoid colliding with a native Postgres install on 5432.
    "postgresql+psycopg2://dqe:dqe@localhost:5433/dqe",
)

# --- Alerting ---------------------------------------------------------------
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
ALERT_HEALTH_SCORE_THRESHOLD = float(os.getenv("ALERT_HEALTH_SCORE_THRESHOLD", "70"))

# --- Scheduler ---------------------------------------------------------------
# Deliberately separate from UPLOAD_DIR (used by the /ingest API endpoint) —
# files dropped here simulate new monthly submissions arriving on their own,
# distinct from a person manually uploading through the dashboard.
WATCH_FOLDER = os.getenv("WATCH_FOLDER", str(BASE_DIR / "data" / "incoming"))
PROCESSED_FOLDER = os.getenv("PROCESSED_FOLDER", str(BASE_DIR / "data" / "processed"))
FAILED_FOLDER = os.getenv("FAILED_FOLDER", str(BASE_DIR / "data" / "failed"))
SCHEDULER_INTERVAL_MINUTES = int(os.getenv("SCHEDULER_INTERVAL_MINUTES", "60"))
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"

# --- Optional domain reference data -----------------------------------------
# The engine itself is schema-agnostic (see quality/rules.py) and does not
# require this list. It exists only so the bundled power-sector sample
# dataset/demo can pass an accurate reference set to completeness checks if
# a caller chooses to (28 states + 8 union territories of India).
CANONICAL_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
    "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya",
    "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim",
    "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal",
    # Union Territories
    "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir",
    "Ladakh", "Lakshadweep", "Puducherry",
]

# --- Quality rule engine ------------------------------------------------
# Every rule here works on ANY tabular dataset — none of them hardcode a
# column name or a domain reference list. Each rule can be independently
# toggled on/off, and each issue type has a configurable penalty weight used
# by the health score. See quality/rules.py for what each rule actually does.
RULE_CONFIG = {
    "completeness": {
        "enabled": True,
        "penalty_weight": 4,           # points deducted per flagged column
        "null_pct_threshold": 20.0,    # flag a column once >20% of its
                                        # values are missing
    },
    "duplicate": {
        "enabled": True,
        "penalty_weight": 3,   # points deducted per duplicate row
    },
    "validity": {
        "enabled": True,
        "penalty_weight": 10,  # points deducted per invalid value
        "nonnegative_ratio_threshold": 0.90,  # if >=90% of a numeric
            # column's values are >= 0, treat the rare negative ones as
            # likely data-entry errors rather than a legitimate negative
            # metric (e.g. profit/loss). A column that's routinely negative
            # (below this ratio) is left alone — this is a relative,
            # data-driven check, not a hardcoded "energy can't be negative"
            # domain rule.
    },
    "outlier": {
        "enabled": True,
        "penalty_weight": 6,   # points deducted per statistical outlier
        "method": "zscore",    # "iqr" or "zscore" (modified/MAD-based z-score)
        "group_by": None,      # optionally set to a column name so each
                                # entity (e.g. one state, one store) is
                                # compared against its OWN history rather
                                # than the whole column — otherwise a
                                # naturally large entity gets flagged just
                                # for being bigger than a small one. Left
                                # unset by default since a generic dataset
                                # has no known entity column; run_pipeline
                                # auto-detects one when it's obvious (see
                                # ingest/structured.py::guess_entity_column).
        "min_group_size": 3,   # need at least this many points per group
                                # to judge what's "normal" for it
        "iqr_multiplier": 1.5,
        "zscore_threshold": 3.5,   # standard cutoff for a modified z-score
    },
    "consistency": {
        "enabled": True,
        "penalty_weight": 5,   # points deducted per fuzzy-matched naming issue
        "fuzzy_match_threshold": 60,  # rapidfuzz score (0-100) a rare value
                                       # needs against a common one to be
                                       # flagged as a likely typo of it.
                                       # Deliberately lower than it looks:
                                       # short-string rename pairs like
                                       # "Orissa"/"Odisha" score only ~67 on
                                       # every rapidfuzz scorer (edit
                                       # distance is a large fraction of a
                                       # 6-7 character string), so a
                                       # "confident-looking" threshold like
                                       # 85 would miss exactly the naming
                                       # drift this rule exists to catch
        "max_unique_ratio": 0.5,      # skip near-duplicate detection on a
                                       # column where more than half the
                                       # values are unique — that's a
                                       # free-text/ID column, not a
                                       # categorical one, and fuzzy-matching
                                       # it would just produce noise
        "min_value_count": 2,         # a value needs at least this many
                                       # OTHER occurrences of something more
                                       # common before it's flagged as a
                                       # likely typo of that more-common value
    },
    "schema_drift": {
        "enabled": True,
        "penalty_weight": 15,  # points deducted per schema change
    },
}

PROFILE_DIR = BASE_DIR / "data" / "profiles"
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
