"""Generic wide-to-long unpivot for PySpark DataFrames.

Public API:
    unpivot(df, *, period_col, value_col) -> DataFrame
    unpivot_validated(df, *, period_col, value_col) -> DataFrame
    read_and_unpivot(spark, path, *, period_col, value_col) -> DataFrame

Period dates emitted are always **end-of-period** for the locked format
(e.g. 2025-Q2 -> 2025-06-30, 2025-05 -> 2025-05-31). YYYY-MM-DD headers
are emitted verbatim.
"""

from wide_to_long.api import read_and_unpivot, unpivot, unpivot_validated

__all__ = ["unpivot", "unpivot_validated", "read_and_unpivot"]
