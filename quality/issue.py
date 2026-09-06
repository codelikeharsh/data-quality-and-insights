"""Shared issue type flagged by every quality rule."""
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class Issue:
    row_reference: Any     # e.g. a row index, or "month=2026-02" for a
                            # batch-level issue with no single row
    column: str
    issue_type: str        # matches a key in config.RULE_CONFIG
    description: str
    severity: str = "medium"  # "low" | "medium" | "high" — used by alerting

    def to_dict(self) -> dict:
        return asdict(self)
