# Azure Databricks — Bundle Deployment Guidance

## Catalog Creation: MANAGED LOCATION Required

On Azure Databricks, `CREATE CATALOG` fails unless the metastore has a default storage root
configured **or** you supply an explicit `MANAGED LOCATION` clause pointing to ADLS Gen2:

```sql
-- Fails on Azure without default metastore storage:
CREATE CATALOG IF NOT EXISTS vinoworld

-- Required on Azure when no default storage is configured:
CREATE CATALOG IF NOT EXISTS vinoworld
    MANAGED LOCATION 'abfss://<container>@<storage-account>.dfs.core.windows.net/<path>'
```

**Error you will see without it:**
```
[INVALID_STATE] Metastore storage root URL does not exist. Default Storage is enabled
in your account. You can use the UI to create a new catalog using Default Storage,
or please provide a storage location for the catalog.
```

### Bundle Pattern: Variable-Driven MANAGED LOCATION

Use a `managed_location` bundle variable so the same notebook works across environments
without branching logic:

**`databricks.yml`:**
```yaml
variables:
  managed_location:
    description: >
      ADLS abfss:// path for catalog MANAGED LOCATION (Azure only).
      Leave empty for Free Edition — omits the clause entirely.
    default: ""

targets:
  dev:                          # Free Edition — no clause needed
    ...
  azure_prod:
    variables:
      managed_location: "abfss://<container>@<storage-account>.dfs.core.windows.net/<path>"
```

Pass it as a job parameter on the environment setup job:
```yaml
parameters:
  - name: managed_location
    default: ${var.managed_location}
```

**Notebook widget (catalog_ddl):**
```python
dbutils.widgets.text("managed_location", "")
MANAGED_LOCATION = dbutils.widgets.get("managed_location") or None
```

The `or None` converts an empty string to `None` so the utility function receives
a clean sentinel value rather than an empty string.

**Utility function (`catalog_setup.py`):**
```python
def create_catalog(spark, catalog, managed_location=None):
    location_clause = f"\n    MANAGED LOCATION '{managed_location}'" if managed_location else ""
    spark.sql(f"CREATE CATALOG IF NOT EXISTS {catalog}{location_clause}")
```

Free Edition receives `""` → `None` → no clause.
Azure receives the `abfss://` path → clause is included.

---

## Prerequisites: Azure Infrastructure (Outside Bundle Scope)

The bundle assumes this Azure infrastructure already exists before `bundle deploy` runs.
It does **not** provision any of it — that belongs in Terraform or Bicep:

- ADLS Gen2 storage account and container
- External Location registered in Databricks Unity Catalog
- Service principal with Storage Blob Data Contributor on the container
- Databricks metastore linked to the Unity Catalog

---

## Workspace User Identity

Azure Databricks users are typically Azure AD accounts and will have a different email
than Free Edition accounts. Never hardcode a username in `root_path`.

Use the bundle substitution that resolves at deploy time:
```yaml
root_path: /Workspace/Users/${workspace.current_user.userName}/.bundle/${bundle.name}/${bundle.target}
```

This works correctly in both Free Edition and Azure without any target-specific override.
