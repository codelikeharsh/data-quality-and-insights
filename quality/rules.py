"""
The quality & governance rule engine.

Every rule here is domain-agnostic: none of them require a specific column
name or an external reference list. Each is a pure function: DataFrame
(+ config/context) in, list[Issue] out. They are independently testable
(see tests/test_quality_rules.py) and independently toggleable via
config.RULE_CONFIG, and none of them mutate the input DataFrame — that
keeps them composable and safe to run in any order, which is exactly what
run_all_rules() does.
"""
import numpy as np
import pandas as pd
from rapidfuzz import process, fuzz

from config import RULE_CONFIG
from quality.issue import Issue


def completeness_rule(df: pd.DataFrame, config: dict | None = None) -> list[Issue]:
    """Flag any column whose null rate exceeds a configurable threshold —
    the generic version of "is everything that should be here, here?" that
    works on any dataset without needing to know what a "complete" row
    looks like for this particular domain."""
    config = config or RULE_CONFIG["completeness"]
    if not config.get("enabled", True):
        return []

    threshold = config.get("null_pct_threshold", 20.0)
    n = len(df)
    issues: list[Issue] = []
    if n == 0:
        return issues

    for col in df.columns:
        null_count = int(df[col].isna().sum())
        null_pct = (null_count / n) * 100
        if null_pct > threshold:
            issues.append(
                Issue(
                    row_reference="column",
                    column=col,
                    issue_type="completeness",
                    description=(
                        f"Column '{col}' is {null_pct:.1f}% empty "
                        f"({null_count}/{n} rows) — above the {threshold}% threshold"
                    ),
                    severity="high" if null_pct > 50 else "medium",
                )
            )
    return issues


def group_completeness_rule(
    df: pd.DataFrame,
    entity_column: str | None,
    period_column: str | None,
    config: dict | None = None,
) -> list[Issue]:
    """Optional, auto-triggered completeness check: if the dataset looks
    like it has a repeating entity (e.g. a state, a store) reported across
    a repeating period (e.g. a month), flag an entity that reports in SOME
    periods but is silently absent from another — the "Bihar didn't submit
    this month" case that a null-rate check can't see, since a missing row
    has no null value to notice.

    No-ops when either column is missing/unresolved (run_pipeline only
    passes real column names when ingest.structured.guess_entity_column /
    guess_period_column found a plausible candidate), so this never assumes
    a dataset has this shape.
    """
    config = config or RULE_CONFIG["completeness"]
    if not config.get("enabled", True):
        return []
    if not entity_column or not period_column:
        return []
    if entity_column not in df.columns or period_column not in df.columns:
        return []

    all_entities = set(df[entity_column].dropna().unique())
    if len(all_entities) < 2:
        return []

    issues: list[Issue] = []
    for period, group in df.groupby(period_column):
        reported = set(group[entity_column].dropna().unique())
        missing = all_entities - reported
        for entity in sorted(missing, key=str):
            issues.append(
                Issue(
                    row_reference=f"{period_column}={period}",
                    column=entity_column,
                    issue_type="completeness",
                    description=(
                        f"'{entity}' is missing from {period_column}={period} "
                        f"despite reporting in other periods"
                    ),
                    severity="high",
                )
            )
    return issues


def duplicate_rule(df: pd.DataFrame, config: dict | None = None) -> list[Issue]:
    """Flag exact duplicate rows — the same record ingested twice, which
    silently double-counts in any downstream aggregation."""
    config = config or RULE_CONFIG["duplicate"]
    if not config.get("enabled", True):
        return []

    issues: list[Issue] = []
    dup_mask = df.duplicated(keep="first")
    for idx in df[dup_mask].index:
        issues.append(
            Issue(
                row_reference=idx,
                column="*",
                issue_type="duplicate",
                description=f"Row {idx} is an exact duplicate of an earlier row in this batch",
                severity="medium",
            )
        )
    return issues


