# Geographic risk aggregation & rollup design (FEMA hazard + climate)

**What this is.** A focused design note on one genuinely hard modeling problem in the Gold layer: how
FEMA National Risk Index (NRI) **risk scores and ratings** behave when aggregated across geography, why a
naive average is wrong, and what the project will (and deliberately will *not*) build as a result. It also
captures the related decision about surfacing a categorical **risk rating/band** in reporting.

It exists because this topic is complex enough to reason about on its own, separately from the broader
`gold_layer_design.md`. That doc's **§5.4 (hazard banding)** is the stub this note expands; treat this
file as the authoritative reasoning for anything touching risk aggregation, banding, or geographic
rollup. Self-contained by intent (§21): a future reader needs no prior conversation.

**Status:** reasoning + decisions captured; **no code, and no rollup machinery is being built for v1**
(see §7). FEMA-methodology specifics are graded and flagged for verification before any algorithm is
committed (§8).

**Grounded in:** `silver_capability_snapshot.md` (coverage), `silver_ddl.py`
(`fact_fema_hazard_cbsa` / `fact_noaa_climate_cbsa` schema), `silver_gold_column_name_mapping.md` §5/§6
(names + RESL polarity note), `gold_layer_design.md` §3.3/§5.4 (`dim_metro_profile`).

---

## 1. The data we're reasoning about

FEMA NRI publishes, per geography, three kinds of quantity that behave **completely differently** under
aggregation:

| Quantity | Example columns | Nature | Aggregates? |
|---|---|---|---|
| **Dollar exposure** | `eal_valt` (Expected Annual Loss, $) | **Extensive** (additive) | ✅ `SUM` is exact |
| **Population** | `population` | **Extensive** (additive) | ✅ `SUM` is exact |
| **Score** (0–100 national percentile) | `risk_score`, `sovi_score`, `resl_score`, the 10 per-hazard `*_risks` | **Intensive** (relative rank) | ❌ no meaningful sum or average |
| **Rating** (categorical) | `risk_ratng` = {Very Low, Relatively Low, Relatively Moderate, Relatively High, Very High, Insufficient Data} | **Ordinal label** (a binning of the score) | ❌ no meaningful aggregation |

