-- silver_row_counts.sql
-- Row count for every table in the silver schema (dims + facts + quarantine).
-- Adhoc diagnostic — run in the DBSQL editor, a %sql notebook cell, or the Statements API.
--
-- Catalog is parameterized via a session variable so the same script works on any target.
-- Set it to the target's catalog before running:
--   dev / user  -> dev_marketpulse      staging -> staging_marketpulse      prod -> marketpulse
-- (If your tool doesn't support session variables, replace every
--  IDENTIFIER(catalog || '.silver.<t>') with the literal three-part name catalog.silver.<t>.)

DECLARE OR REPLACE VARIABLE catalog STRING DEFAULT 'dev_marketpulse';
-- SET VARIABLE catalog = 'marketpulse';   -- uncomment / edit per target

SELECT kind, table_name, row_count
FROM (
    -- Conformed dimensions
    SELECT 'dim'  AS kind, 'dim_geo'        AS table_name, count(*) AS row_count FROM IDENTIFIER(catalog || '.silver.dim_geo')
    UNION ALL
    SELECT 'dim', 'dim_date',                 count(*) FROM IDENTIFIER(catalog || '.silver.dim_date')
    UNION ALL
    SELECT 'dim', 'dim_fred_series',          count(*) FROM IDENTIFIER(catalog || '.silver.dim_fred_series')
    -- Housing facts
    UNION ALL
    SELECT 'fact', 'fact_zillow_metro_monthly',     count(*) FROM IDENTIFIER(catalog || '.silver.fact_zillow_metro_monthly')
    UNION ALL
    SELECT 'fact', 'fact_realtor_metro_monthly',    count(*) FROM IDENTIFIER(catalog || '.silver.fact_realtor_metro_monthly')
    UNION ALL
    SELECT 'fact', 'fact_fhfa_hpi_metro_quarterly', count(*) FROM IDENTIFIER(catalog || '.silver.fact_fhfa_hpi_metro_quarterly')
    UNION ALL
    SELECT 'fact', 'fact_fred_series',              count(*) FROM IDENTIFIER(catalog || '.silver.fact_fred_series')
    -- Weather/hazard facts (CBSA atoms)
    UNION ALL
    SELECT 'fact', 'fact_fema_hazard_cbsa',         count(*) FROM IDENTIFIER(catalog || '.silver.fact_fema_hazard_cbsa')
    UNION ALL
    SELECT 'fact', 'fact_noaa_climate_cbsa',        count(*) FROM IDENTIFIER(catalog || '.silver.fact_noaa_climate_cbsa')
    -- Quarantine (rejected rows across all sources)
    UNION ALL
    SELECT 'quarantine', 'quarantine',              count(*) FROM IDENTIFIER(catalog || '.silver.quarantine')
)
ORDER BY kind, table_name;


-- ============================================================================================
-- No-gap check — date-based facts only
-- ============================================================================================
-- A "gap" = a calendar period that should exist in a series but has no row. Gold derivations that
-- look back a fixed number of periods (e.g. FHFA year-over-year via a 4-quarter offset, FRED
-- forward-fill) assume a CONTIGUOUS series per entity; a silent gap makes a positional look-back
-- reach the wrong period. This query reports, per date-based fact, how many entities have at least
-- one gap and how many periods are missing in total. (The two CBSA weather facts are static —
-- geo-keyed, no date — so they have no cadence to check and are intentionally excluded.)
--
-- Method:
--   * Monthly / quarterly facts (zillow, realtor, fhfa): build a calendar-position ORDINAL per row
--     (year*12+month, or year*4+quarter) from dim_date. For each entity, missing = (MAX(ord) -
--     MIN(ord) + 1) - present_rows. This counts holes WITHIN each entity's own first..last span;
--     it does NOT penalise an entity for starting late or ending early (different metros legitimately
--     have different histories).
--   * FRED (fact_fred_series): cadence is per-series (weekly / monthly / quarterly / annual), so a
--     fixed ordinal can't be used. Instead, measure the day-spacing between consecutive observations
--     (LAG), take each series' MODAL spacing as its native cadence, and count a missing observation
--     wherever a spacing exceeds 1.5x the modal (missing ~= round(gap_days / modal) - 1). The 8-9 day
--     spacings in the weekly mortgage series (holiday reporting shifts) stay under 1.5x and are NOT
--     flagged; a true skipped period is.
--
-- Interpreting the output (baseline observed on dev 2026-06-01):
--   zillow / realtor          -> 0 gaps (fully contiguous).
--   fhfa                      -> ~42 metros / ~132 quarters, ~93% pre-1985 (expected historical
--                                sparsity in small metros; harmless for any post-2000 window).
--   fred                      -> CPIAUCSL + UNRATE each miss one month (2025-10), a source-side BLS
--                                release gap; should self-heal on a later refresh once BLS publishes.
-- A NEW gap in zillow/realtor, or a fhfa gap in a recent quarter, would indicate a load problem.

