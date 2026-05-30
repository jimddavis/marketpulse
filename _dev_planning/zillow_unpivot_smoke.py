# /// script
# requires-python = ">=3.12"
# dependencies = ["pyspark>=3.5,<4"]
# ///
"""Smoke test: run wide_to_long against a FULL (non-windowed) Zillow file.

Proves the module runs end-to-end from THIS project on the real 321-column file
(5 id cols + 316 monthly date cols) — not just the 12-month committed sample the
pytest integration test uses. Read-only on the source; writes the converted long
output to a throwaway dir for eyeballing.

Pinned pyspark<4 so it runs on the local Java 8 JVM (Spark 4 needs Java 17).

Run:  uv run _dev_planning/zillow_unpivot_smoke.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Mirror tests/conftest.py + notebook_init: put databricks_code/libs on sys.path
# so `import wide_to_long` resolves without installing the package.
sys.path.insert(0, str(REPO / "databricks_code" / "libs"))

from pyspark.sql import SparkSession  # noqa: E402
from wide_to_long.api import read_and_unpivot  # noqa: E402

SRC = REPO / "_local_downloads" / "zillow" / "zhvi_home_values_metro_monthly.csv"
OUT = REPO / "_local_downloads" / "zillow" / "_converted_long"  # throwaway artifact


def main() -> None:
    spark = (
        SparkSession.builder
        .master("local[2]")
        .appName("zillow-unpivot-smoke")
        .config("spark.sql.shuffle.partitions", "2")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")

    wide = (
        spark.read.option("header", True).option("inferSchema", False).csv(str(SRC))
    )
    n_cols = len(wide.columns)
    n_rows = wide.count()
    n_date_cols = n_cols - 5
    print(f"\nINPUT  {SRC.name}: {n_rows:,} data rows x {n_cols} columns")
    print(f"       id cols   (first 5): {wide.columns[:5]}")
    print(f"       date cols (last 3) : {wide.columns[-3:]}")

    # Defaults: period_col='period_date', value_col='value'. Validated path.
    long_df = read_and_unpivot(spark, str(SRC))
    print("\nOUTPUT schema:")
    long_df.printSchema()

    out_rows = long_df.count()
    expected = n_rows * n_date_cols
    print(f"OUTPUT rows: {out_rows:,}  (expected {n_rows:,} x {n_date_cols} = {expected:,})")
    assert out_rows == expected, f"ROW COUNT MISMATCH: {out_rows} != {expected}"

    first_region = wide.select("RegionID").first()["RegionID"]
    print(f"\nSample — RegionID={first_region}, latest 3 periods:")
    (
        long_df
        .filter(long_df.RegionID == first_region)
        .orderBy(long_df.period_date.desc())
        .show(3, truncate=False)
    )

    long_df.coalesce(1).write.mode("overwrite").option("header", True).csv(str(OUT))
    print(f"\nConverted long CSV written under: {OUT}")
    print("(throwaway — safe to delete; `rm -rf` it when done.)")
    spark.stop()


if __name__ == "__main__":
    main()
