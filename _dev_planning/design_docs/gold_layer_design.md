# Gold layer design (star schema + thin Power BI serving seam)

**What this is.** The buildable, table-by-table specification for the marketpulse Gold layer. It is the
single source of truth for the later `/sc:implement` pass — that work drives from *this* doc, not from
chat memory (§21). No DDL/SQL/PySpark/DAX here; this is the design only.

**Grounded in (read alongside):**
- `_dev_planning/design_docs/gold_reporting_research.md` — the 4 report concepts, the GOLD-vs-DAX
  placement table (§C), the thin-PBI findings (§D/§E), and the **six resolved decisions**.
- `_dev_planning/silver_gold_column_name_mapping.md` — authoritative Gold column **names** + the
  `COMMENT = "Display Label: description"` text. This doc references it for names; it does **not** restate
  the full mapping. Any column NOT covered there is called out explicitly below.
- `_dev_planning/silver_capability_snapshot.md` — coverage/gap ground truth.
- `databricks_code/libs/ddl/silver_ddl.py` — the exact Silver schema Gold reads from.

---

## 0. Locked inputs (binding — do not reopen)

The six decisions from the research doc, plus the three star-schema answers (2026-06-01):

1. **Metro universe = sparse outer.** Housing stays at full coverage; FHFA appreciation is a sparse
   add-on (a metro absent from FHFA simply has no FHFA rows).
2. **Gold/DAX split = research §C as written.** Gold materializes: FHFA YoY, price-to-rent, gross-yield,
   affordability composite, CPI-real, FRED wide forward-filled strip, hazard banding. DAX keeps:
   Zillow/Realtor MoM-YoY, rolling averages, cross-metro rank/percentile, metro-vs-national spread.
3. **PK/FK declared on every Gold table** to drive Power BI auto-relationships.
4. **Realtor Sep–Nov 2022 break = document-only**, via COMMENT on the affected measures. No per-row flag.
5. **RESL polarity kept as is** (higher = more resilient); any composite must account for the inverted
   direction explicitly.
6. **Serving = plain Gold tables + thin PBI model**; UC Metric View optional/documented appendix only.
7. **(answer) Separate native-grain facts** — Gold mirrors Silver's fact set; no consolidated wide fact.
8. **(answer) 1:1 `dim_metro_profile`** holds the static hazard + climate attributes.
9. **(answer) Unit suffixes only where the source was cryptic** — realtor/zillow names unchanged.

---

## 1. Schema at a glance

A conformed-dimension **star** — separate native-grain facts sharing two date/geo dimensions, plus a 1:1
static profile dimension on the geo side.

```
                         gold.dim_date  (PK date_key)
                               │ date_key (FK)
   fact_zillow_metro_monthly ──┤
   fact_realtor_metro_monthly ─┤
   fact_fhfa_metro_quarterly ──┤
   fact_fred_national_monthly ─┘ (date only — national, no geo)
                               
                         gold.dim_geo   (PK geo_key)
                               │ geo_key (FK)
   fact_zillow / realtor / fhfa ──┤
                               └── gold.dim_metro_profile (PK/FK geo_key, 1:1 — static hazard+climate)
```

**Objects (8):** 3 dimensions (`dim_geo`, `dim_date`, `dim_metro_profile`) + 4 facts
(`fact_zillow_metro_monthly`, `fact_realtor_metro_monthly`, `fact_fhfa_metro_quarterly`,
`fact_fred_national_monthly`). `dim_fred_series` is **not** carried into Gold — see §2.1.

All objects land in the `gold` schema of each target catalog (`{CATALOG}.gold.*`), per the existing
bundle/catalog conventions. Three-part names everywhere.

---

## 2. Cross-cutting design decisions

### 2.1 Conformed dimensions are re-materialized as Gold tables (not views, not Silver references)

**Decision (recommended):** materialize `gold.dim_geo` and `gold.dim_date` as **tables** populated from
their Silver counterparts, carrying the **same key values**.

