from quality.issue import Issue
from quality.health_score import compute_health_score


def test_no_issues_gives_perfect_score():
    result = compute_health_score([])
    assert result["score"] == 100
    assert result["deductions"] == []


def test_score_deducts_by_weight_and_count():
    issues = [
        Issue("r1", "col", "validity", "bad value"),
        Issue("r2", "col", "validity", "bad value"),
    ]
    config = {"validity": {"penalty_weight": 10}}
    result = compute_health_score(issues, rule_config=config)
    assert result["score"] == 80
    assert result["deductions"][0]["points_deducted"] == 20


def test_score_capped_at_zero():
    issues = [Issue(f"r{i}", "col", "validity", "bad") for i in range(50)]
    config = {"validity": {"penalty_weight": 10}}
    result = compute_health_score(issues, rule_config=config)
    assert result["score"] == 0