def validity_rule(
    df: pd.DataFrame,
    columns: list[str] | None = None,
    config: dict | None = None,
) -> list[Issue]:
    """Flag values that are very likely data-entry/unit errors rather than
    real measurements. Generic heuristic: for each numeric column, if the
    great majority of its values are non-negative, treat the rare negative
    ones as suspicious (a column that's routinely negative — e.g. a
    profit/loss figure — is left alone, since being negative is normal for
    it)."""
    config = config or RULE_CONFIG["validity"]
    if not config.get("enabled", True):
        return []

    ratio_threshold = config.get("nonnegative_ratio_threshold", 0.95)
    min_sample_size = config.get("min_sample_size_for_ratio", 5)
    columns = columns if columns is not None else list(df.select_dtypes(include="number").columns)
    issues: list[Issue] = []

    for col in columns:
        if col not in df.columns:
            continue
        series = df[col].dropna()
        if series.empty:
            continue

        # Too few values to reliably tell "routinely negative" from "one bad
        # reading" — err on the side of flagging rather than silently
        # missing it (the opposite mistake, made confidently on 100+ rows,
        # is worse: staying silent on a genuinely-negative-by-nature column).
        nonneg_ratio = (series >= 0).mean()
        if len(series) >= min_sample_size and nonneg_ratio < ratio_threshold:
            continue  # this column is routinely negative — not an error pattern

        invalid_mask = df[col].notna() & (df[col] < 0)
        for idx, value in df.loc[invalid_mask, col].items():
            issues.append(
                Issue(
                    row_reference=idx,
                    column=col,
                    issue_type="validity",
                    description=(
                        f"Value {value} in '{col}' is negative, but "
                        f"{nonneg_ratio:.0%} of this column's other values are "
                        f"non-negative — likely a data-entry or unit error"
                    ),
                    severity="high",
                )
            )
    return issues


def _iqr_outliers(series: pd.Series, multiplier: float) -> pd.Series:
    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    iqr = q3 - q1
    lower, upper = q1 - multiplier * iqr, q3 + multiplier * iqr
    return (series < lower) | (series > upper)


def _modified_zscore_outliers(series: pd.Series, threshold: float) -> pd.Series:
    """Median/MAD-based ("modified") z-score. Unlike a mean/std z-score,
    this stays robust when the group is small and the outlier itself would
    otherwise blow out the mean and std it's being measured against — which
    is exactly the case for e.g. 3 readings of one entity where one of the
    3 is the outlier."""
    median = series.median()
    mad = (series - median).abs().median()
    if mad == 0:
        # No spread to compare against (all values identical, or only one
        # differs by a trivial amount) — nothing to confidently flag.
        return pd.Series(False, index=series.index)
    modified_z = 0.6745 * (series - median) / mad
    return modified_z.abs() > threshold


def outlier_rule(
    df: pd.DataFrame,
    columns: list[str] | None = None,
    config: dict | None = None,
) -> list[Issue]:
    """Flag statistical outliers in each numeric column. If `group_by` names
    a column (either via config or the `group_by` param), each group's
    values are compared against that GROUP's own history rather than the
    whole column — otherwise a naturally large entity (e.g. a big state, a
    flagship store) would get flagged every time just for being bigger than
    a small one. With no group_by, outliers are judged against the whole
    column, which is still meaningful for a dataset with no natural entity
    column. Catches e.g. a decimal/unit error where one value is ~100x its
    neighbors.
    """
    config = config or RULE_CONFIG["outlier"]
    if not config.get("enabled", True):
        return []

    columns = columns if columns is not None else list(df.select_dtypes(include="number").columns)
    method = config.get("method", "zscore")
    group_by = config.get("group_by")
    min_group_size = config.get("min_group_size", 3)
    issues: list[Issue] = []

    groups = df.groupby(group_by) if group_by and group_by in df.columns else [(None, df)]

    for group_key, group_df in groups:
        for col in columns:
            if col not in group_df.columns:
                continue
            series = group_df[col].dropna()
            if len(series) < min_group_size:
                # Too little history for this entity/column to judge what's normal.
                continue

            if method == "iqr":
                mask = _iqr_outliers(series, config.get("iqr_multiplier", 1.5))
            else:
                mask = _modified_zscore_outliers(series, config.get("zscore_threshold", 3.5))

            for idx in series[mask].index:
                value = df.at[idx, col]
                scope = f"'{group_key}'" if group_key is not None else "the batch"
                issues.append(
                    Issue(
                        row_reference=idx,
                        column=col,
                        issue_type="outlier",
                        description=(
                            f"Value {value} in {col} is a statistical outlier "
                            f"({method}) relative to {scope}'s own history — "
                            f"possible decimal/unit error"
                        ),
                        severity="medium",
                    )
                )
    return issues


