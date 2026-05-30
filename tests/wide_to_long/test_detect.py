"""Detection algorithm tests (design §5)."""

from __future__ import annotations

import pytest

from wide_to_long.detect import detect_format
from wide_to_long.errors import AmbiguousDateFormatError, NoDateColumnsFoundError


def test_iso_day_recognised():
    det = detect_format(["region", "2025-01-31", "2025-02-28"])
    assert det.fmt.name == "iso_day"
    assert det.id_columns == ("region",)
    assert det.date_columns == ("2025-01-31", "2025-02-28")


def test_iso_month_recognised():
    det = detect_format(["region", "2025-01", "2025-02"])
    assert det.fmt.name == "iso_month"


def test_iso_quarter_recognised():
    det = detect_format(["region", "2025-Q1", "2025-Q2"])
    assert det.fmt.name == "iso_quarter"


def test_iso_week_recognised():
    det = detect_format(["region", "2025-W01", "2025-W22"])
    assert det.fmt.name == "iso_week"


def test_iso_year_recognised():
    det = detect_format(["region", "2023", "2024", "2025"])
    assert det.fmt.name == "iso_year"


def test_longest_tail_wins_over_lower_priority():
    # iso_year would match span=1 on "2025"; iso_quarter matches span=2.
    # Longest tail wins -> iso_quarter, splitting "2025" into IDs.
    det = detect_format(["region", "2025", "2025-Q3", "2025-Q4"])
    assert det.fmt.name == "iso_quarter"
    assert det.date_columns == ("2025-Q3", "2025-Q4")
    assert det.id_columns == ("region", "2025")


def test_no_date_columns_raises():
    with pytest.raises(NoDateColumnsFoundError):
        detect_format(["region", "name", "category"])


def test_all_date_columns_no_id_columns():
    det = detect_format(["2025-01-31", "2025-02-28"])
    assert det.id_columns == ()
    assert det.date_columns == ("2025-01-31", "2025-02-28")


def test_id_columns_passed_through_in_order():
    cols = ["a", "b", "c", "d", "e", "2025-01-31"]
    det = detect_format(cols)
    assert det.id_columns == ("a", "b", "c", "d", "e")
