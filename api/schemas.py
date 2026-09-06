"""Pydantic response models for the API — the contract the React frontend
(and any interviewer poking at /docs) reads against."""
from datetime import datetime

from pydantic import BaseModel


class IssueOut(BaseModel):
    # row_reference is a DataFrame row index (int) for row-level issues, or
    # a string like "month=2026-02" for batch-level ones (e.g. completeness).
    row_reference: str | int
    column: str
    issue_type: str
    description: str
    severity: str

    model_config = {"from_attributes": True}


class HealthScoreDeduction(BaseModel):
    issue_type: str
    count: int
    penalty_weight: int
    points_deducted: int


class HealthScoreOut(BaseModel):
    score: int
    starting_score: int
    total_deducted: int
    deductions: list[HealthScoreDeduction]
    issue_counts: dict[str, int]
    total_issues: int


class IngestResponse(BaseModel):
    run_id: str
    dataset_name: str
    source_file: str
    rows_processed: int
    rows_flagged: int
    health_score: HealthScoreOut
    issues: list[IssueOut]


class RunSummaryOut(BaseModel):
    run_id: str
    dataset_name: str
    timestamp: datetime
    source_file: str
    health_score: int
    rows_processed: int
    rows_flagged: int

    model_config = {"from_attributes": True}


class DatasetSummaryOut(BaseModel):
    dataset_name: str
    latest_run_id: str
    latest_run_at: datetime
    latest_health_score: int
    rows_processed: int
    rows_flagged: int
    run_count: int
    avg_health_score: float
    worst_health_score: int
    best_health_score: int


class IssueBreakdownOut(BaseModel):
    issue_type: str
    severity: str
    issue_count: int
    runs_affected: int


class ColumnProfileOut(BaseModel):
    dtype: str
    null_count: int
    null_pct: float
    # numeric columns
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    std: float | None = None
    # text columns
    unique_count: int | None = None
    unique_values: list[str] | None = None


class RunProfileOut(BaseModel):
    generated_at: str
    row_count: int
    columns: dict[str, ColumnProfileOut]
