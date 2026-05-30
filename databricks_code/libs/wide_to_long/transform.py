"""Wide-to-long transform using DataFrame.unpivot (design §6.1)."""

from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from wide_to_long.detect import Detection


def unpivot_with_format(
    df: DataFrame,
    detection: Detection,
    *,
    period_col: str,
    value_col: str,
) -> DataFrame:
    """Unpivot the date tail into rows.

    Output schema: ID columns (unchanged) + period_col (DateType) +
    value_col (DoubleType), in that order.
    """
    id_cols = list(detection.id_columns)
    date_cols = list(detection.date_columns)
    raw_period_col = f"{period_col}__str"

    long_df = df.unpivot(
        ids=id_cols,
        values=date_cols,
        variableColumnName=raw_period_col,
        valueColumnName=value_col,
    )

    parsed_period = detection.fmt.period_end(F.col(raw_period_col))
    long_df = (
        long_df
        .withColumn(period_col, parsed_period)
        .drop(raw_period_col)
        .withColumn(value_col, F.col(value_col).cast("double"))
        .select(*id_cols, period_col, value_col)
    )
    return long_df
