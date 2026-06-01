 /sc:design Gold layer (star schema + thin Power BI serving model) for the marketpulse Databricks medallion project.

  GOAL
  Design (NOT yet implement) the Gold layer: conformed-dimension star schema(s) of fact + dimension
  tables that serve the 4 report concepts already chosen, plus the thin Power BI semantic-model seam
  that consumes them. The deliverable is a design doc + a phased implementation plan — no DDL, no
  PySpark/SQL/DAX code. Optimize the design for DEMONSTRATED MODELING JUDGMENT (audience = a hiring
  manager assessing data-engineering / analytics-engineering skill), not column count or dashboard polish.

  Guiding philosophy (a constraint, not a preference): thin BI over a rich, governed Gold layer. Push
  canonical / cross-source / expensive logic UPSTREAM into Gold; keep slicer-responsive time-intelligence
  in DAX. The DOCUMENTED split is the artifact that signals seniority.

  AUTHORITATIVE INPUTS (read these first; ground every decision here, not in assumptions or chat memory)
  1. _dev_planning/design_docs/gold_reporting_research.md — the report concepts (B), the per-metric
     GOLD-vs-DAX classification table (C), the screenshot plan (D), the Power BI currency checklist (E),
     and the "Decisions for Gold design (resolved 2026-06-01)" section. THOSE SIX DECISIONS ARE FINAL —
     do not reopen them; design TO them (see below).
  2. _dev_planning/silver_gold_column_name_mapping.md — THE authoritative reference for all Gold column
     names (descriptive snake_case), the COMMENT convention (each Gold column COMMENT = verbatim the
     doc's "Display Label: description" text), and the already-decided derivations (FHFA YoY via
     date-aware self-join; FRED forward-filled wide strip).
  3. _dev_planning/silver_capability_snapshot.md — data ground truth: coverage counts, gaps, what the
     data can and cannot support.
  4. databricks_code/libs/ddl/silver_ddl.py — the EXACT Silver schema you build on. Note the conformed
     dims already exist with declared PKs: dim_geo (grain CBSA, PK geo_key), dim_date (grain day, PK
     date_key), dim_fred_series (PK series_id). The six Silver facts: fact_zillow_metro_monthly,
     fact_realtor_metro_monthly, fact_fhfa_hpi_metro_quarterly, fact_fred_series (national/long),
     fact_fema_hazard_cbsa (static), fact_noaa_climate_cbsa (static).
  5. databricks_code/libs/ddl/gold_ddl.py — current STUB (clean no-op) you will replace; mirror the
     module/return-shape pattern of bronze_ddl.py / silver_ddl.py (read silver_ddl.py for the create_*_
     tables(spark, schema) + _ok/_fail contract and the CREATE TABLE IF NOT EXISTS + CONSTRAINT style).
  6. The project CLAUDE.md files (./.claude/CLAUDE.md and ../.claude/CLAUDE.md) — Safety Protocol (§3),
     confidence grading (§4), match-existing-patterns (§5), centralize load-bearing values (§6), Gold
     patterns (GENERATED ALWAYS AS IDENTITY surrogate keys; never monotonically_increasing_id; MERGE for
     facts with consumers, overwrite OK for fully-rebuilt aggregations; route unmatched join rows to
     quarantine/error, never silently drop), three-part names, Volumes-not-/dbfs, audit columns.

  THE SIX RESOLVED DECISIONS (design to these; they are final)
  1. Metro universe = SPARSE OUTER. Keep housing at full Zillow/Realtor coverage (859/935); FHFA
     appreciation joins as a sparse add-on (NULL where FHFA's 373 metros are absent). Do NOT inner-join
     down to 373 for the broad concepts.
  2. Gold/DAX split = AS DOCUMENTED in research §C. Materialize in Gold: FHFA home-price YoY,
     price-to-rent, gross-yield proxy, affordability composite, CPI-real deflation, the FRED wide
     forward-filled strip, hazard risk banding. Leave in DAX: Zillow/Realtor MoM-YoY, rolling averages,
     cross-metro rank/percentile, metro-vs-national spread.
  3. Declare PK/FK constraints on every Gold fact (PK + FKs to conformed dims) — drives the Power BI
     connector's auto-built model-view relationships.
  4. Realtor Sep–Nov 2022 methodology break = DOCUMENT-ONLY, via a COMMENT on the affected realtor
     measure columns. NO per-row era flag.
  5. RESL (FEMA Community Resilience) polarity = KEEP AS IS (higher = more resilient). Any composite
     "risk" score must explicitly account for RESL's opposite direction vs the hazard scores.
  6. Serving = plain Gold tables + a thin PBI model (DAX for slicer-responsive measures). A UC Metric
     View is OPTIONAL and documented-only, never load-bearing — design the plain-Gold spine fully;
     mention the Metric View only as an optional post-core add-on gated on a connector probe.

  ANSWER THESE DESIGN QUESTIONS EXPLICITLY (with rationale + tradeoffs)
  1. Star schema shape: how many Gold facts, at what grain, and which conformed dims each joins. Resolve
     the grain-reconciliation seams: monthly Zillow/Realtor vs quarterly FHFA vs mixed-cadence national
     FRED vs static (date-less) FEMA/NOAA. Does the static hazard/climate enrichment land as its own
     fact, as dim_geo attributes, or a Gold "metro profile" dimension? Justify.
  2. The sparse-outer FHFA join (decision #1): exactly where it attaches (a wide metro-period Gold fact
     vs a separate fhfa Gold fact), and how NULLs read downstream. Include the date-aware prior-year
     self-join for FHFA YoY (NOT positional LAG(...,4)) and the build-time no-gap assertion already
     called for in the mapping doc.
  3. Surrogate keys & constraints: which Gold tables get GENERATED ALWAYS AS IDENTITY surrogate keys vs
     reuse the Silver geo_key/date_key; the full PK/FK constraint set (decision #3) and how it maps to
     PBI relationships (note PBI's one-active-path rule when a fact has multiple date roles).
  4. Write strategy per Gold table (CLAUDE.md §11.2): MERGE vs full-overwrite-rebuild, with a one-line
     why each. Cross-source rebuilt aggregations are good overwrite candidates; facts with active
     consumers favor MERGE.
  5. The FRED long→wide forward-filled strip (decision #2): its Gold grain, the forward-fill mechanism,
     and how it absorbs the 2025-10 release gap (already a decision — design the mechanics, not whether).
  6. The thin PBI seam (decision #6): what the Gold side must guarantee for the connector payoffs —
     COMMENTs present on every Gold column (mapping-doc text), PK/FK declared, names final — so the
     model-view + TMDL-diff screenshots (#1/#2 in research §D) come near-free. Treat the Metric View as
     an optional appendix only.

  DELIVERABLES
  A. A design doc at _dev_planning/design_docs/gold_layer_design.md: the proposed Gold star-schema
     (table-by-table: name, grain, source Silver tables/joins, surrogate-key strategy, PK/FK constraints,
     write strategy, the Gold-materialized derived columns with their mapping-doc COMMENT text), the
     grain-reconciliation decisions, the FHFA sparse-outer + YoY-self-join design, the FRED wide-strip
     design, and the thin-PBI seam contract. Cross-reference the mapping doc for column names rather than
     restating all of them; call out any column NOT already named there.
  B. A phased, parallelizable implementation plan: identify independent workstreams (e.g. gold_ddl tables,
     each build notebook/transform, the no-gap + row-count assertions, the orchestrator job wiring, the
     PBI-seam verification) and their dependency order — mirror how the Silver/weather phases were staged.
  C. An "open questions — verify before implementing" section, each item graded Verified/Projected/
     Guessing per CLAUDE.md §4, with a cheap probe offered. At minimum cover: GENERATED ALWAYS AS IDENTITY
     + PK/FK constraint support on this edition's Delta/UC; whether the Databricks→PBI connector actually
     carries UC COMMENTs and FKs as claimed (research graded Verified — confirm against current docs);
     and the UC Metric View → PBI `MEASURE()` connector friction IF the optional appendix is pursued.

  CONSTRAINTS
  - Follow the Safety Protocol (§3): produce a numbered plan and STOP for approval before writing the
    design doc.
  - Grade every Databricks-specific claim (Verified/Projected/Guessing); WebFetch the Databricks docs for
    non-trivial platform behavior before recommending.
  - Match existing repo patterns (silver_ddl.py module shape, _ok/_fail, CONSTRAINT style, bundle/catalog
    conventions). Do not normalize minority patterns silently (§5).
  - No new hardcoded load-bearing values (§6) — catalog/schema/status come from the existing init/constants.

  NON-SCOPE (do not do)
  - Do NOT write Gold DDL or any SQL/PySpark/DAX code (that's the later /sc:implement).
  - Do NOT build, mock, or design the Power BI .pbip/TMDL artifacts themselves — only the Gold-side seam
    contract that makes them cheap.
  - Do NOT reopen the six resolved decisions, propose dataset expansion, or design the NEEDS-NEW-DATA
    metrics (months-of-supply, sale-to-list) — note them as boundaries only.
  - One task: if you spot drift elsewhere, name it and move on (§7); do not fix it here.
