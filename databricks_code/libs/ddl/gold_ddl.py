# ddl/gold_ddl.py
# Gold-layer table DDL. STUB — populated when the Gold layer is implemented:
# fact/dimension tables with GENERATED ALWAYS AS IDENTITY surrogate keys (CLAUDE.md).

from ddl._utils import _ok


def create_gold_tables(spark, gold_schema):
    # No Gold tables defined yet — clean no-op (see bronze_ddl for rationale).
    return _ok("Gold DDL not yet implemented — 0 tables.")
