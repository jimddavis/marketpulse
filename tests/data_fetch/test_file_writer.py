"""WS-C — LocalFileWriter / VolumeFileWriter unit tests. Pure filesystem, no network."""

from __future__ import annotations

import errno
import os

import pytest

from data_fetch.file_writer import FileWriter, LocalFileWriter, VolumeFileWriter


def _scratch(tmp_path, name="scratch.bin", data=b"payload"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


# -- LocalFileWriter (os.replace; consumes scratch) --------------------------

def test_local_writer_moves_into_source_subdir(tmp_path):
    root = tmp_path / "root"
    scratch = _scratch(tmp_path, data=b"hello")
    writer = LocalFileWriter(str(root))

    dest = writer.promote(scratch, "zillow", "zhvi.csv")

    assert dest == str(root / "zillow" / "zhvi.csv")
    assert os.path.exists(dest)
    assert open(dest, "rb").read() == b"hello"
    assert not os.path.exists(scratch)        # os.replace consumed the scratch file
    assert isinstance(writer, FileWriter)


def test_local_writer_final_size(tmp_path):
    root = tmp_path / "root"
    writer = LocalFileWriter(str(root))
    assert writer.final_size("fred", "missing.csv") == 0
    writer.promote(_scratch(tmp_path, data=b"1234"), "fred", "x.csv")
    assert writer.final_size("fred", "x.csv") == 4


def test_local_writer_falls_back_to_move_on_exdev(tmp_path, monkeypatch):
    root = tmp_path / "root"
    scratch = _scratch(tmp_path, data=b"crossfs")
    writer = LocalFileWriter(str(root))

    def _raise_exdev(src, dst):
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr(os, "replace", _raise_exdev)
    dest = writer.promote(scratch, "realtor", "hist.csv")     # must fall back to shutil.move

    assert open(dest, "rb").read() == b"crossfs"
    assert not os.path.exists(scratch)


def test_local_writer_reraises_non_exdev_oserror(tmp_path, monkeypatch):
    writer = LocalFileWriter(str(tmp_path / "root"))
    scratch = _scratch(tmp_path)

    def _raise_eperm(src, dst):
        raise OSError(errno.EPERM, "nope")

    monkeypatch.setattr(os, "replace", _raise_eperm)
    with pytest.raises(OSError) as ei:
        writer.promote(scratch, "fhfa", "f.csv")
    assert ei.value.errno == errno.EPERM


# -- VolumeFileWriter (shutil.copy; leaves scratch intact) -------------------

def test_volume_writer_copies_and_leaves_scratch(tmp_path):
    # raw_base is a local dir here; the join/copy logic is identical to a /Volumes base.
    raw_base = tmp_path / "Volumes" / "cat" / "raw"
    scratch = _scratch(tmp_path, data=b"vol-bytes")
    writer = VolumeFileWriter(str(raw_base))

    dest = writer.promote(scratch, "fhfa", "hpi_master.csv")

    assert dest == str(raw_base / "fhfa" / "hpi_master.csv")
    assert open(dest, "rb").read() == b"vol-bytes"
    assert os.path.exists(scratch)            # copy semantics — scratch NOT consumed
    assert isinstance(writer, FileWriter)


def test_volume_writer_final_size(tmp_path):
    raw_base = tmp_path / "raw"
    writer = VolumeFileWriter(str(raw_base))
    assert writer.final_size("zillow", "none.csv") == 0
    writer.promote(_scratch(tmp_path, data=b"abcde"), "zillow", "z.csv")
    assert writer.final_size("zillow", "z.csv") == 5
