# Gold reporting research (pre-Gold)

**What this is.** Research input for the Gold layer + a thin Power BI serving layer. Audience for the
*finished* work = a hiring manager assessing data-engineering / analytics-engineering skill. Optimized
for **demonstrated modeling judgment**, not dashboard polish. Feeds a later `/sc:design`; it does **not**
design DDL or write code (per `/sc:research` boundary).

**Grounded in:** `silver_capability_snapshot.md` (data ground truth), `silver_gold_column_name_mapping.md`
(naming + COMMENT convention + already-decided derivations), `silver_ddl.py` (schema), project CLAUDE.md.
External claims carry a confidence grade (§E); sources listed at the end.

---

## Executive summary

- **One philosophy decision drives everything:** rich, governed **Gold** + a **thin** Power BI semantic
  model. Most time-intelligence belongs in **DAX measures** (slicer-responsive, free to store); reserve
  **Gold columns** for expensive, canonical, or cross-source derivations. The *documented split* is the
  artifact that signals seniority — not the column count.
- **Two verified platform findings reduce your UI work and validate prior decisions:**
  1. The Databricks→Power BI connector **copies a table's column COMMENTs into Power BI column
     descriptions** — so the `silver_gold_column_name_mapping.md` "Display Label: description" COMMENT
     work pays off automatically downstream. *(Verified.)*
  2. It **preserves UC foreign-key relationships as Power BI model relationships** — so a Gold star
     schema with declared PK/FK constraints **auto-builds the model-view diagram**, your highest-signal
     / lowest-effort screenshot. *(Verified.)*
- **Differentiator:** the **hazard × climate × housing** join is the concept almost no Zillow-data
  portfolio has. Make it the hero.
- **Two honest boundaries to state up front, not paper over:** you have **no closed-sale data**, so true
  **months-of-supply** and **sale-to-list ratio** (the two canonical "market health" metrics) are
  **not derivable** — only listing-flow proxies. Saying so is itself a maturity signal.

---

## Boundaries (restated from the capability snapshot — bind every recommendation)

- **FHFA covers only 373 metros** (Zillow 859, Realtor/hazard ~935, climate 924) — the cross-source
  bottleneck. Any "all sources" view must choose inner-join (~373) vs sparse outer.
- **No actual per-metro sale price** (Zillow = modeled value, Realtor = *asking*, FHFA = *index*; only
  national `MSPUS` is a real sale price).
