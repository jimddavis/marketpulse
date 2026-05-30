"""Public API surface — thin orchestration over detect/validate/transform/read."""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession

from wide_to_long.read import read_csv_all_string
from wide_to_long.transform import unpivot_with_format
from wide_to_long.detect import detect_format
from wide_to_long.validate import validate_all


def unpivot(
    df: DataFrame,
    *,
    period_col: str = "period_date",
    value_col: str = "value",
) -> DataFrame:
    """Pure wide-to-long transform. Trusts the contiguous-tail rule.

    Raises NoDateColumnsFoundError if no right-edge column parses against
    any registered date format.
    """
    detection = detect_format(df.columns)
    return unpivot_with_format(df, detection, period_col=period_col, value_col=value_col)


def unpivot_validated(
    df: DataFrame,
    *,
    period_col: str = "period_date",
    value_col: str = "value",
) -> DataFrame:
    """Validated wide-to-long transform.

    Runs the five structural validators before unpivoting (see design §3.2).
    """
    detection = validate_all(df.columns)
    return unpivot_with_format(df, detection, period_col=period_col, value_col=value_col)


def read_and_unpivot(
    spark: SparkSession,
    path: str,
    *,
    period_col: str = "period_date",
    value_col: str = "value",
) -> DataFrame:
    """Read a single CSV file as all-string, then unpivot with validation."""
    df = read_csv_all_string(spark, path)
    return unpivot_validated(df, period_col=period_col, value_col=value_col)
