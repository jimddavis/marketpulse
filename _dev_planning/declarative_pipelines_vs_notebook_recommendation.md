# Bronze → Silver: Lakeflow Declarative Pipelines vs. Python module/notebook — recommendation

**Status:** Research report (per `/sc:research`) — analysis + recommendation for human decision. No implementation.
**Date:** 2026-05-29
**Scope:** How to build the Bronze → Silver transform for the four MarketPulse sources (Zillow, Realtor.com, FHFA HPI, FRED), described in `bronze_silver_pipeline_overview.md`.
**Bottom line:** **Continue with the Python module/notebook approach.** Not because declarative pipelines are unavailable (they are available) — but because, for *this* project, paradigm consistency, the load-bearing custom audit model, and the learning goals all point the same way.

---

## 0. The finding that changes the framing

The overview doc (line 351) and the project `CLAUDE.md` both list **"DLT / Lakeflow Declarative Pipelines — out of scope, Free-Edition constraint."** That assumption is **out of date and should be corrected.**

> **Verified (Databricks docs, this session): Lakeflow Spark Declarative Pipelines *are* available on Databricks Free Edition.** The Free Edition limitations page lists pipelines as supported with the constraint *"one active pipeline per pipeline type,"* and a published walk-through builds a full bronze/silver/gold declarative pipeline end-to-end on the Free Tier.

So the decision is **no longer made for us by the platform.** We are choosing between two *available* options on merit. That distinction matters: the right reason to pick notebooks here is *fit*, not *constraint*.

(The "Lakeflow requires the Premium plan" claim that appears in some secondary sources refers to enterprise capabilities/support, not the basic declarative pipeline, which the authoritative Free Edition limitations doc and real-world Free-Tier usage both confirm works.)

---

## 1. What the workload actually is (from `bronze_silver_pipeline_overview.md`)

- **Batch, on-demand, low cadence:** monthly (Zillow/Realtor/FRED) and quarterly (FHFA). Explicitly **not streaming** (the doc itself says so).
- **Small, stable DAG:** ~10 Bronze tables → 4 Silver facts + 2 conformed dims (`dim_geo`, `dim_date`). Dependencies are fixed and known.
- **The hard part is transform logic, not orchestration:** Zillow wide→long unpivot, STRING→typed casting, null-sentinel handling (`.`, `-`, `(2.56)`), FRED vintage resolution, and the **Zillow→CBSA geo crosswalk** (a seeded reference CSV).
- **Three load-bearing project patterns** run through everything:
  1. **Custom audit logging** — `pipeline_step_log`, `transform_detail_log` (with `rows_inserted/updated/expired/rejected`, `validation_rules_applied`, `schema_drift_detected`), `ingestion_log` (and the new `download_log`).
  2. **Quarantine-with-reason** — bad rows are *routed* to `quarantine_<source>` with a reason column (`cast_failed:<col>`, `unmatched_geography`), never dropped.
  3. **Explicit MERGE/idempotency strategies** — per-source choice of natural-key MERGE + `row_hash`, `txnAppId` append, or file-delete-reinsert.

These three are not incidental — they are the spine of the project's design philosophy and are codified in `CLAUDE.md` and `AUDIT_DDL.py`.

---

## 2. Option A — Lakeflow Declarative Pipelines

### Pros (for this project)

- **The DAG shape is exactly what it's built for.** ~10 → 6 tables with fixed dependencies is the textbook declarative-pipeline case; it infers the DAG, schedules, retries, and manages incremental state for you. *(Verified — product docs.)*
- **Expectations are first-class quality gates.** The doc's "every typed column passes the cast" / "every fact row has a non-null `geo_key`" checks map onto declarative `EXPECT` constraints, surfaced automatically in a data-quality dashboard. *(Verified — product docs.)*
- **Far less boilerplate.** No hand-written orchestrator, no `dbutils.notebook.run` wiring, no manual step-log plumbing for the happy path. The platform owns orchestration and table maintenance.
- **Modern canonical Databricks path.** Aligns with Unity Catalog + serverless + Asset Bundles; strong résumé/skill value for a learning project.
- **Available on Free Edition** (one active pipeline per type). *(Verified.)*

### Cons (for this project)

