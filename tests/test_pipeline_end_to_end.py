"""
End-to-end check that the full pipeline, run against the seeded sample
dataset, catches exactly the four intentionally planted problems described
in the project brief:
  1. Bihar missing entirely for 2026-02 (completeness)
  2. "Orissa" instead of "Odisha" for 2026-03 (consistency)
  3. Jharkhand negative energy_availability_mu for 2026-01 (validity)
  4. Delhi's absurd energy_requirement_mu of 999999 for 2026-03 (outlier)
"""
from pathlib import Path

from run_pipeline import run_pipeline

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "samples" / "sample_power_data.csv"


def test_pipeline_catches_all_seeded_issues():
    result = run_pipeline(str(SAMPLE), verbose=False)
    issues_by_type = {}
    for issue in result["issues"]:
        issues_by_type.setdefault(issue["issue_type"], []).append(issue)

    # 1. Completeness: Bihar missing in Feb
    assert any(
        "Bihar" in i["description"] and "2026-02" in i["row_reference"]
        for i in issues_by_type.get("completeness", [])
    )

    # 2. Consistency: Orissa vs Odisha
    assert any(
        "Orissa" in i["description"] for i in issues_by_type.get("consistency", [])
    )

    # 3. Validity: Jharkhand negative availability
    assert any(
        i["column"] == "energy_availability_mu" and "-120" in i["description"]
        for i in issues_by_type.get("validity", [])
    )

    # 4. Outlier: Delhi's 999999 requirement
    assert any(
        "999999" in i["description"] for i in issues_by_type.get("outlier", [])
    )

    # Health score should be meaningfully below 100 given four real issues.
    assert 0 <= result["health_score"]["score"] < 100
