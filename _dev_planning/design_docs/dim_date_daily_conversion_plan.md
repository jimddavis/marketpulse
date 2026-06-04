# Build Plan — Convert `dim_date` to Daily Grain (for Power BI Date Table)

**Status:** IMPLEMENTED + **dev-verified 2026-06-04** (gold_load green on `dev_marketpulse`; all checks below passed). Not yet committed.
**Date:** 2026-06-04
**Scope class:** §20 atomic cross-file migration of a deployed, conformance-verified table. Gated by a deploy + dev-run (§3.1) — not locally testable (no local Spark for notebook/DDL paths).

---

## 1. Problem

Power BI's **Mark as Date Table** requires the date column to be **contiguous and gap-free**, covering full calendar years. Our `dim_date` is **month-end grain** (one row per month: Jan 31, Feb 28, …), so PBI rejects it ("there cannot be any gaps in the date column"). Without a marked Date table we lose DAX time-intelligence: `TOTALYTD`, `TOTALMTD`, prior-year, `SAMEPERIODLASTYEAR`, `DATEADD`, rolling-12.

Report concepts that need those features (per `gold_reporting_research.md` §B/§C): **Concept 2 — Market Momentum** (Zillow YoY/MoM, rolling-12 — placed in DAX precisely because the data is contiguous monthly) and, optionally, Concept 4's prior-year affordability deltas. Concepts 1 and 3 do not need them.

## 2. Decision (resolved with user, 2026-06-04)

1. **Keep the name `dim_date`; change grain month-end → daily.** A daily calendar is a strict **superset** of the current month-end rows (same `date_key` = yyyymmdd convention). Every fact's existing `date_key` FK still resolves to exactly one (month-end / quarter-end) row. No new table, no FK changes. Rejected the separate-`dim_date_daily` option as redundant.
2. **Keep the `1947-01-01` start floor.** Do **not** truncate to 2000. Rationale below (§3, the FHFA trap). A daily calendar 1947-01-01→2031-12-31 is 31,046 rows — negligible for Spark and for a PBI marked Date table.
3. **Slicer usability is a report-layer concern, not a schema concern.** The "slider opens at 1947" annoyance is fixed per-report with a **visual-level filter on the slicer** (e.g. `Date[year] >= 2000`, or `>= 2016` on Realtor pages) or a **relative-date slicer** — never by truncating the shared dimension. This also lets each report pick its own floor (facts start at different dates: Zillow ~2000, Realtor 2016, FHFA 1975-Q3).

## 3. Coupling and risks discovered (the load-bearing part)

### 3.1 `dim_date` is also the FRED monthly spine — MUST filter to month-ends

`gold/build_fact_fred.ipynb` builds the national-monthly FRED fact's spine **directly from `dim_date`**, assuming one row per month:

```python
spine = (spark.table(DIM_DATE).select("date_key", F.col("full_date").alias("month_end"))
           .where((F.col("full_date") >= F.lit(bounds["lo"])) & (F.col("full_date") <= F.lit(bounds["hi"]))))
```

If `dim_date` goes daily and this is left unchanged, the spine goes **daily** → the FRED fact is built at daily grain (~30× rows), forward-filled per day.

**⚠ Silent-failure hazard:** the existing row-count assertion is `post_count != spine_count`. Both sides become the daily count, so **the assertion still passes** and the corruption is invisible to the gate. The fix is mandatory and must be verified by **inspecting the actual FRED row count** (expect ~monthly count, not daily), not by trusting the assert.

**Fix:** filter the spine to month-ends (the `is_month_end` column, which becomes genuinely meaningful at daily grain):

```python
spine = (spark.table(DIM_DATE).where(F.col("is_month_end"))
           .select("date_key", F.col("full_date").alias("month_end"))
           .where((F.col("full_date") >= F.lit(bounds["lo"])) & (F.col("full_date") <= F.lit(bounds["hi"]))))
```

### 3.2 The start floor is bound by the earliest FACT date_key — FHFA 1975-Q3

The floor is **not** set by what reports display, nor by CPI (1947). It is set by the earliest `date_key` of any fact that FKs `dim_date`. That is **FHFA: 1975-Q3 – 2026-Q1** (`silver_capability_snapshot.md:37`; FHFA all-transactions "back to 1975" per `fhfa_README.md:126`). The Silver FHFA load applies **no date floor**.

`gold/build_fact_fhfa.ipynb` hard-asserts on FK orphans:

```python
date_orphans = staged.join(spark.table(DIM_DATE).select("date_key"), "date_key", "left_anti").count()
if geo_orphans or date_orphans: raise AssertionError(...)
```