- **Paradigm split with the rest of the system.** The download framework (already built, 98 tests) and the entire `CLAUDE.md` operating manual are **imperative module/notebook**. Making Bronze→Silver declarative means **two mental models and two logging systems** in one pipeline. `CLAUDE.md §5` ("match existing patterns") cuts directly against this.
- **It fights the custom audit model.** Declarative pipelines manage their **own** write lifecycle and emit their **own** event log; you cannot cleanly inject per-table `transform_detail_log` rows (`rows_expired`, `validation_rules_applied`, the pre-declared-variable try/except pattern from `CLAUDE.md §11.4`) into their managed writes. Audit writes are exactly the *"procedural side effects"* that the comparison literature says push you toward notebooks. *(Reasoned, corroborated by sources.)*
- **Quarantine-with-reason cuts across the grain of expectations.** Native expectations **drop / fail / warn** — they don't *route bad rows to a table with a reason code*. You can build the split-good/bad pattern inside a declarative table, but at that point you've hand-written the quarantine logic anyway and lost the "free" quality story for the project's most important gate.
- **It hides the very mechanics the project is teaching.** This is a learning project whose explicit goals include MERGE semantics and idempotency strategy selection (A/B/C). Declarative pipelines replace hand-coded MERGE with `AUTO CDC` / streaming-table incrementals — which is great in production, but **abstracts away the exact thing being learned.**
- **Same transform code, no saving there.** The unpivot, sentinel handling, vintage resolution, and crosswalk join are custom PySpark **either way** (declarative tables just wrap them). Declarative buys orchestration/incremental/quality — not transform simplicity — and at this scale the orchestration need is small.
- **Free-Edition operational friction.** *"One active pipeline per pipeline type,"* *"max 5 concurrent job tasks,"* and a fair-usage quota that **shuts compute down for the day if exceeded** make iterative full-refresh reruns costlier than cheap notebook cell-by-cell iteration. *(Verified.)*

---

## 3. Option B — Python module / notebook (the current approach)

### Pros (for this project)

- **One paradigm, end to end.** Matches the already-built download framework, the orchestrator pattern, and every rule in `CLAUDE.md`. The whole pipeline reads as a single system. *(This is the single strongest argument.)*
- **The custom audit model is native here.** `transform_detail_log` with full row-count accounting, the `except`-path logging pattern, and `download_log`↔`ingestion_log` joins are all straightforward imperative writes — the project's spine works with the grain, not against it.
- **Quarantine-with-reason is natural.** A `good_df` / `bad_df` split writing to `quarantine_<source>` with a reason column is the documented Silver pattern and trivial in PySpark.
- **Full control over MERGE/idempotency.** The deliberate per-source A/B/C strategy choice — and the `row_hash` semantics — stay explicit and visible, which is the point for a learning project.
- **Cheapest iteration under the Free-Edition quota.** Cell-level execution, `%skip` debug cells, no full-pipeline refresh to test one transform.
- **No new failure modes.** No declarative-pipeline-specific gotchas (streaming-table semantics, full-refresh behavior, expectation tuning) to learn on top of the domain problem.

### Cons (for this project)

- **You own the orchestration.** The Bronze→Silver run order is hand-wired in the orchestrator (`dbutils.notebook.run`) rather than DAG-inferred. At 6–10 steps this is modest, but it is manual.
- **You own incremental/retry logic.** No managed incremental state; idempotency is your MERGE code's job (which the project already embraces).
- **More boilerplate** than declarative for the happy path — though much of it (audit, quarantine) is *required by the project anyway* and would be re-added inside declarative tables.
- **Misses hands-on declarative-pipeline learning** — a genuine skill gap if the goal includes "modern Databricks data engineering."

---

## 4. Recommendation — **continue with Python module/notebook**

For Bronze → Silver on this project, stay with the module/notebook approach. The reasoning, in priority order:

