"""WS-F — validation + hashing unit tests. Pure filesystem, no network."""

from __future__ import annotations

import hashlib

import pytest

from data_fetch.validation import (
    ValidationError,
    assert_csv_header_prefix,
    assert_non_empty,
    assert_size_matches,
    sha256_of,
    validate_download,
)

_ZILLOW_HEADER = ("RegionID", "SizeRank", "RegionName", "RegionType", "StateName")


def _write(tmp_path, name, data: bytes):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


# -- sha256 ------------------------------------------------------------------

def test_sha256_matches_hashlib(tmp_path):
    data = b"some,csv\n1,2\n"
    path = _write(tmp_path, "f.csv", data)
    assert sha256_of(path) == hashlib.sha256(data).hexdigest()


# -- non-empty ---------------------------------------------------------------

def test_non_empty_passes_and_fails(tmp_path):
    assert_non_empty(_write(tmp_path, "ok.bin", b"x"))          # no raise
    with pytest.raises(ValidationError, match="empty"):
        assert_non_empty(_write(tmp_path, "empty.bin", b""))


# -- size match (truncation) -------------------------------------------------

def test_size_match_ok_and_mismatch(tmp_path):
    path = _write(tmp_path, "f.bin", b"12345")
    assert_size_matches(path, 5)                                # no raise
    with pytest.raises(ValidationError, match="truncation"):
        assert_size_matches(path, 999)


# -- CSV prefix header -------------------------------------------------------

def test_header_exact_match(tmp_path):
    path = _write(tmp_path, "f.csv", b"RegionID,SizeRank,RegionName,RegionType,StateName\n1,2,3,4,5\n")
    assert_csv_header_prefix(path, _ZILLOW_HEADER)              # no raise


def test_header_prefix_match_with_extra_date_columns(tmp_path):
    # Zillow wide CSV: 5 ID cols then a long date tail — prefix must still match.
    path = _write(tmp_path, "wide.csv",
                  b"RegionID,SizeRank,RegionName,RegionType,StateName,2000-01-31,2000-02-29\n1,2,3,4,5,6,7\n")
    assert_csv_header_prefix(path, _ZILLOW_HEADER)              # no raise


def test_header_mismatch_raises(tmp_path):
    path = _write(tmp_path, "bad.csv", b"WrongID,SizeRank,RegionName,RegionType,StateName\n")
    with pytest.raises(ValidationError, match="header prefix mismatch"):
        assert_csv_header_prefix(path, _ZILLOW_HEADER)


def test_header_fewer_columns_than_expected_raises(tmp_path):
    path = _write(tmp_path, "short.csv", b"RegionID,SizeRank\n1,2\n")
    with pytest.raises(ValidationError, match="header prefix mismatch"):
        assert_csv_header_prefix(path, _ZILLOW_HEADER)


def test_header_bom_is_stripped(tmp_path):
    path = _write(tmp_path, "bom.csv",
                  b"\xef\xbb\xbfRegionID,SizeRank,RegionName,RegionType,StateName\n1,2,3,4,5\n")
    assert_csv_header_prefix(path, _ZILLOW_HEADER)              # BOM must not cause a mismatch


# -- validate_download orchestration -----------------------------------------

def test_validate_download_csv_happy_path(tmp_path):
    data = b"RegionID,SizeRank,RegionName,RegionType,StateName\n1,2,3,4,5\n"
    path = _write(tmp_path, "z.csv", data)
    validate_download(path, fmt="csv", expected_header=_ZILLOW_HEADER, expected_size=len(data))


def test_validate_download_skips_header_for_xlsx(tmp_path):
    # opaque bytes; header set but fmt=xlsx → header check skipped, no raise (§16.6)
    path = _write(tmp_path, "a.xlsx", b"PK\x03\x04 binary xlsx bytes")
    validate_download(path, fmt="xlsx", expected_header=_ZILLOW_HEADER)


def test_validate_download_skips_header_for_json(tmp_path):
    path = _write(tmp_path, "a.json", b'{"x": 1}')
    validate_download(path, fmt="json", expected_header=_ZILLOW_HEADER)


def test_validate_download_skips_header_when_none(tmp_path):
    path = _write(tmp_path, "n.csv", b"anything\n")
    validate_download(path, fmt="csv", expected_header=None)


def test_validate_download_skips_size_when_unknown(tmp_path):
    path = _write(tmp_path, "n.csv", b"a,b\n1,2\n")
    validate_download(path, fmt="csv", expected_header=None, expected_size=None)


def test_validate_download_raises_on_empty(tmp_path):
    path = _write(tmp_path, "empty.csv", b"")
    with pytest.raises(ValidationError, match="empty"):
        validate_download(path, fmt="csv", expected_header=None)


def test_validate_download_raises_on_size_mismatch(tmp_path):
    data = b"a,b\n1,2\n"
    path = _write(tmp_path, "t.csv", data)
    with pytest.raises(ValidationError, match="truncation"):
        validate_download(path, fmt="csv", expected_header=None, expected_size=len(data) + 100)