def consistency_rule(
    df: pd.DataFrame,
    columns: list[str] | None = None,
    config: dict | None = None,
) -> list[Issue]:
    """Entity resolution without an external reference list: for each
    categorical (low-cardinality text) column, cluster its own observed
    values by fuzzy similarity and flag a rare variant that closely matches
    a much more common one (e.g. "Odisha" appearing 40 times and "Orissa"
    appearing twice in the same column). This catches naming drift that
    would otherwise silently fragment a groupby/join, without needing to
    know in advance what the "correct" spellings are.
    """
    config = config or RULE_CONFIG["consistency"]
    if not config.get("enabled", True):
        return []

    threshold = config.get("fuzzy_match_threshold", 85)
    max_unique_ratio = config.get("max_unique_ratio", 0.5)
    min_value_count = config.get("min_value_count", 2)
    min_sample_size = config.get("min_sample_size_for_ratio_filter", 10)
    issues: list[Issue] = []

    candidate_columns = columns if columns is not None else list(df.select_dtypes(include="object").columns)

    for column in candidate_columns:
        if column not in df.columns:
            continue

        non_null = df[column].dropna().astype(str)
        if non_null.empty:
            continue

        n = len(df)
        # Below min_sample_size, a high unique-ratio isn't a reliable signal
        # of "this is free text" (e.g. 2 unique values in 3 rows) — the
        # min_value_count check just below already keeps a genuinely
        # unique-heavy small batch from producing false positives.
        if n >= min_sample_size and non_null.nunique() / n > max_unique_ratio:
            continue  # looks like free text / an ID column, not categorical

        counts = non_null.value_counts()
        common_values = counts[counts >= min_value_count].index.tolist()
        if not common_values:
            continue  # nothing frequent enough to compare rare values against

        rare_values = counts[counts < min_value_count].index.tolist()
        for rare in rare_values:
            candidates = [v for v in common_values if v != rare]
            if not candidates:
                continue
            best = process.extractOne(rare, candidates, scorer=fuzz.WRatio)
            if best is None:
                continue
            match, score, _ = best
            if score >= threshold:
                for idx in df.index[non_null == rare]:
                    issues.append(
                        Issue(
                            row_reference=idx,
                            column=column,
                            issue_type="consistency",
                            description=(
                                f"'{rare}' in column '{column}' closely matches the far "
                                f"more common value '{match}' ({score:.0f}% similarity) — "
                                f"likely a naming inconsistency that will break "
                                f"joins/counts"
                            ),
                            severity="medium",
                        )
                    )
    return issues


def schema_drift_rule(
    df: pd.DataFrame,
    baseline_profile: dict | None,
    config: dict | None = None,
) -> list[Issue]:
    """Compare this run's columns/dtypes against a saved baseline profile
    (from profiling.profiler, see profiling/profiler.py) and flag any
    new, missing, or retyped column. With no baseline (first-ever run),
    nothing to compare against, so this is a no-op."""
    config = config or RULE_CONFIG["schema_drift"]
    if not config.get("enabled", True) or not baseline_profile:
        return []

    baseline_columns = baseline_profile.get("columns", {})
    current_columns = {col: str(df[col].dtype) for col in df.columns}
    issues: list[Issue] = []

    for col, meta in baseline_columns.items():
        if col not in current_columns:
            issues.append(
                Issue(
                    row_reference="schema",
                    column=col,
                    issue_type="schema_drift",
                    description=f"Column '{col}' present in the previous run is missing from this run",
                    severity="high",
                )
            )
        elif current_columns[col] != meta.get("dtype"):
            issues.append(
                Issue(
                    row_reference="schema",
                    column=col,
                    issue_type="schema_drift",
                    description=(
                        f"Column '{col}' changed type from {meta.get('dtype')} "
                        f"to {current_columns[col]}"
                    ),
                    severity="medium",
                )
            )

    for col in current_columns:
        if col not in baseline_columns:
            issues.append(
                Issue(
                    row_reference="schema",
                    column=col,
                    issue_type="schema_drift",
                    description=f"New column '{col}' not present in the previous run's schema",
                    severity="low",
                )
            )

    return issues


def run_all_rules(
    df: pd.DataFrame,
    group_by: str | None = None,
    period_by: str | None = None,
    baseline_profile: dict | None = None,
) -> list[Issue]:
    """Run every enabled rule and return the combined, flat issue list.

    `group_by`, if given, names the column outlier_rule (and
    group_completeness_rule) should compare each entity's own history
    against. `period_by` names a reporting-period column. Both are optional
    and, when the caller is run_pipeline, auto-detected (see
    ingest.structured.guess_entity_column / guess_period_column) rather than
    hardcoded — a dataset with neither shape just skips the rules that need
    them.
    """
    outlier_config = dict(RULE_CONFIG["outlier"])
    if group_by:
        outlier_config["group_by"] = group_by

    issues: list[Issue] = []
    issues += completeness_rule(df)
    issues += group_completeness_rule(df, entity_column=group_by, period_column=period_by)
    issues += duplicate_rule(df)
    issues += validity_rule(df)
    issues += outlier_rule(df, config=outlier_config)
    issues += consistency_rule(df)
    issues += schema_drift_rule(df, baseline_profile=baseline_profile)
    return issues