1. **Consistency beats novelty mid-project.** The download spine is built, tested, and module-shaped; `CLAUDE.md` is a notebook/module manual. Splitting the pipeline into imperative-download + declarative-transform doubles the mental and audit surface for no proportional gain (`CLAUDE.md §5`).
2. **The project's three load-bearing patterns are imperative by nature.** Custom `transform_detail_log` accounting, quarantine-with-reason, and explicit per-source MERGE strategy all *fight* the declarative model. Choosing declarative would mean either abandoning these (a real regression for the project's stated standards) or hand-rebuilding them inside declarative tables (paying declarative's cost without its benefit).
3. **The transform logic — the actual hard part — is paradigm-neutral.** Declarative would simplify orchestration we barely need at this scale, not the unpivot/sentinel/vintage/crosswalk work that dominates the effort.
4. **Learning visibility.** This is explicitly a learning project; the notebook path keeps MERGE/idempotency/medallion mechanics in view, where declarative would abstract them away.
5. **Free-Edition iteration economics** favor cheap cell-level notebook iteration over quota-bounded pipeline refreshes.

**Equally important — correct the record.** Update `bronze_silver_pipeline_overview.md` (line 351) and `CLAUDE.md`: Lakeflow Declarative Pipelines are **available on Free Edition**, so "out of scope" should read **"deliberately not chosen for fit reasons,"** not "unavailable." Choosing notebooks on merit is defensible; choosing them on a false constraint is not.

**Suggested follow-up (not now):** treat declarative pipelines as a **separate, parallel learning track** — the four heterogeneous sources are an excellent declarative-pipelines playground — rather than retrofitting this audit-heavy project. That captures the skill-building value without compromising the main build.

---

## 5. ⚠️ Orthogonal risk that outranks this decision (flag for the team)

Independent of the Bronze→Silver paradigm: **Free Edition restricts outbound internet to "a limited set of trusted domains."** *(Verified — Free Edition limitations doc.)* The **download stage** reaches `files.zillowstatic.com`, `fhfa.gov`, `econdata.s3…amazonaws.com`, and `api.stlouisfed.org` — none of which are guaranteed to be on the allowlist (the allowlist is not published; **Projected** that these are blocked).

If outbound is blocked on Free-Edition serverless, the download framework **cannot run on the cluster**, regardless of how Bronze→Silver is built. The mitigation already exists in the design (`SdkUploadFileWriter`, design doc §8): **download locally** (which we've proven end-to-end via `scripts/download_local.py`) **and upload the files to the Volume via the SDK/UI.** This should be verified at WS-I **before** the Bronze→Silver paradigm matters, because it constrains the whole architecture. Bronze→Silver itself reads from Volumes and writes Delta — **no external internet needed** — so this risk does not change the recommendation above; it just outranks it in sequencing.

---

## Sources

- [Databricks Free Edition limitations — Databricks on AWS](https://docs.databricks.com/aws/en/getting-started/free-edition-limitations) *(Verified: one active pipeline per type; max 5 concurrent job tasks; serverless-only; outbound internet restricted to trusted domains; fair-usage quota.)*
- [My Weekend with LakeFlow on Databricks' Free Tier — Medium](https://medium.com/@mani.bellan/my-weekend-with-lakeflow-on-databricks-free-tier-a9f2e0dbb569) *(Real-world: a full medallion declarative pipeline built and run on the Free Tier.)*
- [Spark Declarative Pipelines — Databricks (product)](https://www.databricks.com/product/data-engineering/lakeflow-declarative-pipelines)
- [Lakeflow Spark Declarative Pipelines — Databricks on AWS (docs)](https://docs.databricks.com/aws/en/ldp/)
- [Declarative Pipelines vs. Notebook Orchestration: How to Pick — Medium, Mar 2026](https://medium.com/@douglas.garcia_64102/declarative-pipelines-vs-acd7aa114960)
- [Lakeflow Declarative Pipelines: The Evolution of DLT — Tredence](https://www.tredence.com/blog/lakeflow-declarative-pipelines-deep-dive-into-the-evolution-of-delta-live-tables-dlt)
- [Announcing the GA of Databricks Lakeflow — Databricks Blog](https://www.databricks.com/blog/announcing-general-availability-databricks-lakeflow)

**Confidence summary:** *Verified* — LDP availability on Free Edition and the Free-Edition operational limits (pipeline/job/quota) and outbound-internet restriction. *Projected* — that the four source domains are specifically blocked by the Free-Edition allowlist (not published; verify empirically at WS-I). *Reasoned* — the per-project fit analysis, grounded in the project docs + cited comparison literature.
