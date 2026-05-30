# ddl/bronze_ddl.py
# Bronze-layer table DDL. STUB — populated when the Bronze layer is implemented:
# one all-STRING table per source-file-pattern (see bronze_silver_pipeline_overview.md).

from ddl._utils import _ok


def create_bronze_tables(spark, bronze_schema):
    # No Bronze tables defined yet — clean no-op so the orchestrator's dependency chain
    # (catalog → schema → tables) stays intact and re-runs cheaply.
    return _ok("Bronze DDL not yet implemented — 0 tables.")