So a 2000-01-01 floor would orphan every FHFA quarter 1975-Q3…1999-Q4 → **FHFA Gold build fails**. Keeping `1947-01-01` (or at minimum `1975-07-01`) avoids this with zero benefit lost. We keep 1947 (simplest; FRED CPI history remains reachable; the Gold FRED fact self-clips to its data bounds regardless).

### 3.3 Unaffected consumers (verified by grep of `databricks_code/`)

- `gold/build_fact_fhfa.ipynb` joins `dim_date` on the **quarter-end** `date_key` for year/quarter labels — still maps to exactly one daily row. No change.
- `gold/build_fact_zillow.ipynb`, `gold/build_fact_realtor.ipynb` — carry `date_key` from Silver; do not read `dim_date`. No change.
- `gold/build_dim_date.ipynb` — carries `silver.dim_date` verbatim via `CARRY_COLS`; **no logic change**, just more rows.
- Fact FK orphan checks — daily is a superset of all month-/quarter-end keys → all still pass.

## 4. File-by-file change list

| # | File | Change |
|---|------|--------|
| 1 | `databricks_code/setup/seed_dim_date.ipynb` | `interval 1 month` → `interval 1 day`; drop the `last_day` wrap; compute `is_month_end`/`is_quarter_end` per-row; **`END` 12-01 → 12-31** (daily must end on a full-year boundary — `last_day` previously hid this; verified the old `END` dropped the 2031-12 month-end). Switch `MERGE` → `INSERT OVERWRITE`. |
| 2 | `databricks_code/gold/build_fact_fred.ipynb` | Add `.where(F.col("is_month_end"))` to the spine (§3.1). |
| 3 | `databricks_code/libs/ddl/silver_ddl.py` | Update `dim_date` COMMENTs: header (line ~11 "grain = day (period-end)"), `full_date` ("always a month-end" → "any calendar day"), `is_month_end` (drop "always true at this grain"). |
| 4 | `databricks_code/libs/ddl/gold_ddl.py` | Same COMMENT updates as #3 (header line ~12 + `dim_date` block lines ~102/108). |
| 5 | Docs / baselines | Update `dim_date` row-count references (`_dev_planning/silver_capability_snapshot.md` and the deployment-status baseline counts). Grep `dim_date` row counts before editing. |

### 4.1 Exact change — `seed_dim_date.ipynb` (cell 2)

**Before:**
```python
START = "1947-01-01"   # CPI series reaches back to 1947; covers every source
END   = "2031-12-01"

cal = spark.sql(
    f"SELECT explode(sequence(to_date('{START}'), to_date('{END}'), interval 1 month)) AS m"
)
dim = (
    cal.select(F.last_day("m").alias("full_date"))
    .select(
        ( ... date_key ... ),
        F.col("full_date"),
        F.year("full_date").alias("year"),
        F.quarter("full_date").alias("quarter"),
        F.month("full_date").alias("month"),
        F.trunc("full_date", "MM").alias("month_start"),
        F.trunc("full_date", "quarter").alias("quarter_start"),
        F.lit(True).alias("is_month_end"),
        F.month("full_date").isin(3, 6, 9, 12).alias("is_quarter_end"),
    )
)
```

**After** (daily grain; `is_month_end`/`is_quarter_end` computed, not literal):
```python
# Daily grain (one row per calendar day) so dim_date can be marked as a Power BI Date Table
# (mark-as-date-table requires a contiguous, gap-free date column). Floor stays 1947 — it must
# cover the earliest fact date_key (FHFA 1975-Q3), and CPI history reaches 1947; ~30.7k rows.
START = "1947-01-01"
END   = "2031-12-01"

cal = spark.sql(
    f"SELECT explode(sequence(to_date('{START}'), to_date('{END}'), interval 1 day)) AS full_date"
)
dim = cal.select(
    (F.year("full_date") * 10000 + F.month("full_date") * 100
     + F.dayofmonth("full_date")).cast("int").alias("date_key"),
    F.col("full_date"),
    F.year("full_date").alias("year"),
    F.quarter("full_date").alias("quarter"),
    F.month("full_date").alias("month"),
    F.trunc("full_date", "MM").alias("month_start"),
    F.trunc("full_date", "quarter").alias("quarter_start"),
    # is_month_end: this day is its month's last day. is_quarter_end: also a Mar/Jun/Sep/Dec end.
    (F.col("full_date") == F.last_day("full_date")).alias("is_month_end"),
    ((F.col("full_date") == F.last_day("full_date"))
     & F.month("full_date").isin(3, 6, 9, 12)).alias("is_quarter_end"),
)
```

