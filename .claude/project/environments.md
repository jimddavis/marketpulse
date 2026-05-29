# Project context and environments


## Deployment targets

| Target | Mode | Catalog | Purpose |
|---|---|---|---|
| `user` | development | `dev_marketpulse` | Laptop-driven iteration. Default for `bundle deploy` with no `--target`. Resources prefixed `[dev <user>]`. |
| `dev` | production | `dev_marketpulse` | CI-deployed shared dev. No per-user prefix. Never deployed from laptop. |
| `staging` | production | `staging_marketpulse` | Pre-production validation. |
| `prod` | production | `marketpulse` | Production on Free Edition. |


The catalog values above MUST match the `_target_catalog_map` dict in
`libs/notebook_init.ipynb` — see @.claude/project/deviations.md for that
load-bearing coupling.

## Environments

**Primary: Databricks Free Edition** (`dbc-d0f295f4-d028.cloud.databricks.com`)
- Serverless compute only — no classic clusters.
- No Workflows scheduling beyond what bundles provide.
- No Repos / Git integration in the UI.
- No cluster policies.
- Unity Catalog active, metastore auto-provisioned.


## Out of scope

Do not implement, recommend, or scaffold:

- **Delta Live Tables / Lakeflow Declarative Pipelines**.
- **Cluster policies** (Free Edition has none).
- **DBFS paths** (`/dbfs/...`). Unity Catalog Volumes only.
- **Performance tuning** (Z-ORDER, OPTIMIZE, VACUUM) without explicit ask.
- **Power BI integration** — eventual destination, but after AI/BI Dashboards
  validate the reporting layer.
- **Refactoring notebook logic for style** — the pipeline is working;
  do not rewrite on a hunch.
- **Workflow scheduling** beyond what bundles already provide.


