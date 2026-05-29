# Add a Bundle Variable with Multi-Environment Support

Make a value environment-specific by wiring it through the full chain:
**YAML variable → job parameter → notebook widget → Python constant**

This is the pattern used for `catalog` and `shared_lib_path`. Use it whenever a value must differ between dev, staging, and prod.

## Step 1: Gather requirements

If `$ARGUMENTS` does not provide all of the following, ask before generating anything:

1. **Variable name** — snake_case, e.g. `source_system`
2. **Description** — one sentence for the `variables:` block
3. **Default value** — used by prod and any target that doesn't override it
4. **Per-target overrides** — which targets need a different value from the default?
5. **Which job(s)** — `marketpulse_environment_setup`, `marketpulse_elt_pipeline`, or both?
6. **Does `notebook_init.ipynb` need a corresponding constant?** — yes for values notebooks need; no for values only used by Python script tasks via `sys.argv`

## Step 2: Add to `databricks.yml`

### 2a — Declare in the `variables:` section

```yaml
variables:
  <name>:
    description: <description>
    default: <default_value>
```

### 2b — Pass as a job parameter on each affected job

```yaml
parameters:
  - name: <name>
    default: ${var.<name>}
```

### 2c — Add per-target overrides in `targets:`

Only add overrides for targets that differ from the default. Do not repeat the default value.

```yaml
targets:
  dev:
    variables:
      <name>: <dev_value>
  staging:
    variables:
      <name>: <staging_value>
  # prod inherits default if no override needed
```

## Step 3: Update `Shared/notebook_init.ipynb`

If notebooks need the value as a Python constant, add a widget and read it. The widget default is the fallback for manual/standalone runs — use the prod/default value here.

Add this block in the constants section, grouped with similar constants:

```python
dbutils.widgets.text("<name>", "<default_value>")
<CONSTANT_NAME> = dbutils.widgets.get("<name>")
```

**Why widgets?** When a notebook runs as a Databricks job task, every job-level parameter is automatically available as a widget value. `dbutils.widgets.get("<name>")` will return the bundle-injected value. The `dbutils.widgets.text(...)` call only sets the default — it does not override a value already provided by the job.

## Step 4: Validate

```bash
databricks bundle validate --target dev
databricks bundle validate --target staging
databricks bundle validate --target prod
```

All three must pass before deploying.

## Rules

- Never hardcode an environment-specific value in notebook code. It must come through the widget chain.
- The widget default in `notebook_init.ipynb` should always be the prod/safe value so a manual run doesn't accidentally hit a wrong environment.
- `${var.name}` in YAML, `dbutils.widgets.get("name")` in Python — these must use the exact same string name.
- For Python script tasks (`spark_python_task`), job parameters are NOT available as widgets. Pass the value explicitly via `spark_python_task.parameters` and read it with `sys.argv[n]`.
