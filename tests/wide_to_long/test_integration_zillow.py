"""End-to-end integration test against a committed Zillow sample (acceptance §9.2)."""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

import pytest
from pyspark.sql.types import DateType, DoubleType

from wide_to_long.api import read_and_unpivot

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CSV = REPO_ROOT / "data" / "samples" / "zillow" / "zhvi_home_values_metro_monthly.csv"


@pytest.fixture(scope="module")
def sample_header_and_row_count() -> tuple[list[str], int]:
    with SAMPLE_CSV.open(newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        data_rows = sum(1 for _ in reader)
    return header, data_rows


def test_zillow_sample_exists():
    assert SAMPLE_CSV.exists(), f"missing committed sample: {SAMPLE_CSV}"


def test_zillow_end_to_end(spark, sample_header_and_row_count):
    header, data_row_count = sample_header_and_row_count
    date_cols = [c for c in header if c.startswith("20")]
    id_cols = [c for c in header if c not in date_cols]
    assert len(date_cols) == 12, "sample is windowed to 12 months per README"

    long_df = read_and_unpivot(spark, str(SAMPLE_CSV))

    # Output column count: id cols + period_date + value.
    assert long_df.columns == id_cols + ["period_date", "value"]
    assert len(long_df.columns) == len(header) - 12 + 2

    # Output row count = data_rows * date_cols.
    assert long_df.count() == data_row_count * 12

    # Schema types.
    schema = {f.name: f.dataType for f in long_df.schema.fields}
    assert isinstance(schema["period_date"], DateType)
    assert isinstance(schema["value"], DoubleType)

    # Period-date range matches the windowed sample (2025-05-31 -> 2026-04-30).
    distinct_periods = sorted({r["period_date"] for r in long_df.select("period_date").distinct().collect()})
    assert distinct_periods[0] == dt.date(2025, 5, 31)
    assert distinct_periods[-1] == dt.date(2026, 4, 30)
    assert len(distinct_periods) == 12
