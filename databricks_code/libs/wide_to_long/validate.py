"""Structural validators run by unpivot_validated (design §3.2)."""

from __future__ import annotations

from wide_to_long.detect import Detection, detect_format
from wide_to_long.errors import (
    InterleavedColumnError,
    MixedDateFormatsError,
    WideToLongError,
)
from wide_to_long.formats import REGISTRY


def validate_all(columns: list[str]) -> Detection:
    """Run all five validators in order and return the detection result.

    Order matches design §3.2 (fail-fast):
        1. At least one column exists.
        2. At least one tail column parses as a date.
        3. All date columns share one format (no mixing within the tail).
        4. Contiguous-tail rule: no non-date column to the right of a
           date column.
        5. Format unambiguity (raised by detect_format).
    """
    # 1. At least one column exists.
    if not columns:
        raise WideToLongError(
            "Input DataFrame has zero columns.",
            input_columns=columns,
            detected="empty schema",
        )

    # 2 & 5. Detection runs; raises NoDateColumnsFoundError or
    #        AmbiguousDateFormatError as appropriate.
    detection = detect_format(columns)

    # 3. All date columns share one format. The detector already locks
    #    a single format, but a date column from a *different* format
    #    embedded inside the tail can only be caught explicitly: walk
    #    the locked tail and assert every header matches the locked
    #    format. (If a foreign-format date appears, it would split the
    #    contiguous tail and not be included; we surface that as a
    #    MixedDateFormatsError because the user clearly intended dates,
    #    not as InterleavedColumnError.)
    fmt = detection.fmt
    foreign_in_ids = [
        column
        for column in detection.id_columns
        if any(other.matches(column) for other in REGISTRY if other.name != fmt.name)
    ]
    if foreign_in_ids:
        raise MixedDateFormatsError(
            "Tail locked one format but other columns match a different date format.",
            input_columns=columns,
            detected=f"locked format: {fmt.name}",
            offending=foreign_in_ids,
        )

    # 4. Contiguous-tail rule. Any ID-side column whose header matches
    #    the locked format itself proves the tail isn't truly contiguous
    #    — there's a non-date column to its right that pushed it out
    #    of the tail span.
    same_format_in_ids = [column for column in detection.id_columns if fmt.matches(column)]
    if same_format_in_ids:
        raise InterleavedColumnError(
            "Non-date column appears to the right of a date column.",
            input_columns=columns,
            detected=f"locked format: {fmt.name}",
            offending=same_format_in_ids,
        )

    return detection
