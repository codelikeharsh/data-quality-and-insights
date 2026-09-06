"""
SQLAlchemy ORM models for the four core tables.

  dataset_rows    - the ingested data, one row per source row, stored as
                    JSON so the schema doesn't need to be known in advance
                    (this table works for any tabular dataset, not just one
                    fixed column layout)
  quality_runs    - one row per ingestion run, with its health score
  quality_issues  - every flagged issue for a run, queryable later
  data_lineage    - source -> transformations -> destination, per file

quality_runs.run_id is the thread tying all four tables together: it's what
makes a row, an issue, and a lineage record traceable back to exactly the
ingestion run that produced them.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import relationship

from db.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class QualityRun(Base):
    """One row per ingestion run — the parent record everything else hangs off."""

    __tablename__ = "quality_runs"

    run_id = Column(String(16), primary_key=True)
    timestamp = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    source_file = Column(String(512), nullable=False)
    # The stable identity a batch of runs belongs to — e.g. "sample_power_data"
    # for every monthly upload of that same feed, distinct from "retail_sales"
    # uploaded five minutes later. Without this, /runs mixes unrelated
    # datasets into one list and a health-score trend chart would plot two
    # different datasets' scores on the same line. Defaults to the uploaded
    # filename's stem (see api/main.py) but can be set explicitly so the
    # same logical dataset stays grouped even if the filename varies
    # (e.g. "power_supply_2026-04.csv" vs "...2026-05.csv").
    dataset_name = Column(String(255), nullable=False, index=True, default="default")
    health_score = Column(Integer, nullable=False)
    rows_processed = Column(Integer, nullable=False)
    rows_flagged = Column(Integer, nullable=False)

    rows = relationship("DatasetRow", back_populates="source_run", cascade="all, delete-orphan")
    issues = relationship("QualityIssue", back_populates="run", cascade="all, delete-orphan")


class DatasetRow(Base):
    """One ingested row, stored as JSON rather than fixed columns — this is
    what makes storage work for any dataset shape without a migration per
    schema. `row_index` is the row's position in the source file, used to
    join back to issues (whose row_reference is that same index)."""

    __tablename__ = "dataset_rows"

    id = Column(Integer, primary_key=True, autoincrement=True)
    row_index = Column(Integer, nullable=False)
    data = Column(JSON, nullable=False)
    source_run_id = Column(String(16), ForeignKey("quality_runs.run_id"), nullable=False, index=True)

    source_run = relationship("QualityRun", back_populates="rows")


class QualityIssue(Base):
    """Every flagged issue for a run — the audit trail behind the health score."""

    __tablename__ = "quality_issues"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(16), ForeignKey("quality_runs.run_id"), nullable=False, index=True)
    row_reference = Column(String(64), nullable=False)
    column = Column("column", String(64), nullable=False)
    issue_type = Column(String(32), nullable=False, index=True)
    description = Column(Text, nullable=False)
    severity = Column(String(16), nullable=False, default="medium")

    run = relationship("QualityRun", back_populates="issues")


class DataLineage(Base):
    """Simple lineage: where data came from, what was done to it, where it landed."""

    __tablename__ = "data_lineage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_file = Column(String(512), nullable=False)
    ingested_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    transformations_applied = Column(JSON, nullable=False)  # e.g. ["load_structured", "run_all_rules", ...]
    destination_table = Column(String(64), nullable=False)
    run_id = Column(String(16), ForeignKey("quality_runs.run_id"), nullable=False)

    # An explicit relationship (not just the raw FK column) is what lets
    # SQLAlchemy's unit-of-work correctly order this insert AFTER its
    # parent quality_runs row within the same flush/commit.
    run = relationship("QualityRun")