**Why tables, not views:** UC FK constraints (decision #3, the PBI auto-relationship driver) must
reference a PK on a **table**; a view cannot be an FK target. So the dims that facts point at must be
materialized tables with declared PKs.

**Why carry the same key values:** `geo_key` is `GENERATED ALWAYS AS IDENTITY` *in Silver*. Gold must
**not** re-generate it — a second identity column would mint new, non-matching keys and break every
fact's `geo_key` reference. Gold `dim_geo.geo_key` is therefore a plain `BIGINT NOT NULL` (PK, **not**
identity), populated by `INSERT … SELECT geo_key, …` from `silver.dim_geo`. `date_key` is already a
deterministic `INT` (not identity), so it carries forward trivially.

**`dim_fred_series` is dropped at Gold.** Once FRED pivots to the wide strip (§4.2), `series_id` stops
being a row key — the 10 series become 10 *columns*. The series metadata (label/units/frequency) moves
into those columns' COMMENTs. A series dimension with no fact to join is dead weight, so Gold omits it.

*Open item (graded §6):* whether to refine `dim_geo` on the way into Gold (e.g. apply the optional
`_pct`-style suffixes — no, per decision #9) or carry it verbatim. Default: **carry verbatim** + add no
new columns; `dim_metro_profile` holds the new static enrichment.

### 2.2 Write strategy — full rebuild (overwrite) for every Gold table

Gold is a **deterministic projection of Silver**, rebuilt wholesale each run; there are no row-level
late-arriving updates *at Gold* and no incremental consumers (Power BI re-imports the whole table). So
every Gold table uses **overwrite-rebuild** (truncate-and-reload semantics), not MERGE.

- Rationale vs CLAUDE.md §11.2: MERGE earns its place when a target has active row-level consumers or
  costly recompute. Ours are ≤ ~271K rows and fully derivable from Silver — a full rebuild is simpler,
  idempotent, and removes a class of merge-key bugs. (Documented per §11.2's "declare the strategy.")
- **Row-count validation (§11.5) adapts to overwrite:** assert `post_count == expected`, where `expected`
  is the driving Silver row count (for 1:1 projections) or a known transform cardinality (e.g. the FRED
  wide strip = one row per month in the spine). Not the append-delta form.

### 2.3 Surrogate keys

Facts keep their **composite natural PK** `(geo_key, date_key)` — the grain. No single-column identity
surrogate is added (none is needed; nothing references a fact by a surrogate). `dim_metro_profile` is 1:1
with `dim_geo`, so its PK **is** `geo_key` (also the FK to `dim_geo`) — no own identity. This means the
only `GENERATED ALWAYS AS IDENTITY` column in the lineage stays upstream in Silver `dim_geo`; Gold
inherits its values. (Consistent with CLAUDE.md's "never `monotonically_increasing_id`" — we reuse a
real, stable upstream key rather than minting one.)

### 2.4 Audit columns

Every Gold table carries `inserted_ts` + `updated_ts` via `F.current_timestamp()` (CLAUDE.md §11.3). No
`run_id`/`source_file_path` at Gold (those are Bronze-lineage columns).

---

## 3. Table-by-table specification

Column **names + COMMENT text** come from `silver_gold_column_name_mapping.md` unless flagged "(new
here)". Types match the Silver source unless a derivation changes them.

### 3.1 `gold.dim_geo` (dimension)
- **Grain:** CBSA. **Source:** `silver.dim_geo` (verbatim carry).
- **Key:** `geo_key BIGINT NOT NULL` plain (not identity) — **PK**.
- **Columns:** carried verbatim (cbsa_code, cbsa_title, cbsa_type, zillow_region_id, primary_state,
  state_list, household_rank, census_region, cbsa_population) + audit.
- **Constraints:** `PK(geo_key)`.
- **Write:** overwrite from Silver; `expected = 935`.

### 3.2 `gold.dim_date` (dimension)
- **Grain:** day (month-end). **Source:** `silver.dim_date` (verbatim carry).
- **Key:** `date_key INT NOT NULL` — **PK**.
- **Columns:** carried verbatim (full_date, year, quarter, month, month_start, quarter_start,
  is_month_end, is_quarter_end) + audit.
- **Constraints:** `PK(date_key)`.
- **Write:** overwrite; `expected = 1,020` (current dim_date row count — verify at build).

### 3.3 `gold.dim_metro_profile` (dimension — 1:1 static enrichment) **(new table)**
- **Grain:** CBSA, static (no date). **Source:** `silver.fact_fema_hazard_cbsa` (15 cols) +
  `silver.fact_noaa_climate_cbsa` (13 cols), joined on `geo_key`.
- **Key:** `geo_key BIGINT NOT NULL` — **PK** and **FK → dim_geo**.
- **Columns:** all hazard + climate measures, **renamed + COMMENTed per mapping doc §5/§6**
  (e.g. `eal_valt → expected_annual_loss_usd`, `risk_score → overall_risk_score`,
  `resl_score → community_resilience_score` [RESL polarity note in COMMENT, decision #5],
  `ann_tavg_normal → avg_annual_temp_f`, … 28 measure columns total) + audit.
- **Retain for region rollup (do NOT trim):** `expected_annual_loss_usd` and `population` are the
  **additive base** the deferred region/state risk rollup reads from (see
  `geographic_risk_aggregation_design.md` §3/§8). They must stay on this table even though no v1 report
  consumes them directly — dropping them as "unused" would turn the ~0-cost v1.5 rollup into a DDL
  migration + reload.
- **Coverage note:** hazard ≈ 935 (10 PR null on scores), climate = 924. The join is **outer on
  geo_key** so a metro missing one source still gets a profile row with NULLs on the absent side (honest
  coverage; do not inner-join the two static sources down to their intersection).
- **Constraints:** `PK(geo_key)`, `FK(geo_key) → dim_geo(geo_key)`.
- **Write:** overwrite; `expected ≈ 935` (the union of the two sources' geo_keys — verify).
- **(Optional, decision #2 — hazard banding):** a `overall_risk_band` quartile column (static, canonical,
  no slicer dependence) MAY be materialized here. Flagged optional in §5.4; include only if the
  implementation phase confirms the banding rule.

### 3.4 `gold.fact_zillow_metro_monthly` (fact)
- **Grain:** CBSA × month. **Source:** `silver.fact_zillow_metro_monthly` (already well-named).
- **Keys/constraints:** `PK(geo_key, date_key)`, `FK geo_key→dim_geo`, `FK date_key→dim_date`.
- **Columns:** `typical_home_value`, `typical_rent`, `inventory_active` carried verbatim + Gold-derived
  ratios (§5.3): `price_to_rent_ratio`, `gross_rental_yield_pct`. + audit.
- **Write:** overwrite; `expected = 271,444` (verify).

### 3.5 `gold.fact_realtor_metro_monthly` (fact)
- **Grain:** CBSA × month. **Source:** `silver.fact_realtor_metro_monthly` (already well-named).
- **Keys/constraints:** `PK(geo_key, date_key)`, FKs to dim_geo + dim_date.
- **Columns:** the 15 base metrics carried verbatim. **Decision #4:** append the Sep–Nov 2022
  methodology-break note to the COMMENT of the affected measures (inventory/time-on-market family:
  `active_listing_count`, `median_days_on_market`, `new_listing_count`, `pending_listing_count`,
  `pending_ratio`, the price-change share/count columns). No per-row flag. + audit.
- **Write:** overwrite; `expected = 109,160` (verify).

### 3.6 `gold.fact_fhfa_metro_quarterly` (fact)
- **Grain:** CBSA × quarter. **Source:** `silver.fact_fhfa_hpi_metro_quarterly`.
- **Keys/constraints:** `PK(geo_key, date_key)`, FKs to dim_geo + dim_date.
- **Columns:** `home_price_index` (renamed from `index_nsa`), `home_price_index_std_error` (from
  `standard_error`), + **derived `home_price_index_pct_change_yoy`** (§5.1). + audit.
- **Sparse-outer (decision #1):** this fact exists only for the 373 FHFA metros. Because facts are
  separate (answer #7), sparseness is **structural** — non-FHFA metros simply have no row here, which is
  cleaner than NULL-padding a consolidated fact. Downstream "all metros" views left-join from a housing
  fact to this one; FHFA columns read NULL where absent.
- **Write:** overwrite; `expected = 63,334` (verify).

### 3.7 `gold.fact_fred_national_monthly` (fact — wide, forward-filled)
- **Grain:** month (national; **no geo**). **Source:** `silver.fact_fred_series` (long) → wide (§4.2).
- **Key/constraints:** `PK(date_key)`, `FK date_key→dim_date`. No geo FK (national).
- **Columns:** the 10 series as 10 columns, **named + COMMENTed per mapping doc §2**
  (`mortgage_rate_30yr_pct`, `mortgage_rate_15yr_pct`, `housing_affordability_index`,
  `median_sales_price_usd`, `unemployment_rate_pct`, `real_median_household_income_usd`,
  `active_listing_count`, `case_shiller_hpi_sa`, `case_shiller_hpi_nsa`, `cpi_all_urban_sa`) +
  **derived CPI-real series** (§5.2) where applicable + audit.
- **Write:** overwrite; `expected =` one row per month in the spine (verify the spine bounds).

---

## 4. Grain-reconciliation seams (the hard parts)

### 4.1 The three native cadences coexist without a forced common grain
Because facts stay separate (answer #7), Gold does **not** upsample FHFA quarterly → monthly or downsample
anything. Each fact keeps its honest cadence; `dim_date` (which carries both month-end and quarter-end
rows, with `is_quarter_end`) is the shared spine. Power BI/DAX reconcile cadences at query time. This is
the chief benefit of the separate-fact choice and a deliberate modeling statement.

### 4.2 FRED long → wide, forward-filled (decision #2)
- **Transform:** pivot `silver.fact_fred_series` from long `(series_id, observation_date, value)` to a
  monthly wide strip — one column per `series_id`, one row per month-end on a monthly date spine.
- **Forward-fill** each series across the monthly spine: a month with no native observation carries the
  last known value (weekly→monthly downsample to month-end; quarterly/annual series hold their value
  across intervening months). This is what makes a single monthly national strip joinable to the metro
  facts on `date_key`.
- **Why forward-fill is correct for the 2025-10 gap:** `CPIAUCSL` and `UNRATE` each miss 2025-10 (a
  source-side BLS release gap — Verified absent, Projected cause). Forward-fill carries Sept 2025 into the
  Oct slot, the right behavior for a genuinely-unpublished month — *not* a NULL or zero. No special-casing
  beyond the standard forward-fill rule. (Contrast FHFA YoY, §5.1, where a gap *must* be handled.)
- **Rounding:** dollar series (`median_sales_price_usd`, `real_median_household_income_usd`) round to the
  serving precision at Gold (Silver keeps cents) per the mapping-doc note.

### 4.3 Realtor methodology break (decision #4)
Document-only. The affected `fact_realtor_metro_monthly` measure COMMENTs gain a sentence: *"Realtor.com
re-based this metric in Sep–Nov 2022; values before and after are not directly comparable — flag in
multi-year trends."* No `realtor_methodology_era` column. (Break Verified — FRED series notes,
e.g. `MEDDAYONMARUS`.)

---

## 5. Gold-materialized derivations (the §C "GOLD" rows)

### 5.1 FHFA `home_price_index_pct_change_yoy` — date-aware self-join (NOT positional LAG)
- **Definition:** per `geo_key`, `(index_q − index_{same quarter, prior year}) / index_{prior year} × 100`.
- **Mechanism:** self-join the FHFA fact to itself on `geo_key` AND the **prior-year same quarter**,
  resolved through `dim_date` (current row's `year−1`, same `quarter`). A missing prior-year quarter
  yields **NULL** (correct) — never a wrong value.
- **Why not `LAG(index, 4)`:** "4 rows back" equals "4 quarters back" only on a contiguous series; across
  a gap it silently returns the wrong quarter. 42 metros / 132 quarters have gaps (93% pre-1985), so the
  positional form *would* corrupt some values.
- **Build-time no-gap assertion:** per `geo_key`, assert `row_count == MAX(quarter_ordinal) −
  MIN(quarter_ordinal) + 1` (ordinal = `year*4 + quarter`); log/investigate any metro that fails. (The
  derivation tolerates gaps via the date-aware join; the assertion *surfaces* them rather than hiding
  them.) Reuse/extend `databricks_code/utilities/silver_row_counts.sql`'s no-gap section.
- **YoY not QoQ** — source is NSA; same-quarter-prior-year cancels seasonality without modeling it.

### 5.2 CPI-real (deflated) series — cross-source, canonical
Nominal dollar series deflated by `cpi_all_urban_sa` to a base period (`real = nominal ÷ CPI × CPI_base`).
Materialized in `fact_fred_national_monthly` (national) and reusable as a deflator broadcast to metro
facts in the affordability composite (§5.3). Canonical, expensive to redo per report → Gold.

### 5.3 Ratios & affordability composite
- **`price_to_rent_ratio`** = `typical_home_value ÷ (typical_rent × 12)` — row-level, on the Zillow fact.
- **`gross_rental_yield_pct`** = `(typical_rent × 12) ÷ typical_home_value × 100` — same fact.
- **Affordability composite / payment proxy** = metro `typical_home_value` × national
  `mortgage_rate_30yr_pct` (broadcast on `date_key`). **Cross-source**, canonical, expensive → Gold.
  *Placement question (graded §6):* lives most naturally as a derived column on the Zillow fact (metro
  grain) with the national rate joined in at build time, OR as a small dedicated `fact_affordability`
  bridge. Default recommendation: **derive onto the Zillow fact** to keep the star lean; revisit if it
  needs Realtor inputs too.

### 5.4 Hazard banding (optional) — see the dedicated risk-aggregation design
`overall_risk_band` on `dim_metro_profile` — static, no slicer dependence, canonical: a categorical risk
rating that serves as a Power BI slicer / legend / grouping attribute (which a raw score cannot be).

**The banding rule, the two-column shape (label + ordinal sort key), the no-rating bucket, the RESL
polarity caveat, and the score-vs-rating aggregation reasoning are specified in
`_dev_planning/design_docs/geographic_risk_aggregation_design.md` — read it before building this.** That
doc's banding rule is now **resolved (Verified against FEMA NRI Tech Doc, Mar 2023):** FEMA uses k-means
for Risk/EAL and fixed quintiles for SoVI/Resilience, with no official threshold to apply at CBSA grain —
so the band is **fixed quintiles on the CBSA score**, COMMENTed as a CBSA-relative, non-official
approximation. No longer blocked; still optional for v1 (a clean column-add) — include if the hero page
wants categorical risk.

---

## 6. Thin-PBI seam contract (decision #6)

What Gold must guarantee so the high-signal screenshots (research §D #1/#2) come near-free:
1. **COMMENT on every Gold column** = the mapping-doc "Display Label: description" text. (Verified the
   Databricks→PBI connector copies UC column COMMENTs into PBI column descriptions — research §E.)
2. **PK + FK declared on every Gold table** (decision #3). The connector preserves UC FKs as PBI model
   relationships → the model-view diagram auto-builds (research §E, Verified). **One-active-path note:**
   each fact has exactly one geo FK and one date FK (single path), so no inactive-relationship ambiguity.
   `dim_metro_profile → dim_geo` is a 1:1 snowflake extension on the geo side — relate profile to dim_geo
   only (not directly to facts) to avoid a second fact→geo path.
3. **Names final** (this doc + mapping doc) — no renames after PBI binds.

**UC Metric View = optional appendix only.** Do not build it into the spine. If pursued post-core, gate
on a probe that the PBI connector consumes the `MEASURE()` syntax on this edition (research §E flagged it
likely needs Tabular Editor's "Semantic Bridge" — Projected). Otherwise keep as a documented "evaluated"
note. **Never load-bearing.**

---

## 7. Phased, parallelizable implementation plan

Mirrors how the Silver/weather phases were staged (DDL → loaders → assertions → job wiring).

**Phase G0 — `gold_ddl.py` (foundation, blocks everything).** Replace the stub: `create_gold_tables`
following the `silver_ddl.py` shape (`_run_ddl`, `_ok/_fail`, `CREATE TABLE IF NOT EXISTS`, declared
PK + **FK** constraints). All 8 objects. *Dependency: none. One workstream.*

**Phase G1 — dimension builds (parallel after G0):**
- G1a `dim_geo` carry-forward (verbatim from Silver, same keys).
- G1b `dim_date` carry-forward.
- G1c `dim_metro_profile` (outer-join hazard+climate, rename per mapping doc, optional banding).
*All three independent; depend only on G0.*

**Phase G2 — fact builds (parallel after G1; facts FK the dims):**
- G2a `fact_zillow_metro_monthly` (+ price_to_rent, gross_yield).
- G2b `fact_realtor_metro_monthly` (+ break-note COMMENTs).
- G2c `fact_fhfa_metro_quarterly` (+ YoY self-join + no-gap assertion).
- G2d `fact_fred_national_monthly` (long→wide forward-fill + CPI-real).
*Independent of each other; each depends on G1a/G1b (dims must exist for FK + build joins).*

**Phase G3 — assertions & validation.** Row-count assertions per §2.2; FHFA no-gap assertion (§5.1);
spot-check sparse-outer NULL behavior on a non-FHFA metro. *Depends on G2.*

**Phase G4 — orchestrator/job wiring.** Add the Gold phase to the bundle job(s) following the existing
silver/weather job pattern; `run_if` per CLAUDE.md (data tasks `ALL_SUCCESS`, any cleanup `ALL_DONE`).
*Depends on G3.*

**Phase G5 — PBI-seam verification (cheap probe).** After deploy, confirm the connector carries COMMENTs
+ FKs as §6 claims. *Depends on G4; gates the optional Metric View.*

Critical path: **G0 → G1 → G2 → G3 → G4 → G5**; G1*/G2* fan out within their phases for multi-tasking.

---

## 8. Open questions — verify before implementing (graded)

| # | Question | Grade | Cheap probe |
|---|---|---|---|
| 1 | UC **FK** informational constraints — exact syntax + support on this edition's Delta/UC (Silver uses PK + identity already = Verified; FK is **new** to this repo). | **Verified** (docs.databricks.com/.../tables/constraints, confirmed 2026-06-01) | **Resolved — no probe needed.** UC + Delta support PK/FK, informational-only/not-enforced; GA in DBR 15.2+ (we run 17.3 LTS), no tier/edition limit (Free Edition fine). FK on existing table: `ALTER TABLE S ADD CONSTRAINT fk FOREIGN KEY(col) REFERENCES T` — `REFERENCES T` targets T's PK; our FKs target dim_geo(geo_key)/dim_date(date_key), which ARE the PKs. PK cols must be NOT NULL (design already declares this). `RELY` is **optional** — it only flags optimizer trust; PBI relationship discovery reads UC metadata, not the optimizer hint, so omit it. |
| 2 | Databricks→PBI connector actually carries UC **COMMENTs → descriptions** and **FKs → relationships** on the *free* connector path. | **Verified (per research §E)** | Confirm on the real connect once a Gold table exists (G5). |
| 3 | Conformed-dim **re-exposure as Gold tables with carried key values** (§2.1) — confirm `INSERT … SELECT geo_key` preserves keys and that a plain (non-identity) BIGINT PK is accepted. | **Projected** | Build `gold.dim_geo` from `silver.dim_geo`; assert key set identical (anti-join count = 0). |
| 4 | **Affordability composite placement** (§5.3) — derived column on Zillow fact vs dedicated bridge. | **Projected** | Design call; resolve at G2a once the exact inputs are fixed. |
| 5 | UC **Metric View → PBI `MEASURE()`** friction — only if the optional appendix (§6) is pursued. | **Projected** | Defer; probe only if/when the appendix is taken up. |
| 6 | Exact current `dim_date` / `dim_geo` row counts for the §2.2 `expected` assertions. | **Verified-able** | `SELECT COUNT(*)` at build time; bake the asserted constants from the live count. |

---

## 9. Scope boundaries (non-goals of this design and the build it specifies)

- **No** consolidated wide metro-month fact (answer #7); facts stay separate.
- **No** dataset expansion. **Months-of-supply (true)** and **sale-to-list ratio** remain
  **NEEDS-NEW-DATA** — out of scope; listing-flow proxies are *not* the same metric and are not built.
- **No** Power BI `.pbip`/TMDL artifacts designed or built here — only the Gold-side seam contract (§6).
- **No** code in this doc — `gold_ddl.py` and the build transforms are the `/sc:implement` deliverable.
- The six decisions (§0) are **not** reopened.
```