- **Macro (FRED) is national only**; **hazard & climate are static, single-vintage** (can't trend).
- **Realtor methodology break (Oct 2022):** Realtor.com re-based its inventory/time-on-market metrics in
  Sep–Nov 2022; data before/after is **not directly comparable**. Our realtor fact starts 2016, so it
  **straddles the break** — flag in any long-run realtor trend. *(Verified — Realtor.com.)*

---

## A. Real-estate reporting conventions, mapped onto our columns

| Industry-standard metric | Convention (source) | Our column / derivation | Feasible? |
|---|---|---|---|
| Typical home value (not median sale) | ZHVI = 35th–65th pct typical value; explicitly preferred over median sale price for stability | `typical_home_value` (already ZHVI) | ✅ have it |
| Typical rent | ZORI = repeat-rent, 40th–60th pct, stock-weighted | `typical_rent` (already ZORI) | ✅ have it |
| Home-price appreciation | YoY / since-base index | FHFA `index_nsa` → YoY; Zillow value → YoY | ✅ derivable |
| Median days on market | list→close/pending/off-market | `median_days_on_market` (Realtor) | ✅ have it |
| **Months of supply** | inventory ÷ **closed sales** (4–5 = balanced) (Redfin) | we lack closed sales | ⚠️ **proxy only** |
| **Sale-to-list ratio** | sale price ÷ list price (Redfin) | we lack sale price | ❌ **not derivable** |
| Price cuts / reductions | share of active listings reduced | `price_reduced_share` (Realtor) | ✅ have it |
| Market velocity | pending ÷ active | `pending_ratio` (Realtor) | ✅ have it |
| Price-to-rent ratio | value ÷ annualized rent | `typical_home_value` ÷ (`typical_rent`×12) | ✅ derivable |
| Affordability | payment vs income / rate-sensitive | metro price × national `MORTGAGE30US`; `FIXHAI` | ✅ derivable (cross-source) |

**Takeaway:** our housing coverage maps cleanly onto the *stock/level* and *listing-flow* conventions;
it does **not** support the two *transaction* conventions (months-of-supply, sale-to-list) because those
need closed-sale counts. The standard fix is to lead with the metrics we *do* have (value, rent, DOM,
price cuts, pending ratio) and be explicit about the transaction-data gap.

---

## B. Report concepts (4, spanning 3 notional personas)

### Concept 1 — Climate-Risk-Adjusted Metro Profile  *(HERO; persona: risk-aware buyer/relocator)*
- **Question:** *Which appreciating, affordable metros also carry low hazard & climate risk?*
- **Why it impresses a DE reviewer:** integrates **five heterogeneous sources** (Zillow, FHFA, FEMA NRI,
  NOAA Normals, FRED) on a conformed `geo_key` — the multi-source-join + static-enrichment pattern is the
  whole job. It's also a question the mainstream dashboards *can't* answer.
- **Columns:** `typical_home_value` + appreciation, affordability composite, `risk_score` + per-hazard
  scores, climate normals (`ann_tavg_normal`, `ann_snow_normal`, degree-days).
- **Feasibility:** broad on Zillow's 859 (+ static hazard/climate, ~all). Add FHFA appreciation only if
  you accept the 373-metro narrowing for that measure.

### Concept 2 — Metro Market Momentum & Heat  *(persona: investor / market analyst)*
- **Question:** *Which metros are heating or cooling right now?*
- **Why it impresses:** clean time-intelligence (YoY/MoM, rolling) + cross-metro **ranking** — the
  textbook case for *where* logic lives (DAX rank vs Gold growth). Good vehicle to show the split.
- **Columns:** Zillow value/rent YoY, `median_days_on_market`, `pending_ratio`, `price_reduced_share`,
  `inventory_active`/`active_listing_count` direction.
- **Feasibility:** ✅ 859/935, monthly, **fully contiguous** (gap check passed) — so DAX time-intelligence
  is safe here.

### Concept 3 — Rent-vs-Own / Gross Yield  *(persona: investor)*
- **Question:** *Where does the math favor renting vs buying, and where are gross rental yields highest?*
- **Why it impresses:** a canonical cross-column ratio reused across views — a tidy "define once in Gold"
  example.
- **Columns:** `typical_home_value`, `typical_rent` → price-to-rent, gross-yield proxy.
- **Feasibility:** ✅ Zillow 859 (both columns same fact).

### Concept 4 — Affordability Watch  *(persona: relocation / affordability)*
- **Question:** *How has buying affordability shifted as mortgage rates and incomes moved?*
- **Why it impresses:** demonstrates the **national-macro-broadcast** join and CPI-real deflation — a
  grain-reconciliation pattern (metro-monthly × national-mixed-cadence).
- **Columns:** metro price/rent × FRED `MORTGAGE30US`, `FIXHAI`, `MEHOINUSA672N`, `CPIAUCSL` (deflator).
- **Feasibility:** ✅; relies on the forward-filled FRED wide strip (already a Gold decision).

---

## C. Per-metric classification (the core deliverable)

Default **DAX-measure** for slicer-responsive time-intelligence; **Gold-materialized** for expensive,
canonical, or cross-source derivations; **needs-new-data** flagged sparingly.

| Metric | Source columns | Placement | Rationale |
|---|---|---|---|
| FHFA home-price YoY | `index_nsa` + `dim_date` | **GOLD** | Quarterly **with gaps** → needs date-aware self-join (positional `LAG` corrupts); canonical. Already flagged in mapping doc. |
| Zillow value / rent YoY, MoM | `typical_home_value`, `typical_rent` | **DAX** | Monthly **contiguous** → DAX time-intelligence is safe and must respond to the slicer's date range. |
| Realtor metric MoM/YoY | realtor measures | **DAX** | Slicer-responsive; contiguous monthly. (Silver dropped the `_mm`/`_yy` companions precisely so Gold/BI recompute.) |
| Rolling 3/12-mo averages | any monthly measure | **DAX** | Window responds to filter context; cheap. |
| Cross-metro rank / percentile | any measure, within period | **DAX** | **Must** recompute under the user's slicer selection — classic `RANKX`. |
| Metro-vs-national spread | metro growth − national growth | **DAX** | Depends on selected metro; national side is a scalar per date. |
| Price-to-rent ratio | `typical_home_value` ÷ (`typical_rent`×12) | **GOLD** | Canonical row-level ratio reused across concepts; cheap, define once. |
| Gross-yield proxy | (`typical_rent`×12) ÷ `typical_home_value` | **GOLD** | Same — canonical, reused. |
| Affordability composite / payment proxy | metro price × national `MORTGAGE30US` | **GOLD** | **Cross-source** join (national rate broadcast to metro); canonical, expensive to redo per report. |
| CPI-real (deflated) series | nominal ÷ `CPIAUCSL` × base | **GOLD** | Cross-source, canonical deflation. |
| FRED wide forward-filled strip | `fact_fred_series` long → wide | **GOLD** | Cadence reconciliation + forward-fill (absorbs the 2025-10 gap). Already a Gold decision. |
| Hazard risk banding (quartiles) | `risk_score`, per-hazard | **GOLD** | Static attribute, no slicer dependence, canonical banding. |
| **Months of supply (true)** | needs **closed sales** | **NEEDS-NEW-DATA** | Standard metric needs sold counts we don't ingest. A listing-flow proxy (`inventory`÷`new_listing_count`) is *not* the same metric — label it a proxy if used. |
| **Sale-to-list ratio** | needs **sale price + list price** | **NEEDS-NEW-DATA** | We have asking/listing prices only; no sale price per metro. |

*Needs-new-data items are listed for honesty, not as a recommendation to expand — the project's stated
intent is derivable columns from existing data.*

---

## D. Screenshots (ranked by signal ÷ effort)

1. **Power BI Model View — the star schema** *(highest signal, near-zero UI).* Gold facts joined to
   conformed dims. Because the connector **auto-builds relationships from UC FKs**, this is mostly
   generated, not hand-drawn. This one image says "I model data."
2. **`.pbip` / TMDL semantic model in VS Code + a git diff** *(high signal, near-zero design).* Shows the
   semantic model as **version-controlled text** — the analytics-engineering flex, and it ties the BI
   layer into the same git workflow as the pipeline. *(Preview feature — see §E.)*
3. **The hero report page — Concept 1** *(one page only).* A metro matrix/map shaded by hazard risk with a
   price-trend sparkline + affordability column. This is the "looks like a product" shot.
4. *(Optional)* a **DAX measure** in the DAX query view, or the **UC COMMENT → PBI description**
   carry-through, to show platform currency.

**Recommendation:** build **#1 + #2** for certain (cheap, pure DE signal) and **#3** as the single
designed page. Skip a multi-page report.

---

## E. Power BI currency checklist (graded)

| Item | What changed since ~2020 | Grade | Note for you |
|---|---|---|---|
| **Datasets → "Semantic models"** | Renamed Nov 2023 w/ Fabric GA | **Verified** | Use current term in the README. |
| **Microsoft Fabric umbrella** | Power BI now one Fabric experience | **Verified** | Context only. |
| **`.pbip` project format** | Report+model as plain-text folders, git-ready | **Verified — but PREVIEW** | MS Learn (doc dated 2025-12-15) **still marks PBIP "preview"**, GA targeted 2026. Fine for a portfolio — just label it preview; enable in Desktop *Preview features*. |
| **TMDL + PBIR** | YAML-like model metadata (TMDL); concise report format (PBIR) for clean diffs | **Verified (preview-era)** | The reason `.pbip` diffs are readable. |
| **Databricks connector → Power BI Desktop** (Import/DirectQuery) | Native connector; **free path** (Pro/Desktop) | **Verified** | Your realistic build path; no Premium needed. |
| **UC column COMMENT → PBI description** | Connector copies column comments to PBI descriptions | **Verified** | Direct payoff for the mapping-doc COMMENT work. |
| **UC FK → PBI relationships** | FK relationships preserved on import (one active path; rest set inactive) | **Verified** | Declare Gold PK/FK so the model view auto-builds. |
| **Databricks-UI "Publish to Power BI workspace"** | Create a semantic model from UC tables in the Databricks UI | **Verified — gated** | Requires **Power BI Premium / PPU / Fabric capacity + XMLA read-write + SQL warehouse**. Likely **not** available free — present as the *enterprise* option, don't rely on it. |
| **UC Metric Views** (YAML semantic layer in Databricks, 2025) | Define metrics in UC; on-theme with thin-BI philosophy | **Projected** | Compelling but PBI connector reportedly doesn't natively support the `MEASURE()` syntax (needs Tabular Editor "Semantic Bridge"). **Verify before citing in an interview.** |
| **Modern DAX** (calc groups in Desktop, field parameters, DAX query view) | Added 2022–2024 | **Projected** | Use one to show currency; not load-bearing. |

---

## Decisions for Gold design (resolved 2026-06-01)

These six were the open questions; all are now decided and bind the Gold `/sc:design` pass.

1. **Metro universe — SPARSE OUTER.** Keep housing at full Zillow/Realtor coverage (859/935); join FHFA
   appreciation as a **sparse add-on** (NULL where FHFA's 373-metro coverage is absent). Maximizes
   coverage and is honest about the gap, rather than discarding ~486 Zillow metros to an inner join.
2. **Gold/DAX split — AS DOCUMENTED (§C).** The placement table stands: cross-source / canonical /
   expensive derivations (FHFA YoY, price-to-rent, gross-yield, affordability composite, CPI-real, FRED
   wide strip, hazard banding) materialize in **Gold**; slicer-responsive time-intelligence (Zillow/
   Realtor MoM-YoY, rolling avgs, rank/percentile, metro-vs-national spread) stays in **DAX**.
3. **Declare PK/FK constraints in Gold — YES.** Each Gold fact declares its PK and FKs to the conformed
   dims. Near-free, and it drives the Power BI connector's auto-built model-view relationships (the #1
   screenshot).
4. **Realtor Sep–Nov 2022 methodology break — DOCUMENT-ONLY (via COMMENT).** Realtor.com re-based its
   inventory / time-on-market metrics in late 2022; values before/after are not directly comparable, and
   our realtor fact (starts 2016) straddles the break. Treatment: a one-line `COMMENT` on the affected
   realtor measures noting the source re-basing — **no per-row era flag** (over-engineering for a single
   known break). *(Break is Verified — FRED series notes, e.g. `MEDDAYONMARUS`.)*
5. **RESL polarity — KEEP AS IS.** FEMA's Community Resilience score keeps its native direction (higher =
   more resilient, opposite to the hazard scores). Readers understand "90% resilient > 20% resilient"; do
   not invert. Any composite "risk" score must account for this polarity difference explicitly.
