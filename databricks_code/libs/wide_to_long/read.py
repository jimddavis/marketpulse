"""CSV read for read_and_unpivot (design §6.2 — Approach B)."""

from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession


def read_csv_all_string(spark: SparkSession, path: str) -> DataFrame:
    """Read a single CSV file with header=True, inferSchema=False.

    With inferSchema=False, Spark assigns StringType to every column —
    exactly what the design requires (§6.2).
    """
    return (
        spark.read
        .option("header", True)
        .option("inferSchema", False)
        .csv(path)
    )
