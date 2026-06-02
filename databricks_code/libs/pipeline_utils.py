"""Shared utility module — STUB.

Implement when the first Bronze notebook needs it. Function signatures
and docstrings below define the contract the rest of the pipeline
assumes. Do not change a signature without updating every caller (see
project CLAUDE.md § 6 — load-bearing values).

Conventions enforced by this module (project CLAUDE.md § 12):
- No module-level side effects.
- `spark` and `dbutils` are function parameters, never module globals.
- All `import` statements at the top of the file.
- Utility functions used by orchestration code return structured dicts
  on error (`{"status": "failed", "error_message": ...}`); functions
  called inside try/except blocks may raise normally.
"""

from __future__ import annotations

import traceback
from pathlib import PurePosixPath
from typing import Any


class Utils:
    """Namespace for stateless helpers used across Bronze / Silver / Gold notebooks."""

    @staticmethod
    def capture_exception(exc: BaseException) -> dict[str, str]:
        """Convert an exception into the structured dict logged to audit tables.

        Returns
        -------
        dict with keys: 'error_type', 'error_message', 'error_traceback'.

        Example caller pattern (CLAUDE.md § 11.4):

            try:
                ...
            except Exception as e:
                err = Utils.capture_exception(e)
                error_message = f"{err['error_type']}: {err['error_message']}\\n\\n{err['error_traceback']}"
                ...
                raise

            # Any dbutils.notebook.exit() goes OUTSIDE the try — it raises an
            # ordinary exception that `except Exception` would swallow (there is
            # no dbutils.NotebookExit class). See .claude/project/gotchas.md.
        """
        return {
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "error_traceback": "".join(traceback.format_tb(exc.__traceback__)),
        }

    @staticmethod
    def get_notebook_context(dbutils: Any) -> dict[str, str]:
        """Return notebook identity fields for an audit log row.

        Strips `/Workspace/Users/<email>/` (or `/Users/<email>/`) prefixes so
        `notebook_folder` is project-relative. On any failure returns "unknown"
        rather than raising — identity is best-effort metadata, not load-bearing.

        Returns
        -------
        dict with keys: 'notebook_folder', 'notebook_name', 'notebook_path_full'.
        """
        try:
            ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
            full_path = ctx.notebookPath().get()
        except Exception as e:
            return {
                "notebook_folder":    "unknown",
                "notebook_name":      "unknown",
                "notebook_path_full": f"error: {e}",
            }

        posix_path = PurePosixPath(full_path)
        folder_parts = posix_path.parts[1:-1]   # drop leading '/' and the notebook name itself
        if len(folder_parts) >= 2 and folder_parts[0] == "Workspace":
            folder_parts = folder_parts[1:]        # drop 'Workspace'
        if len(folder_parts) >= 2 and folder_parts[0] == "Users":
            folder_parts = folder_parts[2:]        # drop 'Users' and the email

        folder = "/".join(folder_parts) if folder_parts else "(root)"
        return {
            "notebook_folder":    folder,
            "notebook_name":      p.name,
            "notebook_path_full": full_path,
        }

    @staticmethod
    def archive_source_files(
        dbutils: Any,
        source_path: str,
        archive_subfolder: str = "archive",
    ) -> dict[str, Any]:
        """Move successfully-loaded source files to an archive subfolder.

        Returns
        -------
        dict with keys: 'status' ('succeeded' | 'failed'), 'archived_count',
        'archive_path', optional 'error_message'.

        Implementation notes:
        - Use `dbutils.fs.mv` for atomic moves within the same Volume.
        - Archive path: {source_path}/{archive_subfolder}/{run_id}/
        - Skip files matching `*.tmp` or starting with `.`.
        - This function MUST NOT raise — orchestration code calls it after
          a successful write; an archive failure should be logged but not
          roll back the successful Bronze write.
        """
        raise NotImplementedError("Implement when first Bronze notebook needs file archiving")

    @staticmethod
    def normalize_aware_datetime(dt):
        """Ensure a datetime is timezone-aware (UTC).

        Spark TIMESTAMP columns return offset-naive Python datetimes on read,
        but `datetime.now(timezone.utc)` returns offset-aware. Subtraction
        mixes the two and raises TypeError. Normalize at helper boundaries.
        """
        from datetime import timezone
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
