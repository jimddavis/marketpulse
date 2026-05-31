#!/usr/bin/env python3
"""Local download harness for the data_fetch framework.

Runs the REAL framework end-to-end (providers → validation → sha256 → retry →
LocalFileWriter) against the live source URLs, landing files under
``<repo>/_local_downloads/<source>/``. No Databricks, no Spark: the journal is a no-op
(``last_sha256`` → None, so every run re-downloads and nothing is logged to an audit
table). FRED needs ``FRED_API_KEY`` in ``<repo>/.env``.

Run from the project root:

    uv run --python 3.12 scripts/download_local.py dl_all
    uv run --python 3.12 scripts/download_local.py dl_zillow
    uv run --python 3.12 scripts/download_local.py dl_fhfa
    uv run --python 3.12 scripts/download_local.py dl_realtor
    uv run --python 3.12 scripts/download_local.py dl_fred
"""

from __future__ import annotations

import sys
from pathlib import Path

# The framework lives under the bundle root; put it on sys.path before importing.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "databricks_code" / "libs"))

from data_fetch import (  # noqa: E402 — import after sys.path setup
    SOURCES,
    WEATHER_SOURCES,
    DownloadJournal,
    DotenvSecretResolver,
    LocalFileWriter,
    local_run_context,
    run_all,
)

DEST_ROOT = _REPO / "_local_downloads"


def _run(sources):
    DEST_ROOT.mkdir(parents=True, exist_ok=True)
    summary = run_all(
        sources,
        local_run_context(),
        writer=LocalFileWriter(str(DEST_ROOT)),
        journal=DownloadJournal.noop(),
        secrets=DotenvSecretResolver(start_dir=str(_REPO)),
    )
    print(summary.describe())
    for o in summary.outcomes:
        size = f"{o.bytes_downloaded:,} B" if o.bytes_downloaded is not None else "-"
        print(f"  [{o.status:9}] {o.source_system}/{o.landed_filename}  ({size})  -> {o.landed_file_path}")
    return summary


def _only(name: str):
    return tuple(s for s in SOURCES if s.name == name)


def dl_all():
    """Download every source. Abort-on-first: stops at the first file that fails."""
    return _run(SOURCES)


def dl_zillow():
    return _run(_only("zillow"))


def dl_fhfa():
    return _run(_only("fhfa"))


def dl_realtor():
    return _run(_only("realtor"))


def dl_fred():
    """Needs FRED_API_KEY in <repo>/.env."""
    return _run(_only("fred"))


def dl_weather():
    """Annual weather/hazard sources (FEMA NRI + NOAA Climate Normals) — the WEATHER_SOURCES
    tuple, separate from the monthly SOURCES. Lands the NRI CSV + the Normals tarball +
    inventory under _local_downloads/. (Normalize step is a Databricks notebook, not here.)"""
    return _run(WEATHER_SOURCES)


_METHODS = {
    "dl_all": dl_all,
    "dl_zillow": dl_zillow,
    "dl_fhfa": dl_fhfa,
    "dl_realtor": dl_realtor,
    "dl_fred": dl_fred,
    "dl_weather": dl_weather,
}


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1 or argv[0] not in _METHODS:
        print(f"usage: download_local.py <{' | '.join(_METHODS)}>", file=sys.stderr)
        return 2
    try:
        _METHODS[argv[0]]()
    except Exception as e:
        print(f"FAILED ({type(e).__name__}): {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
