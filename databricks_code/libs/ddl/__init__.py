"""ddl — environment and table DDL for the marketpulse catalog.

One module per concern: provisioning (`catalog_setup`) + per-layer table DDL
(`audit_ddl`, `bronze_ddl`, `silver_ddl`, `gold_ddl`), with shared helpers in `_utils`.
The `create_*` functions are re-exported here so the setup orchestrator imports them from
one place:

    from ddl import (create_catalog, create_schemas, create_volume_schema, create_volumes,
                     create_audit_tables, create_bronze_tables, create_silver_tables,
                     create_gold_tables)

Imports resolve on Databricks because notebook_init puts `…/files/libs` on sys.path
(same mechanism as `import data_fetch`).
"""

from ddl.audit_ddl import create_audit_tables
from ddl.bronze_ddl import create_bronze_tables
from ddl.catalog_setup import (
    create_catalog,
    create_schemas,
    create_volume_schema,
    create_volumes,
)
from ddl.gold_ddl import create_gold_tables
from ddl.silver_ddl import create_silver_tables
from ddl.weather_data import create_weather_bronze_tables

__all__ = [
    "create_catalog",
    "create_schemas",
    "create_volume_schema",
    "create_volumes",
    "create_audit_tables",
    "create_bronze_tables",
    "create_weather_bronze_tables",
    "create_silver_tables",
    "create_gold_tables",
]
