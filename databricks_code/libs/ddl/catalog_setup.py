# ddl/catalog_setup.py
# Provisioning utilities for the marketpulse Databricks environment (catalog, schemas,
# volumes). Called from setup/catalog_ddl.ipynb — never imported by pipeline notebooks.
# Table DDL lives in the sibling <layer>_ddl modules; shared helpers in ddl._utils.

from ddl._utils import _fail, _ok


# ---------------------------------------------------------------------------
# Group A: Catalog and Schemas
# ---------------------------------------------------------------------------

def create_catalog(spark, catalog, managed_location=None):
    try:
        location_clause = f"\n    MANAGED LOCATION '{managed_location}'" if managed_location else ""
        spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog}{location_clause}")
        return _ok(f"Catalog '{catalog}' is ready.", [catalog])
    except Exception as e:
        return _fail(f"Failed to create catalog '{catalog}'.", e)


def create_schemas(spark, schemas):
    """schemas: list of fully-qualified schema names, e.g. ['marketpulse.bronze', ...]"""
    created = []
    for schema in schemas:
        try:
            spark.sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            created.append(schema)
        except Exception as e:
            return _fail(f"Failed to create schema '{schema}'.", e)
    return _ok(f"{len(created)} schema(s) ready.", created)


def create_volume_schema(spark, catalog):
    schema = f"{catalog}.raw"
    try:
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        return _ok(f"Volume schema '{schema}' is ready.", [schema])
    except Exception as e:
        return _fail(f"Failed to create volume schema '{schema}'.", e)


# ---------------------------------------------------------------------------
# Group B: Volumes and Directories
# ---------------------------------------------------------------------------

def create_volumes(spark, dbutils, catalog, volume_definitions):
    """
    volume_definitions: list of {"name": str, "needs_archive": bool}
    Creates each volume under catalog.raw and, when needs_archive is True,
    creates the archive subfolder inside the volume path.
    """
    created = []
    for vol in volume_definitions:
        name      = vol["name"]
        full_name = f"{catalog}.raw.{name}"
        vol_path  = f"/Volumes/{catalog}/raw/{name}"
        try:
            spark.sql(f"CREATE VOLUME IF NOT EXISTS {full_name}")
            if vol.get("needs_archive"):
                dbutils.fs.mkdirs(f"{vol_path}/archive")
            created.append(full_name)
        except Exception as e:
            return _fail(f"Failed to create volume '{full_name}'.", e)
    return _ok(f"{len(created)} volume(s) ready.", created)