**Write strategy: `INSERT OVERWRITE` (decided 2026-06-04).** Replaces the prior `MERGE` — a full rebuild is cleaner for a grain change and avoids any half-migrated mix of grains. Mirrors the `INSERT OVERWRITE ... SELECT *` pattern already used by `gold/build_dim_date.ipynb`; staging is built in DDL column order (incl. `inserted_ts`/`updated_ts`) so `SELECT *` lines up positionally.

## 5. Verification plan (the real gate — §3.1)

Static pre-checks (necessary, not sufficient): `databricks bundle validate --target user`; `nbformat` parse of both edited notebooks.

Then **deploy + dev run** and verify empirically:

1. **`dim_date` shape:** `count(*) = 31,046`; `count(*) WHERE is_month_end = 1,020` (identical to old monthly grain); `count(*) WHERE is_quarter_end = 340`; `MIN(full_date)=1947-01-01`, `MAX(full_date)=2031-12-31` (full years); no gaps: `count(*) == datediff(max,min)+1`. *(All five verified in a pure-Python calendar probe 2026-06-04 — engine-independent facts; Spark execution itself deferred to the dev run since no local Java 17.)*
2. **FHFA fact builds (no orphans):** `build_fact_fhfa` completes; row count unchanged (~63,334); `date_orphans = 0`.
3. **FRED fact stays MONTHLY (§3.1 hazard):** inspect `fact_fred_national_monthly` count — must equal the **month** count over the FRED range, **not** the daily count. Do not trust the row-count assert here. **Prod anchor: 953 rows** (`select count(*) from marketpulse.gold.fact_fred_national_monthly`, captured 2026-06-04). The dim_date change is row-count-neutral by construction (identical month-end set), so the count must not change. Dev will equal 953 **iff** dev's FRED observation date range matches prod's; a different dev number means a different data range, not a regression from this change.
4. **Zillow/Realtor facts:** row counts unchanged.
5. **Audit:** `pipeline_step_log` / `transform_detail_log` rows for the run all `succeeded`.
6. **PBI smoke (manual):** import `gold.dim_date`, **Mark as Date Table** on `full_date` (succeeds — was the original blocker), relate a fact on `date_key`, confirm a `SAMEPERIODLASTYEAR` measure returns values at month-grain axis.

**Commit only after the dev run is green** (§3.1). Branch off `main` first.

### Dev run results — 2026-06-04 (`dev_marketpulse`, target `user`)

`gold_load` TERMINATED SUCCESS; finalize `databricks_failures detected: 0`.

| Check | Result |
|---|---|
| `gold.dim_date` total / `is_month_end` / `is_quarter_end` | 31,046 / 1,020 / 340 |
| `gold.dim_date` range / contiguous | 1947-01-01 → 2031-12-31 / true |
| `silver.dim_date` (carried verbatim) | 31,046 |
| `fact_fhfa_metro_quarterly` (orphans) | 63,334 (0 — job assert passed) |
| `fact_fred_national_monthly` count / distinct date_key | **953 / 953** (= prod anchor) |
| FRED grain guard: rows on non-month-end days | **0** (range 1947-01-31 → 2026-05-31) |
| `fact_zillow_metro_monthly` / `fact_realtor_metro_monthly` | 271,444 / 110,085 |

Both flagged risks cleared: FHFA 1975+ quarter-ends resolve (no orphans); FRED stayed monthly (953, zero non-month-end rows — the §3.1 silent-daily-explosion did not occur).

## 6. Rollback

Revert the two notebooks + two DDL files and re-run `seed_dim_date` (MERGE re-converges; or `INSERT OVERWRITE` from the reverted monthly logic). `dim_date` returns to month-end grain; facts unaffected (their keys are a subset either way).

## 7. Out of scope

- Building the Power BI semantic model / reports (separate Power BI follow-on project — see memory `powerbi_followon_project`).
- Any change to fact grain, FK definitions, or other dims.
- Slicer configuration (report-layer, done in PBI per §2.3).

## 8. Authoritative references

- `_dev_planning/design_docs/gold_reporting_research.md` §B/§C — report concepts & Gold/DAX placement.
- `databricks_code/setup/seed_dim_date.ipynb` — the seed being changed.
- `databricks_code/gold/build_fact_fred.ipynb` — the FRED spine coupling (§3.1).
- `databricks_code/gold/build_fact_fhfa.ipynb` — the FK orphan assertion (§3.2).
- `databricks_code/libs/ddl/{silver,gold}_ddl.py` — `dim_date` DDL/COMMENTs.
- `_dev_planning/silver_capability_snapshot.md:37` — FHFA range 1975-Q3 – 2026-Q1.
