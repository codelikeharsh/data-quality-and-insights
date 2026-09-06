"""Unit tests for each quality rule, independent of DB/API/pipeline.

None of these rules require a specific column name or dataset shape — the
test data below uses power-sector-flavored column names purely for realism,
but the same assertions would hold for any other domain's columns.
"""
import pandas as pd
import pytest

from config import RULE_CONFIG
from quality.rules import (
    completeness_rule,
    duplicate_rule,
    validity_rule,
    outlier_rule,
    consistency_rule,
    schema_drift_rule,
)


# --- completeness_rule (generic: null-rate per column) ------------------


def test_completeness_flags_high_null_column():
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [1, None, None, None, None]})
    issues = completeness_rule(df)
    assert len(issues) == 1
    assert issues[0].column == "b"
    assert issues[0].issue_type == "completeness"


def test_completeness_no_flags_below_threshold():
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5], "b": [1, 2, 3, 4, None]})
    assert completeness_rule(df) == []


def test_completeness_respects_disabled_config():
    df = pd.DataFrame({"a": [None, None, None]})
    issues = completeness_rule(df, config={"enabled": False})
    assert issues == []


# --- duplicate_rule -------------------------------------------------


def test_duplicate_flags_exact_duplicate_row():
    df = pd.DataFrame({"a": [1, 2, 1], "b": ["x", "y", "x"]})
    issues = duplicate_rule(df)
    assert len(issues) == 1
    assert issues[0].row_reference == 2
    assert issues[0].issue_type == "duplicate"


def test_duplicate_no_flags_for_unique_rows():
    df = pd.DataFrame({"a": [1, 2, 3]})
    assert duplicate_rule(df) == []


# --- validity_rule (generic: rare negative in an otherwise non-negative column) ---


def test_validity_flags_negative_value():
    # >=95% of the column's values must be non-negative before a rare
    # negative reads as an error rather than a routinely-negative metric —
    # needs enough rows for one negative to still clear that ratio.
    availability = [95, -50] + [140 + i for i in range(20)]
    df = pd.DataFrame(
        {
            "energy_requirement_mu": [100] * len(availability),
            "energy_availability_mu": availability,
        }
    )
    issues = validity_rule(df)
    assert len(issues) == 1
    assert issues[0].column == "energy_availability_mu"
    assert issues[0].row_reference == 1


def test_validity_no_flags_for_all_positive():
    df = pd.DataFrame(
        {"energy_requirement_mu": [100, 200], "energy_availability_mu": [95, 190]}
    )
    assert validity_rule(df) == []


def test_validity_ignores_nulls():
    df = pd.DataFrame({"energy_requirement_mu": [100, None]})
    assert validity_rule(df) == []


def test_validity_leaves_routinely_negative_column_alone():
    """A column that's negative most of the time (e.g. profit/loss) is not
    an error pattern — only a RARE negative in an otherwise non-negative
    column is suspicious."""
    df = pd.DataFrame({"profit_loss": [-10, -20, -5, 8, -12]})
    assert validity_rule(df) == []


# --- outlier_rule -------------------------------------------------


def test_outlier_flags_extreme_value_within_group():
    df = pd.DataFrame(
        {
            "state_name": ["Delhi", "Delhi", "Delhi"],
            "energy_requirement_mu": [2980, 3010, 999999],
        }
    )
    config = {**RULE_CONFIG["outlier"], "group_by": "state_name"}
    issues = outlier_rule(df, columns=["energy_requirement_mu"], config=config)
    assert len(issues) == 1
    assert issues[0].row_reference == 2


def test_outlier_does_not_flag_naturally_large_entity():
    """An entity that's just consistently bigger than others (e.g. Uttar
    Pradesh) shouldn't be flagged — outliers are relative to that entity's
    OWN history, not to other entities."""
    df = pd.DataFrame(
        {
            "state_name": ["UP", "UP", "UP", "Goa", "Goa", "Goa"],
            "energy_requirement_mu": [16540, 16610, 16680, 412, 420, 428],
        }
    )
    config = {**RULE_CONFIG["outlier"], "group_by": "state_name"}
    issues = outlier_rule(df, columns=["energy_requirement_mu"], config=config)
    assert issues == []


def test_outlier_skips_group_below_min_size():
    df = pd.DataFrame(
        {"state_name": ["Goa", "Goa"], "energy_requirement_mu": [412, 999999]}
    )
    config = {**RULE_CONFIG["outlier"], "group_by": "state_name"}
    issues = outlier_rule(df, columns=["energy_requirement_mu"], config=config)
    assert issues == []  # only 2 data points, below min_group_size of 3


def test_outlier_works_ungrouped_on_generic_dataset():
    """With no group_by (the default for a dataset with no known entity
    column), outliers are still caught relative to the whole column."""
    df = pd.DataFrame({"price": [10, 11, 9, 10, 12, 5000]})
    issues = outlier_rule(df, columns=["price"])
    assert len(issues) == 1
    assert issues[0].row_reference == 5


# --- consistency_rule (generic: self-referential near-duplicate detection) ---


def test_consistency_flags_rare_naming_variant():
    df = pd.DataFrame(
        {"state_name": ["Odisha", "Odisha", "Odisha", "Odisha", "Orissa"]}
    )
    issues = consistency_rule(df)
    assert len(issues) == 1
    assert issues[0].row_reference == 4


def test_consistency_no_flag_for_exact_match():
    df = pd.DataFrame({"state_name": ["Odisha", "Odisha", "Bihar", "Bihar"]})
    assert consistency_rule(df) == []


def test_consistency_skips_high_cardinality_free_text_column():
    """A column where almost every value is unique (e.g. free-text notes or
    an ID) isn't categorical — fuzzy-matching it would just produce noise."""
    df = pd.DataFrame({"notes": [f"note {i}" for i in range(20)]})
    assert consistency_rule(df) == []


# --- schema_drift_rule -------------------------------------------------


def test_schema_drift_flags_missing_column():
    baseline = {"columns": {"state_name": {"dtype": "object"}, "extra_col": {"dtype": "object"}}}
    df = pd.DataFrame({"state_name": ["Bihar"]})
    issues = schema_drift_rule(df, baseline_profile=baseline)
    assert len(issues) == 1
    assert issues[0].column == "extra_col"


def test_schema_drift_flags_new_column():
    baseline = {"columns": {"state_name": {"dtype": "object"}}}
    df = pd.DataFrame({"state_name": ["Bihar"], "new_col": [1]})
    issues = schema_drift_rule(df, baseline_profile=baseline)
    assert len(issues) == 1
    assert issues[0].column == "new_col"


def test_schema_drift_no_baseline_is_noop():
    df = pd.DataFrame({"state_name": ["Bihar"]})
    assert schema_drift_rule(df, baseline_profile=None) == []
