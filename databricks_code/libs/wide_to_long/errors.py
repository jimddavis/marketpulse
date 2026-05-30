"""Exception classes raised by wide_to_long.

The base class is never raised directly. Each subclass corresponds to one
validator in the design (§3.2 / §7).
"""

from __future__ import annotations


def _format_message(
    summary: str,
    input_columns: list[str] | None = None,
    detected: str | None = None,
    offending: list[str] | None = None,
) -> str:
    parts = [summary]
    if input_columns is not None:
        parts.append(f"  Input columns: {list(input_columns)}")
    if detected is not None:
        parts.append(f"  Detected: {detected}")
    if offending is not None:
        parts.append(f"  Offending: {list(offending)}")
    return "\n".join(parts)


class WideToLongError(Exception):
    """Base class for all wide_to_long failures."""

    def __init__(
        self,
        summary: str,
        *,
        input_columns: list[str] | None = None,
        detected: str | None = None,
        offending: list[str] | None = None,
    ) -> None:
        message = _format_message(summary, input_columns, detected, offending)
        super().__init__(message)
        self.summary = summary
        self.input_columns = list(input_columns) if input_columns is not None else None
        self.detected = detected
        self.offending = list(offending) if offending is not None else None


class NoDateColumnsFoundError(WideToLongError):
    """Validator 2: no right-edge column parses against any date format."""


class MixedDateFormatsError(WideToLongError):
    """Validator 3: tail columns parse against more than one format."""


class InterleavedColumnError(WideToLongError):
    """Validator 4: a non-date column appears to the right of a date column."""


class AmbiguousDateFormatError(WideToLongError):
    """Validator 5: two distinct formats produce equal tail spans."""
