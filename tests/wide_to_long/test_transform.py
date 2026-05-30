"""Transform tests — period-end correctness per format (design §4)."""

from __future__ import annotations

import datetime as dt

from pyspark.sql.types import (
    DateType,
    DoubleType,
    StringType,
    StructField,
    StructType,
)

from wide_to_long.api import unpivot, unpivot_validated


def _wide(spark, columns: list[str], rows: list[tuple]):
    schema = StructType([StructField(c, StringType(), True) for c in columns])
    return spark.createDataFrame(rows, schema)


def _collect_period_values(spark, columns: list[str], rows: list[tuple]):
    df = _wide(spark, columns, rows)
    long_df = unpivot(df)
    return {r["period_date"]: r["value"] for r in long_df.collect()}


def test_output_shape_and_types(spark):
    df = _wide(spark, ["region", "2025-01-31", "2025-02-28"], [("A", "1.5", "2.5")])
    out = unpivot(df)
    assert out.columns == ["region", "period_date", "value"]
    schema = {f.name: f.dataType for f in out.schema.fields}
    assert isinstance(schema["region"], StringType)
    assert isinstance(schema["period_date"], DateType)
    assert isinstance(schema["value"], DoubleType)
    rows = sorted(out.collect(), key=lambda r: r["period_date"])
    assert rows[0]["region"] == "A"
    assert rows[0]["value"] == 1.5


def test_iso_day_period_end_verbatim(spark):
    got = _collect_period_values(
        spark, ["r", "2025-05-31"], [("A", "10.0")]
    )
    assert got == {dt.date(2025, 5, 31): 10.0}


def test_iso_month_period_end_last_day(spark):
    got = _collect_period_values(
        spark, ["r", "2025-01", "2025-02"], [("A", "1.0", "2.0")]
    )
    # Jan 31 and Feb 28 (2025 is not a leap year).
    assert got == {dt.date(2025, 1, 31): 1.0, dt.date(2025, 2, 28): 2.0}


def test_iso_quarter_period_end_last_day(spark):
    got = _collect_period_values(
        spark,
        ["r", "2025-Q1", "2025-Q2", "2025-Q3", "2025-Q4"],
        [("A", "1.0", "2.0", "3.0", "4.0")],
    )
    assert got == {
        dt.date(2025, 3, 31): 1.0,
        dt.date(2025, 6, 30): 2.0,
        dt.date(2025, 9, 30): 3.0,
        dt.date(2025, 12, 31): 4.0,
    }


def test_iso_week_period_end_sunday(spark):
    # Per design §12, iso_week parsing is "Projected"; verify W22 -> 2025-06-01.
    got = _collect_period_values(
        spark, ["r", "2025-W22"], [("A", "7.0")]
    )
    assert got == {dt.date(2025, 6, 1): 7.0}


def test_iso_year_period_end_december_31(spark):
    got = _collect_period_values(
        spark, ["r", "2024", "2025"], [("A", "1.0", "2.0")]
    )
    assert got == {dt.date(2024, 12, 31): 1.0, dt.date(2025, 12, 31): 2.0}


def test_all_date_columns_no_id_columns(spark):
    df = _wide(spark, ["2025-01-31", "2025-02-28"], [("1.0", "2.0")])
    out = unpivot(df)
    assert out.columns == ["period_date", "value"]
    rows = sorted(out.collect(), key=lambda r: r["period_date"])
    assert rows[0]["value"] == 1.0


def test_non_numeric_value_becomes_null(spark):
    # Design §11: cast("double") produces null for non-numeric strings; caller's concern.
    df = _wide(spark, ["r", "2025-01-31"], [("A", "not-a-number")])
    out = unpivot(df)
    row = out.collect()[0]
    assert row["value"] is None


def test_custom_column_names(spark):
    df = _wide(spark, ["r", "2025-01-31"], [("A", "1.0")])
    out = unpivot(df, period_col="dt", value_col="amount")
    assert out.columns == ["r", "dt", "amount"]


def test_unpivot_validated_matches_unpivot_on_clean_input(spark):
    cols = ["r", "2025-01-31", "2025-02-28"]
    rows = [("A", "1.0", "2.0")]
    a = unpivot(_wide(spark, cols, rows)).collect()
    b = unpivot_validated(_wide(spark, cols, rows)).collect()
    assert sorted(a, key=lambda r: r["period_date"]) == sorted(
        b, key=lambda r: r["period_date"]
    )