WITH zil AS (
        SELECT f.geo_key, dd.year*12 + dd.month AS ord
        FROM IDENTIFIER(catalog || '.silver.fact_zillow_metro_monthly') f
        JOIN IDENTIFIER(catalog || '.silver.dim_date') dd ON f.date_key = dd.date_key
    ),
    zilp AS (SELECT geo_key, count(*) AS present, max(ord) - min(ord) + 1 AS span FROM zil GROUP BY geo_key),

    rea AS (
        SELECT f.geo_key, dd.year*12 + dd.month AS ord
        FROM IDENTIFIER(catalog || '.silver.fact_realtor_metro_monthly') f
        JOIN IDENTIFIER(catalog || '.silver.dim_date') dd ON f.date_key = dd.date_key
    ),
    reap AS (SELECT geo_key, count(*) AS present, max(ord) - min(ord) + 1 AS span FROM rea GROUP BY geo_key),

    fhf AS (
        SELECT f.geo_key, dd.year*4 + dd.quarter AS ord
        FROM IDENTIFIER(catalog || '.silver.fact_fhfa_hpi_metro_quarterly') f
        JOIN IDENTIFIER(catalog || '.silver.dim_date') dd ON f.date_key = dd.date_key
    ),
    fhfp AS (SELECT geo_key, count(*) AS present, max(ord) - min(ord) + 1 AS span FROM fhf GROUP BY geo_key),

    -- FRED: per-series day-spacing between consecutive observations.
    fd AS (
        SELECT series_id,
               datediff(observation_date,
                        lag(observation_date) OVER (PARTITION BY series_id ORDER BY observation_date)) AS gap_days
        FROM IDENTIFIER(catalog || '.silver.fact_fred_series')
    ),
    fcount AS (SELECT series_id, count(*) AS n FROM IDENTIFIER(catalog || '.silver.fact_fred_series') GROUP BY series_id),
    -- modal (most frequent) spacing per series = its native cadence in days
    fmodrk AS (
        SELECT series_id, gap_days,
               row_number() OVER (PARTITION BY series_id ORDER BY count(*) DESC) AS rn
        FROM fd WHERE gap_days IS NOT NULL GROUP BY series_id, gap_days
    ),
    fmod AS (SELECT series_id, gap_days AS modal FROM fmodrk WHERE rn = 1),
    -- a jump > 1.5x the modal spacing implies round(gap/modal)-1 missing observations
    fgap AS (
        SELECT fd.series_id, sum(cast(round(fd.gap_days / fmod.modal) AS INT) - 1) AS missing
        FROM fd JOIN fmod ON fd.series_id = fmod.series_id
        WHERE fd.gap_days > fmod.modal * 1.5
        GROUP BY fd.series_id
    ),
    fsum AS (
        SELECT fc.series_id, fc.n, coalesce(fg.missing, 0) AS missing
        FROM fcount fc LEFT JOIN fgap fg ON fc.series_id = fg.series_id
    )
SELECT fact, grain, entities, rows, entities_with_gaps, missing_periods,
       CASE WHEN missing_periods = 0 THEN 'OK' ELSE 'GAPS' END AS verdict
FROM (
    SELECT 'fact_zillow_metro_monthly'     AS fact, 'monthly'           AS grain,
           count(*) AS entities, sum(present) AS rows,
           sum(CASE WHEN present < span THEN 1 ELSE 0 END) AS entities_with_gaps,
           sum(span - present) AS missing_periods
    FROM zilp
    UNION ALL
    SELECT 'fact_realtor_metro_monthly', 'monthly',
           count(*), sum(present),
           sum(CASE WHEN present < span THEN 1 ELSE 0 END), sum(span - present)
    FROM reap
    UNION ALL
    SELECT 'fact_fhfa_hpi_metro_quarterly', 'quarterly',
           count(*), sum(present),
           sum(CASE WHEN present < span THEN 1 ELSE 0 END), sum(span - present)
    FROM fhfp
    UNION ALL
    SELECT 'fact_fred_series', 'per-series native',
           count(*), sum(n),
           sum(CASE WHEN missing > 0 THEN 1 ELSE 0 END), sum(missing)
    FROM fsum
)
ORDER BY fact;