FEMA's composite is, roughly, `Risk = Expected Annual Loss × Social Vulnerability ÷ Community
Resilience`, with the result expressed as a **national percentile score**; the **rating** is a binning of
that score. *(Grade: Projected — the formula shape is documented but the exact percentile breakpoints for
the rating bins need verification; see §8.)*

**Grain reality:** FEMA publishes NRI at **county and Census-tract** level only. There is **no official
FEMA score or rating at CBSA, state, or region.** Every coarser-than-county figure is therefore *our*
derivation, not a published FEMA value. This is the root of the whole problem.

---

## 2. The core problem: relative measures do not aggregate

A percentile **score** is a unit's rank *relative to all other units*. A region is not "the average
percentile of its metros," because the region itself would occupy a *different* percentile when ranked
against *other regions*. So:

- **Averaging scores is wrong** — even a population-weighted average is only an *approximation*, not the
  region's true relative position.
- **Averaging ratings is undefined** — there is no `mean("Relatively High", "Very Low")`.

This is the "hard part" we anticipated. The instinct that "a simple AVG can't be accurate" is correct,
and it extends further than it first appears: the **population-weighted mean** Silver already uses for the
county→CBSA rollup is *also* an approximation of the same kind. It is an acceptable convenience at the
CBSA grain (and is what `risk_score` already holds), but it is not a faithful aggregation, and stacking
another average on top of it (CBSA→region) compounds the error.

---

## 3. The principle: aggregate the additive base, then re-derive the relative measure

The correct pattern is the inverse of averaging:

> **Roll up the extensive dollar/count base by `SUM`. Then *re-derive* any relative measure (per-capita
> exposure, percentile score, rating) at the new grain from those sums. Never average a score or a
> rating.**

Applied here:

1. **Sum the additive base** across the target geography: `eal_valt` ($) and `population`.
2. **Derive a comparable intensive metric** that *is* meaningful across regions — e.g. **EAL per capita**
   (`eal_valt ÷ population`) or EAL as a share of aggregate home value. A ratio of two sums is itself
   well-defined and comparable; DAX computes it correctly on the fly.
3. **(Only if a relative score/rating is genuinely needed at the new grain)** re-percentile those
   aggregated metrics across the full peer set at that grain, and label the result explicitly as
   *"derived, <grain>-relative — not FEMA-official."*

### Why Silver already supports this
Silver's county→CBSA rollup deliberately kept **both** representations in `fact_fema_hazard_cbsa`:
- `eal_valt` — **summed** dollars (extensive, rollup-safe), and `population` — summed.
- `risk_score` etc. — **population-weighted mean** (the intensive approximation).

Because the **additive base is preserved at CBSA grain**, a faithful coarser rollup is achievable later
*without re-mining Bronze* — sum `eal_valt`/`population` up from CBSA and re-derive. This was good
foresight; this design depends on it.

### Why the categorical `risk_ratng` was dropped at Silver (and why that was right)
The county-level `risk_ratng` label was dropped in the county→CBSA rollup because **a categorical label
cannot be population-weighted** — there is no average of `"Relatively High"`. Keeping the **score** (which
*can* be approximately rolled, and from which a rating can be re-binned) while dropping the **label** was
the correct call. The lesson generalizes: **carry the rollup-safe quantity (score/dollars), derive the
label at the serving layer** — never try to aggregate the label itself.

---

## 4. Surfacing a risk rating/band in reporting (the motivation)

Why we care about a rating at all, and how it would appear — this motivates §5.4 of the Gold design.

**Score vs band do opposite visual jobs; keep both:**

| | Good for | 
|---|---|
| **Score** (continuous 0–100) | ranking, sorting, precise comparison, continuous shading, "top-10 riskiest" |
| **Band/rating** (categorical) | **filtering, grouping, categorical coloring, plain-language labels** |

A categorical band earns its place because a raw score is bad at exactly the things a band is good at:

1. **Slicer** — a one-click "show only Low / Relatively Low risk metros" filter. This is the backbone of
   the hero concept ("appreciating, affordable, *low-risk* metros").
2. **Legend / categorical color** — discrete green→red shading on the hero map/matrix (legible, vs a
   muddy continuous gradient).
3. **Grouping axis** — "how do appreciating metros distribute across risk bands?" (one bar per band).
4. **Detail label** — a card reading *"Overall Risk: Relatively High"* beats *"Risk Score: 78.4"* for a
   human reader.

**Why this forces Gold placement (not DAX):** a Power BI **slicer / legend / axis must be a column** (a
dimension attribute); a DAX *measure* cannot occupy a slicer or legend. So for the band to do jobs 1–3 it
**must be a stored column** on `dim_metro_profile`. This is the same Gold-vs-DAX logic used throughout:
static + slicer-independent + must-be-a-filterable-attribute → materialize in Gold.

**Two concrete schema implications for §5.4** (if the band is adopted at CBSA grain):
- The band is really **two columns**: the label (`overall_risk_band`) **plus an ordinal sort key**
  (`overall_risk_band_order`, 1…5 Very Low→Very High). Without the sort key, Power BI sorts the band
  **alphabetically** ("Relatively High, Relatively Low, Relatively Moderate, Very High, Very Low" —
  meaningless); the sort key + PBI "Sort by column" fixes it.
- An explicit **"Insufficient Data" / "No Rating"** bucket for the 10 Puerto Rico metros that carry null
  scores (sorted last or excluded).
- **RESL polarity (decision #5) still applies:** `community_resilience_score` runs *opposite* (higher =
  better). If banding is ever applied to resilience, the labels must invert — never apply a hazard band
  scheme blindly to resilience.

**Banding rule (Verified — FEMA NRI Technical Documentation, March 2023, §3.2–3.3):** FEMA derives
ratings two different ways depending on the component:
- **Risk Index & EAL ratings: k-means / natural breaks — there are NO fixed numeric breakpoints.**
  scikit-learn `KMeans(n_clusters=5, random_state=42, max_iter=500, n_init=20, tol=1e-15)`, clusters
  ordered ascending Very Low → Very High by centroid, fit to the **county/tract** population. (Direct
  quote: *"for risk and EAL there are no specific numeric values that determine the rating."*)
- **Social Vulnerability & Community Resilience ratings: fixed national-percentile quintiles** — Very Low
  0–20, Relatively Low 20–40, Relatively Moderate 40–60, Relatively High 60–80, Very High 80–100.
- **Non-numeric ratings:** *No Rating* (EAL = 0), *Insufficient Data* (missing source data),
  *Not Applicable* (hazard can't occur), *Data Unavailable* (SoVI/Resilience missing).

**Implication for the CBSA band:** there is **no official FEMA threshold to "apply"** for overall risk —
the cut points are data-derived per release. Two defensible options at CBSA grain:
1. **Replicate FEMA's method** — run `KMeans(n_clusters=5, random_state=42, …)` on the 935 CBSA risk
   scores. Method-faithful and reproducible (fixed seed), but clusters an *already-approximated*
   pop-weighted CBSA score, and the boundaries differ from FEMA's county clustering (it's CBSA-relative
   regardless).
2. **Fixed quintiles** on the CBSA risk score (0–20 … 80–100). Simple, transparent, and exactly how FEMA
   bands SoVI/Resilience — though it diverges from FEMA's k-means for *Risk*.

**Recommended (portfolio):** option 2 (quintiles) for the overall-risk band — simplest and most
transparent — and quintiles are *correct* for any SoVI/Resilience band. Either way, COMMENT the column
as *"CBSA-relative quintile band, derived from a population-weighted CBSA score — not FEMA's official
k-means county/tract rating; planning comparison only."* Map the 10 null-score (PR) metros to the
*No Rating / Insufficient Data* bucket. (RESL polarity, decision #5: an 80–100 resilience band is *good*
— never relabel it as high-risk.)

---

## 5. On-the-fly vs pre-calculated — the split

The aggregation question maps onto the same Gold-vs-DAX split used elsewhere:

| Measure at a coarser grain | How it aggregates | Where it lives |
|---|---|---|
| `eal_valt` ($), `population` | exact `SUM` | **on the fly** (DAX implicit aggregation) |
| EAL per capita = `SUM(eal) ÷ SUM(pop)` | ratio of two sums | **on the fly** (DAX) |
| region/state **score or rating** (re-percentiled) | non-trivial algorithm; DAX would *naively average* it (**wrong**) | **pre-calculated in a Gold table** |

**Rule:** anything DAX can aggregate correctly with `SUM` or a ratio of sums → leave on the fly (free,
slicer-responsive, no duplication). Anything requiring a re-derivation algorithm → **materialize**,
precisely so it *cannot* be silently mis-averaged by a careless implicit aggregation.

---

## 6. Table strategy — separate pre-aggregated tables, but only where needed

- **Additive measures** need **no** per-grain tables. They live once at the finest grain
  (`dim_metro_profile` / the hazard data at CBSA) and DAX sums them up a `dim_geo` hierarchy
  (CBSA → state → census_region → national) on demand. Duplicating `eal_valt` into a region table would
  be redundant and a maintenance hazard.
- **Re-derived scores/ratings** at a coarser grain, *if ever required*, get a **thin dedicated Gold table
  per grain** — e.g. `gold.region_risk_profile` (grain = census_region or state). Each needs its own
  algorithm run and its own peer-set re-percentiling, so each is its own table. This matches the
  intuition that "different rollup steps" would hold pre-calculated values — but **only the relative
  measures**, not the additive ones.

So the architecture is: **one fine-grained source of additive truth + (optionally) one thin derived-score
table per coarse grain that needs a relative score.**

---

## 7. v1 scope decision — we do NOT build rollup machinery

**Critical scoping call:** all four Gold report concepts (`gold_reporting_research.md` §B) are
**metro-level (CBSA)**. None requires a region-level risk *score*. In them, `census_region` /
`primary_state` (already on `dim_geo`) act purely as **slicer / grouping attributes** — the user filters
"show Southern metros" or groups metros by region, while **risk stays at the metro grain**.

Therefore, for v1:
- **Risk lives at CBSA only.** Region/state are slicer attributes, not grains with their own derived
  score.
- **No `region_risk_profile` table, no custom rollup algorithm, no re-percentiling** is built.
- The hard problem of §2–§3 is **deliberately avoided, not solved prematurely** — consistent with the
  project's right-sizing principle (don't build speculative machinery).

This note documents the *path* (the principle, the table strategy, the change-isolation) so that **if** a
region-level score is later genuinely needed, the approach is known and the Silver data (preserved
additive base) is already shaped for it.

### 7.1 Update (2026-06-01): region rollup is now an intended **v1.5**, still deferred

The project owner now intends to build region/state risk rollup. It remains **deferred past the Gold MVP
(v1) into a focused v1.5**, because the **refactoring cost of deferring it is ≈ 0**:

- The **additive base** (`expected_annual_loss_usd`, `population`) is already preserved in Silver
  `fact_fema_hazard_cbsa` **and carried into Gold `dim_metro_profile`** (v1). v2 reads from Gold — no
  Bronze/Silver reach-back.
- The **geography hierarchy** (`primary_state`, `census_region`) is already on `dim_geo` and carried into
  Gold (v1).
- `region_risk_profile` is **purely additive**: a new table + transform + orchestrator task that
  **touches none of the v1 tables**. No DDL migration, no fact changes.

So building it in v1 vs v1.5 is the *same* work (a new table + the algorithm + FEMA verification); doing
it now saves no rework and would expand the v1 critical path (G0→G5) and delay the metro-level star.

**Enablers locked in v1 to keep the deferral free:**
1. `dim_metro_profile` **retains** `expected_annual_loss_usd` + `population` — flagged "do not trim" in
   `gold_layer_design.md` §3.3. This is the single guard rail; dropping them would turn the ~0-cost
   rollup into a DDL migration + reload.
2. The geo hierarchy (`primary_state`, `census_region`) is exposed in the Gold model so **region works as
   a slicer from v1** — which is all the v1 concepts need anyway.

**v1.5 scope when taken up:** build `region_risk_profile` (SUM the additive base by grain → derive
**EAL-per-capita** and/or re-percentile a region-relative score/band, labeled non-official), add
assertions + an orchestrator task. Estimated focused effort ≈ half-day to a day, the bulk of it the
aggregation algorithm — none of it rework.

### 7.2 Additive-base fork (Verified 2026-06-01) — pick the EAL-based path to keep deferral free

FEMA's risk math is `Risk value = EAL × CRF`, where **CRF** (the Social-Vulnerability ÷ Community-
Resilience scaling factor) is **per-community and does NOT aggregate**. Only **dollar values** sum
cleanly (FEMA itself sums EAL and the Risk Index *value* from tracts to counties). This forks the v1.5
region metric:

- ✅ **EAL-based (recommended): `SUM(expected_annual_loss_usd)` and `EAL-per-capita`** = `SUM(eal) ÷
  SUM(population)`. Both inputs are already preserved in Silver/Gold (the §3.3 enabler guard), so this
  path has **≈0 deferral cost** and is the most defensible region-level risk indicator we can produce.
  Optionally re-percentile or k-means the per-capita values into a region-relative *band*.
- ⚠️ **Faithful FEMA-style region Risk score (NOT recommended): not reconstructable** from the current
  base. It would require the Risk Index **dollar value** (`RISK_VALUE`, summable) carried from Bronze —
  a **Silver schema change**, not a free Gold add. And even then, FEMA explicitly warns the NRI *"does
  not consider … interdependencies across geographic regions"* and *"should not be used as an absolute
  measurement"* — so a re-aggregated composite Risk at region grain is low-value and easy to misread.

**Decision:** region rollup uses the **EAL-based path**; do not attempt to reproduce FEMA's composite
Risk score at coarser grains. This keeps the §3.3 enabler guard (`expected_annual_loss_usd` +
`population`) sufficient and the deferral genuinely free.

---

## 8. Designing for change (when/if v2 needs region scores)

The whole point of §3's "preserve the additive base, derive the relative measure" is that it **isolates
the volatile part**:

- The **additive base** (`eal_valt`, `population`) is the immutable source of truth and never changes
  when the algorithm does.
- Any **derived region-score table** reads *only* from that base and is **rebuilt wholesale** (overwrite
  write-strategy, per `gold_layer_design.md` §2.2).
- So **swapping the aggregation algorithm, or adding a new grain** (state, Census division, region,
  national), is a **single-table rebuild** — zero impact on the base hazard data, `dim_metro_profile`, or
  any metro-level report.

"An established algorithm from the internet" vs "our own": FEMA's methodology *is* the established one but
**stops at county/tract**. Defensible coarser approaches, in increasing effort:
1. **EAL-per-capita** (or EAL ÷ aggregate home value) — a real, comparable intensive metric; no
   re-percentiling needed; arguably the most honest region-level risk indicator we can produce.
2. **Re-percentile** the aggregated metrics across the peer set to mint a region-relative score/rating —
   more "FEMA-like," but explicitly *our* ranking, labeled as such.

---

## 9. Open questions — verify before implementing (graded)

| # | Question | Grade | Resolution |
|---|---|---|---|
| 1 | FEMA NRI **score→rating breakpoints** (for §4's CBSA band). | **Verified** (FEMA NRI Tech Doc Mar 2023, §3.2–3.3, fetched 2026-06-01) | **Resolved.** Risk & EAL ratings = k-means (no fixed cuts); SoVI/Resilience = fixed quintiles (0–20…80–100). Non-numeric buckets: No Rating / Insufficient Data / Not Applicable / Data Unavailable. See §4 for the CBSA-band rule + recommendation (quintiles, labeled non-official). |
| 2 | What is the correct **additive base** for a coarser risk rollup? | **Verified** (same doc) | **Resolved with a fork.** FEMA sums *dollar values* tract→county: **EAL ($)** and the **Risk Index value ($)** are additive; **population** is additive; **scores are percentiles** and **CRF is a per-community factor — neither aggregates.** Silver kept `eal_valt` ($) + `population` (✓ additive base) but **not** the Risk Index dollar value or CRF. ⇒ **EAL-based region metrics are free; a faithful FEMA-Risk region score is not reconstructable from the current base** (see §7.1). |
| 3 | Does a CBSA-grain band off the pop-weighted score read sanely? | **Projected** | Spot-check a few known metros once the band is built (G1.5). Low risk — the band is explicitly labeled a CBSA-relative approximation, not FEMA-official. |
| 4 | RESL polarity handling in any composite or banding (decision #5). | **Verified (decision)** | n/a — never invert silently; an 80–100 resilience band is *good*; account for direction explicitly. |

---

## 10. Decisions captured (summary)

1. **Never average scores or ratings.** They are intensive/ordinal; aggregation operates on the
   **extensive base** (`eal_valt`, `population`) by `SUM`, then re-derives.
2. **Silver's dropped `risk_ratng` stays dropped** — labels don't roll up; the score is the rollup-safe
   carrier, and a rating is re-derived at the serving layer.
3. **A CBSA risk band (§4) is the right serving artifact** — two columns (label + ordinal sort key) +
   no-rating bucket. **Rule resolved (Verified):** FEMA uses k-means for Risk/EAL and fixed quintiles for
   SoVI/Resilience; since there's no official threshold to apply at CBSA grain, use **fixed quintiles on
   the CBSA score** (recommended for portfolio), COMMENTed as a CBSA-relative, non-official approximation.
   This replaces `gold_layer_design.md` §5.4's invented-quartile sketch and is now unblocked.
4. **Additive measures roll up on the fly (DAX `SUM`/ratio); derived relative scores are pre-calculated**
   in a thin per-grain Gold table — *only where a relative score is actually needed.* The only true
   additive base is **dollar values + population**; the region metric is **EAL-per-capita** (§7.2) —
   FEMA's composite Risk is NOT reproduced at coarser grains (CRF doesn't aggregate).
5. **v1 does NOT build region rollups.** Region/state are slicer attributes; risk stays at CBSA. The hard
   problem is avoided, and this doc preserves the path for v2.
6. **Change is isolated:** derived score tables read from the immutable additive base and rebuild
   wholesale, so algorithm changes and new grains are single-table rebuilds.

---

## 11. Relationship to other docs / non-goals

- **Expands** `gold_layer_design.md` §5.4 (hazard banding) and §3.3 (`dim_metro_profile`). If §5.4 is
  promoted from "optional" to "include," it should cross-reference this note for the banding rule.
- **Does not** change the Silver layer (the `risk_ratng` drop and the pop-weighted CBSA score stand).
- **Does not** design region rollup tables, the re-percentiling algorithm, or any code — those are out of
  scope for v1 and documented here only as the future path.
- **Does not** reopen the six locked Gold decisions or the metro-level scope of the four report concepts.
