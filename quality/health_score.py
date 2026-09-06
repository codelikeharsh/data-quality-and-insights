"""
Health scoring: combine every flagged issue into a single 0-100 Data Health
Score per ingestion run.

The weighting is intentionally simple and fully transparent — each issue
type has a configurable penalty weight (config.RULE_CONFIG[type].penalty_weight),
the score starts at 100 and is deducted per issue, and is capped at 0. This
is a deliberate design choice for a governance tool: a black-box score would
undermine the whole point, which is to let an analyst explain *why* a batch
scored the way it did.
"""
from config import RULE_CONFIG
from quality.issue import Issue

STARTING_SCORE = 100


def compute_health_score(issues: list[Issue], rule_config: dict | None = None) -> dict:
    """Return {score, starting_score, deductions: [...], issue_counts: {...}}.

    `deductions` itemizes exactly how the score was arrived at, so it can be
    rendered directly in the API/dashboard as an explanation.
    """
    rule_config = rule_config or RULE_CONFIG

    issue_counts: dict[str, int] = {}
    for issue in issues:
        issue_counts[issue.issue_type] = issue_counts.get(issue.issue_type, 0) + 1

    deductions = []
    total_deduction = 0
    for issue_type, count in issue_counts.items():
        weight = rule_config.get(issue_type, {}).get("penalty_weight", 5)
        subtotal = weight * count
        total_deduction += subtotal
        deductions.append(
            {
                "issue_type": issue_type,
                "count": count,
                "penalty_weight": weight,
                "points_deducted": subtotal,
            }
        )

    score = max(0, STARTING_SCORE - total_deduction)

    return {
        "score": score,
        "starting_score": STARTING_SCORE,
        "total_deducted": total_deduction,
        "deductions": sorted(deductions, key=lambda d: -d["points_deducted"]),
        "issue_counts": issue_counts,
        "total_issues": len(issues),
    }
