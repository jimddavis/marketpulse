# Deploy the marketpulse Bundle

Deploy the bundle to a specific target after validating it first. Always validate before deploying — treat a clean validate as the required checkpoint.

## Valid targets

| Target | Catalog | Mode |
|--------|---------|------|
| `dev` (default) | `dev_marketpulse` | development |
| `staging` | `staging_marketpulse` | development |
| `prod` | `marketpulse` | production |

## Step 1: Determine the target

If `$ARGUMENTS` names a target, use it. If not, ask the user which target before proceeding.

## Step 2: Validate

Run validation and show the user the output:

```bash
databricks bundle validate --target <target>
```

If validation fails, diagnose and fix the error before proceeding. Do not deploy to a failed validate. Common errors:

| Error | Fix |
|-------|-----|
| `mode: production must set workspace.root_path` | Add `workspace: root_path: ...` explicitly inside the `prod:` target block — inheriting the global value is not enough for production mode |
| `Warning: %run cell magic must be at start of cell` | The `%run` magic line has a comment above it in the notebook. Move the `%run` to its own cell with no content above it |
| `Variable not found` | Variable referenced with `${var.name}` but not declared in the `variables:` section |
| `Task depends_on unknown task_key` | A `depends_on` references a `task_key` that doesn't exist in the same job — check spelling |

## Step 3: Deploy

```bash
databricks bundle deploy --target <target>
```

After deployment, tell the user:
- What files were uploaded (bundle deploys to `${workspace.root_path}/files/`)
- Which jobs were created or updated in the workspace
- What `shared_lib_path` resolves to for this target (so they know where the shared modules landed)

## Step 4: Remind about job naming

In `mode: development`, Databricks prepends `[dev <username>]` to the job name automatically. The bundle also appends `(${bundle.target})` to distinguish targets. The user will see jobs named like:

- `[dev zieder0022] marketpulse_ELT_Pipeline (dev)`
- `[dev zieder0022] marketpulse_Environment_Setup (staging)`
- `marketpulse_ELT_Pipeline (prod)` ← no prefix in production mode

## Key concepts

- **`${bundle.target}`** — built-in substitution that resolves to the target name at deploy time. Used in job names and `workspace.root_path` to keep every deployment distinct.
- **`${workspace.root_path}`** — resolves to the path where this bundle deployed its files. For dev: `.../marketpulse_bundle/dev`. Drives `shared_lib_path` automatically.
- **`mode: development`** vs **`mode: production`** — development allows multiple copies of the same bundle (one per developer); production enforces a single copy and requires explicit `root_path`.
