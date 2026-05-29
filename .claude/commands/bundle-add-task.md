# Add a Task to the marketpulse Bundle

Add a new notebook task to `databricks.yml` in the correct job, with the right path format, dependencies, and environment key.

## Step 1: Gather requirements

If `$ARGUMENTS` does not provide all of the following, ask before changing anything:

1. **Task name** (`task_key`) — snake_case, e.g. `load_dim_currency`
2. **Notebook path** — relative to bundle root, e.g. `./silver/my_notebook.ipynb`. The notebook file must already exist locally.
3. **Which job** — see decision guide below
4. **Depends on** — which `task_key`(s) must complete before this task runs? (Can be none for the first task in a chain)
5. **Needs serverless environment?** — if the notebook uses PySpark with external libraries, add `environment_key: Default`

## Step 2: Choose the right job

| Characteristic | Job |
|---------------|-----|
| Creates catalogs, schemas, tables, volumes — run once per environment | `marketpulse_environment_setup` |
| Moves, reads, transforms, or writes pipeline data — run every cycle | `marketpulse_elt_pipeline` |

**The rule:** infrastructure lifecycle belongs in setup; data lifecycle belongs in the pipeline. Do not mix them. A pipeline job task that creates a table it then writes to is flaky — the table may not exist on the first run of a new environment.

## Step 3: Add the task to `databricks.yml`

### Notebook task (most tasks)

```yaml
- task_key: <task_key>
  depends_on:
    - task_key: <predecessor_task_key>
  notebook_task:
    notebook_path: ./<path/to/notebook>.ipynb
  environment_key: Default    # include only if needed
```

### Python script task (for `src/` scripts like `init_pipeline_run_log.py`)

```yaml
- task_key: <task_key>
  depends_on:
    - task_key: <predecessor_task_key>
  spark_python_task:
    python_file: ./src/<script>.py
    parameters:
      - "${var.shared_lib_path}"    # add any variables the script needs via sys.argv
  environment_key: Default
```

## Step 4: Wire dependencies correctly

- The new task's `depends_on` must reference a `task_key` in the **same job**. Cross-job dependencies are not supported in bundle YAML.
- If the new task has no predecessor (it's a new root task), omit `depends_on` entirely.
- If the new task should run in parallel with an existing task (same predecessor), give both the same `depends_on`.
- If existing tasks depend on where this task fits in the sequence, update their `depends_on` too.

## Step 5: Notebook path rules

- Always use `./relative/path.ipynb` — relative to the bundle root (`databricks.yml` location)
- Never use an absolute workspace path like `/Workspace/Users/...` — that bypasses the bundle and breaks multi-environment deployment
- The `source: WORKSPACE` property is only needed for notebooks that are NOT managed by the bundle (legacy holdovers). Remove it once the notebook is local.

## Step 6: The `%run` rule

If the new notebook uses `%run "/Workspace/Shared/notebook_init"`, the `%run` magic **must be the very first character of the cell** — no comments, no blank lines above it. Put any notebook header in a separate markdown cell before the `%run` cell. Violating this causes Databricks to treat it as an IPython line magic instead of the Databricks cell magic, and the run silently fails.

## Step 7: Validate after adding

```bash
databricks bundle validate
```

Fix any errors before deploying. A clean validate is the required checkpoint.
