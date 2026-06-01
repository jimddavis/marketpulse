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
