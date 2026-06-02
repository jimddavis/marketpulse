"""Date-column detection algorithm (design §5).

Strategy: for each format in the registry, compute its tail span — the
number of contiguous right-edge headers that match. The chosen format is
the one with the longest tail span; ties are broken by priority (lower
wins).
"""

from __future__ import annotations

from dataclasses import dataclass

from wide_to_long.errors import AmbiguousDateFormatError, NoDateColumnsFoundError
from wide_to_long.formats import REGISTRY, DateFormat


@dataclass(frozen=True)
class Detection:
    """The result of running the detection algorithm against a header list."""

    fmt: DateFormat
    id_columns: tuple[str, ...]
    date_columns: tuple[str, ...]


def _tail_span(columns: list[str], fmt: DateFormat) -> int:
    span = 0
    for header in reversed(columns):
        if fmt.matches(header):
            span += 1
        else:
            break
    return span


def detect_format(columns: list[str]) -> Detection:
    """Detect the locked format and split columns into IDs vs date tail.

    Raises:
        NoDateColumnsFoundError: no format matched any tail column.
        AmbiguousDateFormatError: two distinct formats produced equal,
            nonzero, maximum tail spans.
    """
    spans: list[tuple[DateFormat, int]] = [
        (fmt, _tail_span(columns, fmt)) for fmt in REGISTRY
    ]
    nonzero = [(fmt, span) for fmt, span in spans if span > 0]

    if not nonzero:
        raise NoDateColumnsFoundError(
            "No right-edge column matched any registered date format.",
            input_columns=columns,
            detected="no format produced a tail span > 0",
        )

    max_span = max(span for _, span in nonzero)
    winners = [fmt for fmt, span in nonzero if span == max_span]

    if len(winners) > 1:
        raise AmbiguousDateFormatError(
            "Multiple date formats produced equal maximum tail spans.",
            input_columns=columns,
            detected=f"tail span {max_span} matched by: "
            + ", ".join(date_fmt.name for date_fmt in winners),
            offending=[date_fmt.name for date_fmt in winners],
        )

    chosen = winners[0]
    split = len(columns) - max_span
    return Detection(
        fmt=chosen,
        id_columns=tuple(columns[:split]),
        date_columns=tuple(columns[split:]),
    )