6. **Serving layer — PLAIN GOLD TABLES + THIN PBI MODEL (spine); UC Metric Views OPTIONAL/DOCUMENTED.**
   Build the verified path: star-schema Gold Delta tables + a thin Power BI semantic model where
   slicer-responsive measures live in DAX. This is the transferable skill being assessed and produces the
   #1/#2 screenshots with verified connector behavior. **Optionally**, after the core works, add **one**
   UC Metric View over a single Gold table as a currency demonstration — but only if a probe confirms the
   PBI connector consumes it on this edition (research flagged `MEASURE()`/connector friction needing
   Tabular Editor's "Semantic Bridge"); otherwise keep Metric Views as a documented "evaluated" note.
   **Do not make a Metric View load-bearing.**

---

## Sources

- Zillow Research — [ZHVI methodology](https://www.zillow.com/research/zhvi-methodology/), [ZORI methodology](https://www.zillow.com/research/methodology-zori-repeat-rent-27092/), [why ZHVI over median sale price](https://www.zillow.com/research/why-zillow-home-value-index-better-17742/)
- Redfin — [Data Center metric definitions](https://www.redfin.com/news/data-center-metrics-definitions/), [months of supply](https://www.redfin.com/definition/monthsof-supply)
- Realtor.com methodology updates (Nov 2021 / Sep 2022 break) — via FRED series notes, e.g. [MEDDAYONMARUS](https://fred.stlouisfed.org/series/MEDDAYONMARUS)
- Microsoft Learn — [Datasets renamed to semantic models](https://learn.microsoft.com/en-us/power-bi/connect-data/service-datasets-rename), [Power BI Desktop projects (PBIP)](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview), [Publish to Power BI service from Azure Databricks](https://learn.microsoft.com/en-us/azure/databricks/partners/bi/power-bi-service)
- Databricks — [Power BI with Databricks](https://docs.databricks.com/aws/en/partners/bi/power-bi), [UC Business Semantics / Metric Views](https://www.databricks.com/product/unity-catalog/business-semantics)
- Tabular Editor — [Semantic modeling patterns with Power BI and Databricks](https://tabulareditor.com/blog/semantic-modeling-patterns-with-power-bi-and-databricks) *(secondary; the Metric Views / `MEASURE()` caveat)*
