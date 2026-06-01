# Variable Renaming Plan — single-letter → descriptive names

**Status:** Plan (not yet executed)
**Author:** prepared 2026-06-01
**Driver:** CLAUDE.md §13 *Descriptive variable names* — added mid-project, so much of
the existing code predates it and still uses single-letter bindings.

> **Descriptive variable names.** Name a variable for what it holds … never a bare
> single letter … *including* loop and comprehension variables. Exceptions: established
> project aliases (`F`, `df` / `*_df`) and a throwaway `_`.

This document is the safe, staged execution plan for bringing the codebase into
compliance. It is organized **module/object → step**, with a verification gate between
steps, so we never make one large change and then debug a wall of breakage.

---

## 1. Decisions baked into this plan

Two scope decisions were confirmed with the user before writing:

1. **`e` in exception handlers is an accepted idiom and stays.** `except … as e:` is the
   exact form CLAUDE.md's own error-handling examples use (§10.1, §11.4: `except Exception
   as e: step.fail(e); raise`). Renaming it would contradict those canonical examples and
   roughly double the churn for no readability gain. **Action:** add `e` (exception
   handlers only) to the CLAUDE.md §13 / §16 exceptions list — see Step 0.2. This also
   covers exception-typed *parameters* that carry the same object (e.g.
   `retrying.RetryingProvider._is_transient(self, e: BaseException)` and `_delay(…, e)`).

2. **Production code only.** In scope: `databricks_code/` (libs + notebooks) and
   `scripts/`. **Out of scope:** throwaway/scratch artifacts — `bronze/step_log_test*.ipynb`,
   `scripts/scratch/*`, everything under `_dev_planning/`, and the `tests/` suite —
   *except* test call-sites that pass a renamed **public keyword parameter** (only
   `tests/data_fetch/test_retrying.py`, which calls `fetch_to(… f=None …)`; that file is
   updated atomically with the provider rename in Step 1.3).

Additional standing rules for this work:

- **Name for local meaning, never blanket replace.** A single letter often means
  different things in different scopes (e.g. `s` in `build_crosswalk.py` is variously a
  raw string, a state code, and a city). **Do not `replace_all`** a single letter across a
  file — rename per occurrence to what it holds in that scope.
- **One module/object per step**, verified before the next (§ CLAUDE.md "one task at a
  time"). The one exception is the cross-file provider-parameter rename (Step 1.3), which
  is **atomic** per CLAUDE.md §20 because the name is also used as a keyword argument.

---

## 2. Inventory (in-scope only)

Produced by `_dev_planning/scan_single_letter.py` (AST-based: flags assignment, for-loop,
comprehension, `with`-as, lambda-arg, and function-parameter bindings; allows `F` and `_`).
Raw scan = **240** single-letter bindings. After removing `e`/exception objects, `tests/`,
and scratch, the **in-scope total is ≈107 bindings across ~24 files**:

| Area | Files | In-scope bindings | Test coverage |
|---|---|---|---|
| `data_fetch` package | `secrets`, `validation`, `runner`, `providers/{base,http_file,fred_api,arcgis_feature_service,retrying}` | ~25 (+2 coupled test sites) | **Full** — 114 local pytest, no Spark |
| other libs | `pipeline_logging`, `pipeline_utils`, `wide_to_long/{detect,validate}` | ~6 | Partial — wide_to_long needs Spark (see §3) |
| scripts | `build_crosswalk`, `download_local` | ~16 | Manual / smoke run |
| bronze notebooks | `load_{zillow,fhfa,fred,realtor}` | ~23 | Databricks job run only |
| silver notebooks | `load_silver_{zillow,fhfa,fred,realtor,fema_hazard,noaa_climate}` | ~35 | Databricks job run only |
| setup notebooks | `seed_dim_date`, `seed_dim_geo` | ~2 | Databricks run only |

Files with **zero** single-letter bindings (no work): all `ddl/*` except `e` handlers,
`finalize_pipeline_run_log`, `init_pipeline_run_log`, `climate_normals_columns`,
`build_station_cbsa`, `load_zillow_long`, `load_climate_normals`, `load_fema_nri`,
`process_climate_normals`, `catalog_ddl`, `seed_dim_fred_series`.

The scanner is the **regression oracle**: re-run it after each step and confirm the
in-scope count for the touched file(s) drops to zero (residual hits will be only `e`
handlers + out-of-scope files).

---

## 3. Verification infrastructure & a hard constraint

| Layer | How to verify a step | Command |
|---|---|---|
| `data_fetch` | Unit tests (no Spark) | `uv run --python 3.12 python -m pytest tests/data_fetch -q` |
| Any `.py` | Parses & imports cleanly | `uv run --python 3.12 python -m py_compile <file>` ; `ruff check <file>` if available |
| `wide_to_long` | Unit tests — **blocked, see below** | `python -m pytest tests/wide_to_long -q` |
| Notebooks | Static parse of every code cell, then a **dev** job run | `databricks bundle validate --target dev`; run the layer job; check `audit.*_log` + row counts |
| `scripts/download_local` | Live smoke run | `uv run --python 3.12 scripts/download_local.py dl_zillow` |

**Baseline captured this session:** `tests/data_fetch` = **114 passed**. `data_fetch` work
is therefore fully guarded locally.

> **⚠ Constraint — local Spark is currently broken.** The installed PySpark requires
> **Java 17** (`UnsupportedClassVersionError`, class file v61), but only JDK 8 and 11 are
> present (`/usr/lib/jvm/`), so every Spark-touching local test fails with
> `JAVA_GATEWAY_EXITED`. This affects `tests/wide_to_long` and any local notebook
> emulation. **Resolve before Phase 2/4 verification** by installing a JDK 17 (e.g.
> Temurin 17) and exporting `JAVA_HOME` to it. Until then, `wide_to_long` and notebook
> renames are verified by static parse + a Databricks dev run, **not** local tests. This
> is the single biggest risk to "test between steps" and should be fixed first if we want
> local guardrails for Phases 2–4. *(Parked finding — fixing the JDK is out of scope for
> the rename task itself; flagged here per CLAUDE.md §7.)*

A reusable static gate for notebooks (no Spark needed):

```bash
# parse every code cell of a notebook as Python — catches rename typos / NameErrors
uv run --python 3.12 python - <<'PY' databricks_code/silver/load_silver_realtor.ipynb
import ast, json, sys
nb = json.load(open(sys.argv[1]))
for i, c in enumerate(nb["cells"]):
    if c["cell_type"] != "code": continue
    src = "".join("pass\n" if l.lstrip().startswith(("%","!")) else l for l in c["source"])
    try: ast.parse(src)
    except SyntaxError as ex: print(f"cell {i}: {ex}")
print("parsed OK")
PY
```

---

## 4. Naming conventions for the common patterns

| Old | Context | New (name for what it holds) |
|---|---|---|
| `f` | `for f in files:` / `f.path` (file path) | `file_path` |
| `f` | provider param of type `SourceFile` | `source_file` |
| `f` | `wide_to_long` comprehension over column names | `field` / `col_name` |
| `c` | `[… for c in columns]`, `lambda c: c.name` | `column` |
| `c` | `build_crosswalk` city blob comprehension | `city` |
| `p` | `(p, h)` header-mismatch pair | `file_path`, then `actual_header` |
| `p` | `provider.probe(...)` result | `probe_result` |
| `h` | header / hash | `actual_header` / `hasher` |
| `k`, `v` | `k, _, v = line.partition("=")` | `key`, `value` |
| `o` | `for o in summary.outcomes` | `outcome` |
| `r` | `for r in results` (healthcheck) | `result` |
| `s` | `for s in SOURCES if s.name == …` | `source` |
| `x` | silver select/comprehension element | name per meaning (`column`, `row`, …) |
| `e` | `except … as e` / `e: BaseException` param | **keep `e`** (decision §1.1) |

When the right name isn't obvious from context (notably `build_crosswalk.py`), read the
surrounding 5–10 lines and name for the value's role — do not guess from the letter.

---

## 5. The staged plan

Each step: **edit → static gate → test gate → re-run scanner on touched files → commit.**
Commit per step (or per phase for the trivial ones) so any regression is bisectable and
revertible in isolation.

### Phase 0 — Prep (no code renames)

- **0.1 Lock the baseline.** Confirm `tests/data_fetch` = 114 pass. Decide the JDK-17 fix
  for Spark (install Temurin 17 → `JAVA_HOME`) or accept static-only verification for
  Phases 2/4 and record that choice here. Keep `scan_single_letter.py` as the oracle.
- **0.2 Update CLAUDE.md.** Add `e` (exception handlers, and exception-typed params) to
  the §13 / §16 / anti-patterns exceptions list, with a one-line reason. This makes the
  rule self-consistent with its own examples before we start enforcing it. *Verify:* doc
  only — re-read the edited bullet.

### Phase 1 — `data_fetch` package (fully test-guarded → do first to prove the workflow)

- **1.1 Leaf helpers.** `secrets.py` (`k,v` → `key,value`), `validation.py`
  (`h` → `hasher`). *Verify:* `pytest tests/data_fetch`.
- **1.2 `runner.py` local vars.** `o` → `outcome` (RunSummary comp), `p` → `probe_result`
  (line ~100), `r` → `result` (healthcheck print loop). **Leave the `f` param for 1.3.**
  *Verify:* `pytest tests/data_fetch`.
- **1.3 [ATOMIC, cross-file] provider `SourceFile` param `f` → `source_file`.** Touches
  `providers/base.py`, `http_file.py`, `fred_api.py`, `arcgis_feature_service.py`,
  `retrying.py`, and the loops + `run_file` param in `runner.py`, **plus** the keyword
  call-sites `f=None` in `tests/data_fetch/test_retrying.py` (lines ~46, ~116).
  Procedure per CLAUDE.md §20:
  1. `grep -rn 'f=' databricks_code/libs/data_fetch tests/data_fetch` → confirm the only
     keyword sites are the two in `test_retrying.py`.
  2. Rename in all 7 files in one change set (positional uses are local; the keyword uses
     must match).
  3. `grep -rn '\bf\b' …/data_fetch` → confirm no stray `f` as a `SourceFile`.
  4. *Verify:* full `pytest tests/data_fetch` (114 must stay green).

### Phase 2 — other libraries

- **2.1 `pipeline_logging.py` (`k` comp ~line153), `pipeline_utils.py` (`p` assign ~line77).**
  No direct unit tests. *Verify:* `py_compile` + `ruff` + `databricks bundle validate`.
  These run inside notebooks/Databricks, so a dev pipeline run in Phase 4 re-exercises them.
- **2.2 `wide_to_long/detect.py` (`f`×2), `validate.py` (`c`×2).** *Verify:* `pytest
  tests/wide_to_long` **iff** JDK 17 is installed (Step 0.1); otherwise `py_compile` +
  `ruff`, then rely on the `load_zillow_long` dev run. Renames are confined to
  comprehension bodies — low risk.

### Phase 3 — scripts

- **3.1 `scripts/download_local.py`** (`o` → `outcome`, `s` → `source`). *Verify:* live
  smoke `… download_local.py dl_zillow` (lands a file, prints summary).
- **3.2 `scripts/build_crosswalk.py`** — the densest file (~14, with `s` heavily
  overloaded). **Name per-site, no blanket replace.** Suggested: `_norm(s)` → `_norm(text)`;
  `sql()` `t`→`tmp_file`, `d`→`response_json`; `load_cbsa_master` `g`→`group`,
  comprehension `c`→`city`, `s`(state) → `state`; `match()` `z`→`zillow_row`; outer loop
  vars; `apply_overrides` `o`→`override_row`, `m`→`mask`. *Verify:* `py_compile` + `ruff`;
  if a warehouse is reachable, re-run and diff the produced crosswalk against the prior
  output (must be identical — this is a deterministic builder).

### Phase 4 — notebooks (one notebook per edit; batched dev-run verification per layer)

All notebook hits are **cell-local** loop/comprehension/lambda variables (header-validation
loops, silver select lists) — no cross-cell or cross-file coupling — so risk per notebook
is low. Edit one notebook per step (reviewable, revertible diff), run the §3 static cell
parser on each, then verify a whole layer with **one** dev pipeline run rather than 11
separate job runs.

- **4.1 setup:** `seed_dim_date.ipynb` (`n`), `seed_dim_geo.ipynb` (`w`). *Verify:* static
  parse; run the two seed notebooks on dev; confirm seed row counts unchanged.
- **4.2–4.5 bronze:** `load_zillow` (3), `load_fhfa` (5), `load_fred` (7), `load_realtor`
  (8) — one notebook per step. After all four are statically clean, run the **bronze dev
  job once**; confirm each `download_log` / `step_log` row and bronze table row counts
  match the documented baseline.
- **4.6–4.11 silver:** `load_silver_zillow` (3), `_fhfa` (5), `_fred` (1), `_realtor` (9),
  `_fema_hazard` (9), `_noaa_climate` (8) — one notebook per step. After all are
  statically clean, run the **silver dev job once**; confirm Silver conformance row counts
  against the deployment baseline (see memory: deployment_status).

> If a batched layer run fails, fall back to running the single notebook whose edit is
> suspect — the per-notebook commits make this a clean bisect.

### Phase 5 — Close-out

- Re-run `_dev_planning/scan_single_letter.py`; confirm the only residual hits are `e`
  handlers and out-of-scope files (tests/scratch). Paste the output into the final commit.
- Delete `_dev_planning/scan_single_letter.py` (a throwaway tool) or keep it under
  `scripts/` if we want a future lint — decide at close-out.
- Confirm CLAUDE.md §13 and the code now agree.

---

## 6. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Local Spark broken (JDK 17) → no local guardrail for `wide_to_long`/notebooks | Fix in Step 0.1, or accept static-parse + dev-run verification (documented per step). |
| Blanket `replace_all` renames a single letter that means different things | Per-site renaming only; explicit warning for `build_crosswalk.py` `s`. |
| Rename collides with / shadows an existing name in scope | `ruff`/`pyflakes` after each `.py` step; static cell parse for notebooks. |
| Notebook JSON corruption from hand-editing source arrays | Edit cell source strings only; re-validate with `databricks bundle validate` + the JSON/AST cell parser before any run. |
| Notebook dev runs are costly | Batch verification per layer (one bronze run, one silver run) after all notebooks in the layer pass the static gate. |
| Keyword-arg coupling missed on the provider rename | Step 1.3 greps `f=` before and `\bf\b` after; full test suite is the backstop. |

## 7. Suggested commit sequence

`0.2 docs` → `1.1` → `1.2` → `1.3` → `2.1` → `2.2` → `3.1` → `3.2` →
`4.1` → `4.2`…`4.5` (+ bronze run) → `4.6`…`4.11` (+ silver run) → `5 close-out`.

Stop and report after each phase; do not start Phase _n+1_ until phase _n_'s gate is green.
