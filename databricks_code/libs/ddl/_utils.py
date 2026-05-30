"""Shared DDL helpers for the `ddl` package.

`_run_ddl` executes a list of `(object_name, sql)` pairs in order, stops on the first
error, and returns a structured result dict. Imported by every `<layer>_ddl` module so
each is standalone (no reliance on `_run_ddl` being in scope, the prior AUDIT_DDL coupling).
`_ok` / `_fail` are the shared result-dict shape used by the provisioning functions too.
"""

import traceback


def _ok(message, objects_created=None):
    return {
        "status":          "succeeded",
        "message":         message,
        "objects_created": objects_created or [],
        "error":           None,
    }


def _fail(message, exc):
    return {
        "status":          "failed",
        "message":         message,
        "objects_created": [],
        "error":           f"{type(exc).__name__}: {exc}\n{''.join(traceback.format_exception(exc))}",
    }


def _run_ddl(spark, statements):
    """Execute a list of (object_name, sql) pairs in order.
    Stops and returns a failed result on the first error."""
    created = []
    for object_name, sql in statements:
        try:
            spark.sql(sql)
            created.append(object_name)
        except Exception as e:
            return _fail(f"Failed to create '{object_name}'.", e)
    return _ok(f"{len(created)} table(s) ready.", created)
