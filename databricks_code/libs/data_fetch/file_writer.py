"""FileWriter Adapter protocol (WS0).

Adapts the final 'promote a completed, validated local temp file to its destination'
hop — local filesystem vs Unity Catalog Volume. Concrete writers (LocalFileWriter,
VolumeFileWriter) are WS-C. The Volume base path is owned by notebook_init (RAW_FILES)
and never reconstructed inside the package (design §8, §16.7).
"""

from __future__ import annotations

import errno
import os
import shutil
from typing import Protocol, runtime_checkable


@runtime_checkable
class FileWriter(Protocol):
    def promote(self, local_tmp_path: str, source_system: str, final_name: str) -> str:
        """Place a completed, validated LOCAL temp file at its final destination.
        Returns the final path/URI (design §8)."""
        ...

    def final_size(self, source_system: str, final_name: str) -> int:
        """Bytes of an existing final file; 0 if absent. For no-op / diagnostics (§8)."""
        ...

    def destination(self, source_system: str, final_name: str) -> str:
        """The final path/URI a promote would target — WITHOUT moving anything. Lets the
        runner log landed_file_path on SKIPPED (no-op) and FAILED rows."""
        ...


class LocalFileWriter:
    """Promote a completed scratch file into a local directory tree (design §8).

    For local dev and pytest. Destination is `<root>/<source_system>/<final_name>`.
    Uses os.replace (atomic) when scratch and destination share a filesystem; falls back
    to shutil.move on EXDEV (cross-filesystem — e.g. tempfile.gettempdir() and `root` on
    different mounts) so local runs don't fail on a tmpfs /tmp.
    """

    def __init__(self, root: str):
        self._root = root

    def destination(self, source_system: str, final_name: str) -> str:
        return os.path.join(self._root, source_system, final_name)

    def promote(self, local_tmp_path: str, source_system: str, final_name: str) -> str:
        dest = self.destination(source_system, final_name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            os.replace(local_tmp_path, dest)          # atomic rename, same FS
        except OSError as e:
            if e.errno != errno.EXDEV:
                raise
            shutil.move(local_tmp_path, dest)          # cross-FS fallback (copy + unlink)
        return dest

    def final_size(self, source_system: str, final_name: str) -> int:
        dest = self.destination(source_system, final_name)
        return os.path.getsize(dest) if os.path.exists(dest) else 0


class VolumeFileWriter:
    """Promote a completed scratch file into a Unity Catalog Volume (design §8, §16.7).

    On Databricks the Volume FUSE mount rejects append/random writes, and os.replace
    across the local→Volume boundary raises EXDEV, so the completed, validated file is
    COPIED (scratch is left intact). `raw_base` is notebook_init's RAW_FILES
    (`/Volumes/<catalog>/raw/`) — never reconstructed inside the package. Destination is
    `<raw_base>/<source_system>/<final_name>`; the manifest keeps SourceSpec.name ==
    SourceSpec.volume, so `source_system` selects the matching Volume (the runner passes
    spec.name).

    CONFIDENCE: standard-file-API writes to /Volumes are Verified (design §8). os.makedirs
    on a Volume is exercised only at WS-I; in the common case the Volume root already
    exists, so exist_ok=True is a no-op.
    """

    def __init__(self, raw_base: str):
        self._raw_base = raw_base

    def destination(self, source_system: str, final_name: str) -> str:
        return os.path.join(self._raw_base, source_system, final_name)

    def promote(self, local_tmp_path: str, source_system: str, final_name: str) -> str:
        dest = self.destination(source_system, final_name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy(local_tmp_path, dest)              # cross-FS copy; scratch left intact
        return dest

    def final_size(self, source_system: str, final_name: str) -> int:
        dest = self.destination(source_system, final_name)
        return os.path.getsize(dest) if os.path.exists(dest) else 0
