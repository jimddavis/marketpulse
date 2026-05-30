"""Closed registry of date-column header formats (design §5).

Each entry knows:
    * its name (locked format identifier),
    * its priority (lower wins ties; 1 is highest),
    * a compiled regex matching valid headers,
    * a Spark expression producing the period-end DateType value from
      the raw header string column.

The registry is intentionally closed: adding a sixth format is a future PR,
not a runtime extension point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from pyspark.sql import Column
from pyspark.sql import functions as F


@dataclass(frozen=True)
class DateFormat:
    name: str
    priority: int
    regex: re.Pattern[str]
    period_end: Callable[[Column], Column]

    def matches(self, header: str) -> bool:
        return bool(self.regex.fullmatch(header))


def _iso_day_period_end(col: Column) -> Column:
    return F.to_date(col, "yyyy-MM-dd")


def _iso_month_period_end(col: Column) -> Column:
    first_of_month = F.to_date(F.concat(col, F.lit("-01")), "yyyy-MM-dd")
    return F.last_day(first_of_month)


def _iso_quarter_period_end(col: Column) -> Column:
    year = F.substring(col, 1, 4)
    quarter_digit = F.substring(col, 7, 1).cast("int")
    first_month_num = (quarter_digit - F.lit(1)) * F.lit(3) + F.lit(1)
    first_month_str = F.lpad(first_month_num.cast("string"), 2, "0")
    first_of_quarter = F.to_date(
        F.concat_ws("-", year, first_month_str, F.lit("01")), "yyyy-MM-dd"
    )
    return F.last_day(F.add_months(first_of_quarter, 2))


def _iso_week_period_end(col: Column) -> Column:
    # Spark 3+ refuses the YYYY-'W'ww pattern under strict timeParserPolicy
    # (SparkUpgradeException). Compute the ISO Sunday by arithmetic instead.
    #
    # Invariant: Jan 4 of any year is always in ISO week 1.
    #   1. Parse Jan 4 of the header's year.
    #   2. Translate Spark dayofweek (1=Sun..7=Sat) -> ISO dow (1=Mon..7=Sun).
    #   3. Step back to the Monday of week 1.
    #   4. Add (week - 1) * 7 days to reach the target Monday.
    #   5. Add 6 days for the Sunday (period-end per design §4).
    year_str = F.substring(col, 1, 4)
    week_int = F.substring(col, 7, 2).cast("int")
    jan4 = F.to_date(F.concat(year_str, F.lit("-01-04")), "yyyy-MM-dd")
    iso_dow = F.pmod(F.dayofweek(jan4) + F.lit(5), F.lit(7)) + F.lit(1)  # 1=Mon..7=Sun
    monday_week_1 = F.date_sub(jan4, (iso_dow - F.lit(1)).cast("int"))
    monday_target = F.date_add(monday_week_1, ((week_int - F.lit(1)) * F.lit(7)).cast("int"))
    return F.date_add(monday_target, 6)


def _iso_year_period_end(col: Column) -> Column:
    return F.to_date(F.concat(col, F.lit("-12-31")), "yyyy-MM-dd")


REGISTRY: tuple[DateFormat, ...] = (
    DateFormat(
        name="iso_day",
        priority=1,
        regex=re.compile(r"^\d{4}-\d{2}-\d{2}$"),
        period_end=_iso_day_period_end,
    ),
    DateFormat(
        name="iso_month",
        priority=2,
        regex=re.compile(r"^\d{4}-\d{2}$"),
        period_end=_iso_month_period_end,
    ),
    DateFormat(
        name="iso_quarter",
        priority=3,
        regex=re.compile(r"^\d{4}-Q[1-4]$"),
        period_end=_iso_quarter_period_end,
    ),
    DateFormat(
        name="iso_week",
        priority=4,
        regex=re.compile(r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$"),
        period_end=_iso_week_period_end,
    ),
    DateFormat(
        name="iso_year",
        priority=5,
        regex=re.compile(r"^\d{4}$"),
        period_end=_iso_year_period_end,
    ),
)


def get_format(name: str) -> DateFormat:
    for fmt in REGISTRY:
        if fmt.name == name:
            return fmt
    raise KeyError(f"Unknown date format: {name}")
