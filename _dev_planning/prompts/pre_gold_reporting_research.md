  # Pre-Gold reporting research for the marketpulse Databricks medallion project.

  ## Goal
  Recommend a small, high-impact set of Gold-layer report concepts and the derived columns/
  metrics needed to support them. The audience for the FINISHED work is a hiring manager
  evaluating me for a DATA ENGINEERING / ANALYTICS-ENGINEERING role (career-changer
  re-entering the field). So optimize recommendations for what signals strong data
  modeling and engineering judgment — NOT for dashboard visual polish.

  Guiding philosophy (treat as a constraint, not a preference): thin BI over a rich,
  governed Gold layer. Push transformation/business logic UPSTREAM into Gold; keep the
  Power BI semantic model a thin presentation surface. The reporting layer exists mainly
  to produce 1–2 persuasive screenshots and demonstrate current Power BI familiarity.

  ## Read first (authoritative — ground every recommendation in these, not assumptions)
  1. _dev_planning/silver_capability_snapshot.md  — what the data can/can't support (ground truth)
  2. _dev_planning/silver_gold_column_name_mapping.md — Gold naming + COMMENT convention + YoY/forward-fill derivation flags already decided
  3. databricks_code/libs/ddl/silver_ddl.py — exact Silver schema
  4. The project CLAUDE.md (.claude/CLAUDE.md) — naming standards, confidence grading, anti-patterns

  ## Research questions
  A. External conventions, mapped onto OUR columns (not generic inspiration):
     - How do reputable real-estate data products present metro housing data
       (Zillow Research, Redfin Data Center, Realtor.com Research, FHFA, NAR, FRED)?
     - Which of their standard metrics/derivations map onto columns we already have?
  B. Report concepts: propose 3–4 (not more). For each, state:
     - the question it answers and the decision it would inform;
     - WHY it reads as impressive to a data-engineering reviewer;
     - the exact Silver/Gold columns it consumes;
     - whether it's feasible given known boundaries (see Constraints).
     - Lean into the hazard×climate × housing seam as the differentiator.
  C. Per-metric classification table — the core deliverable. For every metric the concepts
     need, one row: metric | source columns | EXISTING / GOLD-MATERIALIZED / DAX-MEASURE /
     NEEDS-NEW-DATA | one-line rationale for that placement. Default to DAX-measure for
     slicer-responsive time-intelligence; reserve GOLD-MATERIALIZED for expensive, canonical,
     or cross-source derivations; flag NEEDS-NEW-DATA sparingly and separately.
  D. The screenshots: identify the 3-4 images that land hardest for this audience
     (consider the Power BI Model View / star-schema diagram as a near-zero-UI-effort option),
     and the single report page worth building.
  E. Power BI currency: what materially changed since ~2020 that's worth demonstrating
     (semantic models, Microsoft Fabric, git-trackable .pbip project format, the
     Databricks Unity Catalog → Power BI publish/connector path, a few modern DAX features).
     GRADE platform-specific claims (Verified / Projected / Guessing) per CLAUDE.md §4 and
     flag the Databricks→PBI integration seam as one to verify against current docs before relying on it.

  ## Constraints / boundaries (do not violate; state them in the output)
  - Primary intent is DERIVABLE columns from existing data — NOT dataset expansion. Treat any
    "needs new data" item as an exception, listed separately, with cost/benefit.
  - Honor the Silver boundaries: FHFA covers only 373 metros (the cross-source bottleneck);
    no actual per-metro SALE prices (Zillow=modeled, Realtor=asking, FHFA=index; only national
    MSPUS is a real sale price); macro (FRED) is NATIONAL only; hazard & climate are STATIC,
    single-vintage (can't trend over time).
  - snake_case Gold names; each Gold column's COMMENT = "Display Label: description" per the mapping doc.
  - Right-size for a portfolio: restraint is a positive signal. Do NOT propose an enterprise BI suite.

  ## Non-scope (do not do)
  - Do NOT design Gold DDL or write SQL/PySpark/DAX code (that's a later /sc:design + /sc:implement).
  - Do NOT build or mock Power BI artifacts.
  - Do NOT modify any existing file except to CREATE the deliverable below.

  ## Deliverable
  Write _dev_planning/design_docs/gold_reporting_research.md containing: the 3-4 report
  concepts (B), the per-metric classification table (C), the screenshot recommendation (D),
  a Power BI currency checklist with confidence grades (E), and a short "open questions for
  Gold design" section. Keep it skimmable — it feeds a later /sc:design.
