"""Validator tests — one per validator per acceptance §9.3."""

from __future__ import annotations

import pytest
from pyspark.sql.types import StringType, StructField, StructType

from wide_to_long.api import unpivot_validated
from wide_to_long.errors import (
    AmbiguousDateFormatError,
    InterleavedColumnError,
    MixedDateFormatsError,
    NoDateColumnsFoundError,
    WideToLongError,
)


def _make_df(spark, columns: list[str]):
    """Build an empty DataFrame with the given string-column names."""
    schema = StructType([StructField(c, StringType(), True) for c in columns])
    return spark.createDataFrame([], schema)


# --- Acceptance §9.3, table row #1 -----------------------------------------
def test_validator_1_empty_schema(spark):
    df = _make_df(spark, [])
    with pytest.raises(WideToLongError):
        unpivot_validated(df)


# --- Acceptance §9.3, table row #2 -----------------------------------------
def test_validator_2_no_date_columns(spark):
    df = _make_df(spark, ["id", "name", "category"])
    with pytest.raises(NoDateColumnsFoundError):
        unpivot_validated(df)


# --- Acceptance §9.3, table row #3 -----------------------------------------
def test_validator_3_mixed_date_formats(spark):
    # "2025-01-31" (iso_day) and "2025-Q2" (iso_quarter) cannot share a tail.
    # The locked format will be iso_quarter (tail span=1); 2025-01-31 sits in
    # the ID block and matches a foreign date format -> MixedDateFormatsError.
    df = _make_df(spark, ["id", "2025-01-31", "2025-Q2"])
    with pytest.raises(MixedDateFormatsError):
        unpivot_validated(df)


# --- Acceptance §9.3, table row #4 -----------------------------------------
def test_validator_4_interleaved_column(spark):
    # "extra" splits the tail; the leftmost "2025-01-31" gets pushed into
    # the ID block but still matches the locked format -> InterleavedColumnError.
    df = _make_df(spark, ["id", "2025-01-31", "extra", "2025-02-28"])
    with pytest.raises(InterleavedColumnError):
        unpivot_validated(df)


# --- Acceptance §9.3, table row #5 -----------------------------------------
# The current 5-entry registry is constructively unambiguous (iso_day,
# iso_month, iso_quarter, iso_week, iso_year have mutually exclusive
# regexes — no single header matches more than one). The required test
# therefore exists as an xfail(strict=True) guard against future drift,
# per design §9.3.
@pytest.mark.xfail(
    strict=True,
    reason="registry is unambiguous; test guards against future drift",
)
def test_validator_5_ambiguous_format(spark):
    # If the registry ever gains a sixth format that overlaps with an
    # existing one, this test should start raising AmbiguousDateFormatError
    # for some header set. Until then, no input can trigger it.
    df = _make_df(spark, ["id", "2025-01-31"])
    with pytest.raises(AmbiguousDateFormatError):
        unpivot_validated(df)


# --- Positive sanity check -------------------------------------------------
def test_validate_happy_path_returns_detection(spark):
    df = _make_df(spark, ["region", "2025-01-31", "2025-02-28"])
    # Should not raise.
    out = unpivot_validated(df)
    assert out.columns == ["region", "period_date", "value"]
