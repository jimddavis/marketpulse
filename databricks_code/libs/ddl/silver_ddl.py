# ddl/silver_ddl.py
# Silver-layer table DDL. STUB — populated when the Silver layer is implemented:
# conformed dims (dim_geo, dim_date), per-source fact tables, and quarantine_* tables
# (see bronze_silver_pipeline_overview.md).

from ddl._utils import _ok


def create_silver_tables(spark, silver_schema):
    # No Silver tables defined yet — clean no-op (see bronze_ddl for rationale).
    return _ok("Silver DDL not yet implemented — 0 tables.")
