/sc:implement Gold Phase G0 — `gold_ddl.py` (the 8-object star-schema DDL), against the approved design.

THE SPECIFICATION IS NORMATIVE
- The spec is `_dev_planning/design_docs/gold_layer_design.md`. Read it in full before writing anything,
  especially **§2 (cross-cutting decisions), §3 (table-by-table spec), §7 (phasing — you are building
  G0 ONLY)**.
- Column **names and COMMENT text** are owned by `_dev_planning/silver_gold_column_name_mapping.md`
  (each Gold COMMENT = verbatim the doc's "Display Label: description"). Do not invent names or comments;
  copy them. For columns carried verbatim from Silver (dim_geo, dim_date, zillow, realtor), carry the
  Silver COMMENTs.
- Risk-band specifics, if ever built, live in `geographic_risk_aggregation_design.md` — but the band is
  **out of scope for G0** (see SCOPE GATE).
- This prompt governs *how* you implement; it does not restate the design. Where this prompt and the spec
  disagree on technical content, the spec governs; on scope/sequencing, this prompt governs.

READ-FIRST (before writing a single line — pin the pattern, do not infer it)
- `databricks_code/libs/ddl/silver_ddl.py` — **the analog you mirror exactly**: the
  `create_*_tables(spark, schema)` shape, the `(table_name, ddl_sql)` statements list, the
  `_run_ddl(spark, statements)` call, the `_ok`/`_fail` returns, the inline `CONSTRAINT pk_… PRIMARY KEY`
  style, the `CREATE TABLE IF NOT EXISTS` idempotency, and the `_migrate_*` ALTER pattern.
- `databricks_code/libs/ddl/gold_ddl.py` — the current STUB you replace.
- `databricks_code/libs/ddl/_utils.py` — `_run_ddl` / `_ok` / `_fail` contract.
- `databricks_code/libs/ddl/audit_ddl.py` / `bronze_ddl.py` — secondary examples of the same shape.
- **Where `create_silver_tables` is invoked** (the setup/catalog path) — find it; G0 wires
  `create_gold_tables` into the same place, identically. If you can't find an unambiguous call site, ASK.

BEHAVIORAL RULES (from .claude/CLAUDE.md — non-negotiable)
- **Safety Protocol (§3):** produce a numbered plan and STOP for approval before writing code. After
  approval, execute only the approved steps, summarize, and stop again.
- **Pause on ambiguity.** If a decision is missing or unclear, ASK — do not fill gaps with assumptions.
- **Confidence-grade** every Databricks-specific claim (Verified / Projected / Guessing). Ship nothing
  graded Guessing without a WebFetch or probe first.
- **Match existing patterns (§5);** do not normalize a minority pattern to the majority silently.
- **Centralize load-bearing values (§6):** no hardcoded catalog/schema strings; the schema arrives as the
  `gold_schema` parameter exactly as `silver_schema` does in `silver_ddl.py`.

ANTI-DRIFT — HARD CONSTRAINTS (these are the traps for THIS phase; treat as DO-NOT)
1. **No `GENERATED ALWAYS AS IDENTITY` anywhere in Gold.** `geo_key` is a plain `BIGINT NOT NULL` (PK,
   not identity) — Gold *carries* Silver's key values; a regenerated identity would mint non-matching
   keys. (spec §2.1, §2.3) `date_key` is plain `INT NOT NULL` (already non-identity in Silver).
2. **PK + FK declared on every table** (spec §2.1, §3). FK informational constraints on UC are
   **Verified** (docs.databricks.com/.../tables/constraints; informational-only, GA in DBR 15.2+, no
   edition limit; we run 17.3 LTS). `REFERENCES T` targets T's PK. **Omit `RELY`** — it's an optimizer
   hint, irrelevant to PBI relationship discovery (spec §8 open-Q #1).
3. **Parent-before-child ordering / FK wiring:** a FK needs its parent PK to already exist. Decide and
   state in the plan whether to (a) order the `statements` list dims-before-facts with **inline** FK in
   `CREATE TABLE`, or (b) create all 7 tables (PK inline) then add FKs in a **second ALTER pass** (the
   safer, ordering-independent option, mirroring `_migrate_dim_geo`). Inline FK-in-CREATE on UC is
   **Projected** — if you choose (a), verify it; (b) is Verified.
4. **7 objects only, per spec §3:** dims `dim_geo`, `dim_date`, `dim_metro_environment`; facts
   `fact_zillow_metro_monthly`, `fact_realtor_metro_monthly`, `fact_fhfa_metro_quarterly`,
   `fact_fred_national_monthly`. **`dim_fred_series` is NOT created in Gold** (spec §2.1) — FRED pivots
   wide, series become columns.
5. **`dim_metro_environment` MUST include `expected_annual_loss_usd` + `population`** — the additive base for
   the deferred region rollup, flagged "do not trim" (spec §3.3). Do not omit them as "unused."
6. **Declare the derived columns in the DDL even though G0 doesn't populate them:**
   `home_price_index_pct_change_yoy` (fhfa), `price_to_rent_ratio` + `gross_rental_yield_pct` (zillow),
   and any CPI-real columns on the FRED fact (spec §3.4/§3.6/§3.7, §5). They are nullable at G0; G2 fills
   them. Use the types the derivations imply.
7. **Every table carries `inserted_ts` + `updated_ts` (TIMESTAMP)** audit columns (spec §2.4). No
   `run_id`/`source_file_path` at Gold.
8. **`fact_fred_national_monthly` has a single-column PK `(date_key)` and a date FK only — no geo FK**
   (national). The 10 series are wide columns named per mapping-doc §2 (spec §3.7).
9. **Match column types to the design/mapping** (e.g. ratios `DOUBLE`/`DECIMAL` per the derivation,
   scores `DOUBLE`, dollar columns as in Silver). When a derived column's type isn't pinned in the spec,
   choose and state it in the plan.

PARKED — DO NOT TOUCH
- **The optional CBSA risk band** (`overall_risk_band` + sort key) is NOT part of G0. It's a clean
  column-add later, and only if the owner pulls it into v1. If you think it belongs now, NAME IT and move
  on — do not add it. (spec §5.4; `geographic_risk_aggregation_design.md` §4)
- **Region rollup** (`region_risk_profile`, EAL-per-capita, any re-percentiling) is v1.5 — out of scope.
- **No build transforms, no notebooks, no job/orchestrator wiring, no data population.** G0 creates empty
  tables only. G1 (dim builds) and G2 (fact builds) are later phases — do not start them.
- **Do not modify Silver, Bronze, or audit DDL**, or any existing table. G0 only replaces the
  `gold_ddl.py` stub (+ the one setup call-site wiring per READ-FIRST).

SCOPE GATE
- Implement **G0 ONLY**: replace the `gold_ddl.py` stub with `create_gold_tables(spark, gold_schema)`
  that creates all 7 objects (idempotent, `CREATE TABLE IF NOT EXISTS`, PK+FK constraints, full column
  COMMENTs), plus wiring it into the existing setup path that calls `create_silver_tables`.
- After G0 is approved and committed, STOP and await direction before G1.

VALIDATION / TESTING NOTE
- Local pyspark lacks Unity Catalog, so three-part names + PK/FK constraints likely won't fully exercise
  locally. State how `silver_ddl` is validated/tested today and mirror it. The authoritative check is
  running `create_gold_tables` on **dev** and confirming via `DESCRIBE`/Catalog Explorer that all 7
  tables, their COMMENTs, and the PK/FK constraints registered. Grade any local-vs-Databricks behavior
  claim explicitly.

DELIVERABLE FOR THIS PASS
A numbered implementation plan for G0 — the exact 7 `CREATE TABLE` definitions (columns, types, COMMENT
source, PK/FK), the FK-wiring approach chosen (inline vs ALTER pass, §3 above) with its confidence grade,
the setup call-site wiring, and the validation step — then STOP for approval. No code until approved.
