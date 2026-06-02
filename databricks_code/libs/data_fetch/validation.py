"""Post-download validation + hashing (WS-F).

Pure functions over a completed scratch file, run by the runner BEFORE promote (design
§7.5, §7.6, §16.6). A failure raises ValidationError — a PERMANENT failure: the runner
logs STATUS_FAILED and aborts the run (abort-on-first); it is not retried. Hashing
supports the idempotent no-op (§7.6).

Header validation is PREFIX-match, CSV only: the first len(expected_header) columns of the
first line must equal expected_header. `xlsx`/`json` land as opaque bytes — not header-
validated. expected_header=None skips the check entirely.
"""

from __future__ import annotations

import csv
import hashlib
import os

_HASH_CHUNK = 1024 * 1024  # 1 MiB read chunks — never load the whole file into memory


class ValidationError(Exception):
    """A downloaded file failed a pre-promote check. Permanent (not retried)."""


def sha256_of(path: str) -> str:
    """Streamed sha256 hex digest of the file at `path` (design §7.6)."""
    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def validate_download(path: str, *, fmt: str, expected_header: tuple[str, ...] | None,
                      expected_size: int | None = None) -> None:
    """Run all pre-promote checks; raise ValidationError on the first failure (§7.5).

    - non-empty;
    - byte-count match vs `expected_size` (the server Content-Length) when provided;
    - CSV prefix-header match when fmt == 'csv' and `expected_header` is set.
    """
    size = os.path.getsize(path)                       # stat once; reused by both checks
    assert_non_empty(path, size=size)
    if expected_size is not None:
        assert_size_matches(path, expected_size, size=size)
    if fmt == "csv" and expected_header is not None:
        assert_csv_header_prefix(path, expected_header)


def assert_non_empty(path: str, *, size: int | None = None) -> None:
    if (size if size is not None else os.path.getsize(path)) == 0:
        raise ValidationError(f"downloaded file is empty: {path}")


def assert_size_matches(path: str, expected_size: int, *, size: int | None = None) -> None:
    actual = size if size is not None else os.path.getsize(path)
    if actual != expected_size:
        raise ValidationError(
            f"size mismatch (truncation?): expected {expected_size:,} bytes, "
            f"got {actual:,} at {path}"
        )


def assert_csv_header_prefix(path: str, expected_header: tuple[str, ...]) -> None:
    # utf-8-sig strips a leading BOM so the first column name compares cleanly.
    with open(path, "r", newline="", encoding="utf-8-sig") as fh:
        try:
            actual = next(csv.reader(fh))
        except StopIteration:
            raise ValidationError(f"CSV has no header row: {path}") from None
    prefix = tuple(actual[:len(expected_header)])
    if prefix != tuple(expected_header):
        raise ValidationError(
            f"CSV header prefix mismatch in {path}\n"
            f"  expected (prefix): {list(expected_header)}\n"
            f"  actual (first {len(expected_header)}): {list(prefix)}"
        )
