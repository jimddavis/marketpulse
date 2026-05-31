# Weather and Natural Hazard Data Sources for a Real Estate Analytics Platform


QUESTION ASKED:  I am creating a real estate reporting application, with Zillow, fred, fhfa and realtor data sets. I want to add some regional weather information, simple things like seasonal temperature, rainfall, snowfall, but also risk factors like hurricanes, tornados, high winds, floods. What are good sources to get that kind of data


ANSWER:  all below

For a real estate analytics platform, it is useful to separate data into two categories:

1. **Climate and weather characteristics** (temperature, precipitation, snowfall)
2. **Natural hazard and insurance risk** (hurricanes, tornadoes, flooding, wildfire, etc.)

The best sources are not necessarily the same.

## Climate and Weather

### 1. NOAA Climate Normals (Highly Recommended)

https://www.ncei.noaa.gov/products/land-based-station/us-climate-normals

Provides long-term averages such as:

- Annual temperature
- Seasonal temperature
- Annual precipitation
- Seasonal precipitation
- Annual snowfall
- Heating degree days
- Cooling degree days

Good for:

```text
CBSA Climate Profile
-------------------
Average Summer High
Average Winter Low
Annual Rainfall
Annual Snowfall
Heating Degree Days
Cooling Degree Days
```

This is probably the highest value-to-effort dataset you can add.

---

### 2. NOAA GHCN Daily

https://www.ncei.noaa.gov/products/land-based-station/global-historical-climatology-network-daily

Daily observations from weather stations.

Useful for generating:

- Extreme heat days
- Freeze days
- Heavy rain events
- Snow days

For example:

```sql
days_above_95F
days_below_32F
days_with_precip_gt_1_inch
```

These often correlate better with housing desirability than averages.

---

### 3. PRISM Climate Data

https://prism.oregonstate.edu

Widely used in academic research.

Advantages:

- 4km resolution
- County-level aggregation is straightforward
- Better spatial coverage than station-only datasets

Excellent if you want serious geographic accuracy.

---

## Natural Hazard Data

This is where things become very valuable for real estate.

### 4. NOAA Storm Events Database

https://www.ncei.noaa.gov/stormevents/

Contains:

- Tornadoes
- Hurricanes
- Tropical storms
- Hail
- High winds
- Flooding
- Ice storms
- Lightning

For each county you can calculate:

```text
Tornadoes per decade
Flood events per decade
Wind events per decade
Storm damages
Fatalities
```

This would be one of the highest-priority additions.

---

### 5. FEMA National Risk Index

https://hazards.fema.gov/nri/

Probably the single best hazard dataset for real estate applications.

Provides scores for:

- Flood risk
- Hurricane risk
- Tornado risk
- Wildfire risk
- Earthquake risk
- Hail risk
- Drought risk
- Winter storm risk

Already aggregated and normalized.

Example:

```text
County Risk Score
-----------------
Flood: 87
Tornado: 42
Wildfire: 12
Hurricane: 76
```

You can roll these up to CBSA.

If building this application, this would be near the top of the list.

---

### 6. FEMA Flood Maps

https://www.fema.gov/flood-maps/national-flood-hazard-layer

Useful if you eventually want:

- Percent of homes in flood zones
- Flood insurance exposure
- Coastal flooding metrics

More difficult ETL than NRI.

---

### 7. U.S. Forest Service Wildfire Risk

https://wildfirerisk.org

Useful for western states.

Provides:

- Wildfire probability
- Exposure
- Community risk

Increasingly important for insurance markets.

---

## Insurance-Relevant Metrics

Many buyers increasingly care about insurance availability.

You can derive:

| Metric | Source |
|----------|----------|
| Hurricane risk | FEMA NRI |
| Flood risk | FEMA NRI |
| Wildfire risk | FEMA NRI / USFS |
| Tornado risk | FEMA NRI |
| Severe storm frequency | NOAA Storm Events |
| Hail frequency | NOAA Storm Events |
| Extreme heat days | NOAA GHCN |
| Freeze days | NOAA GHCN |

These can become excellent dashboard filters.

---

## Suggested Warehouse Design

### Fact tables

```text
fact_climate_cbsa
fact_hazard_cbsa
```

### Climate columns

```text
avg_temp_annual
avg_temp_summer
avg_temp_winter

annual_precipitation
annual_snowfall

cooling_degree_days
heating_degree_days

days_above_95f
days_below_32f
```

### Hazard columns

```text
fema_hurricane_risk
fema_flood_risk
fema_tornado_risk
fema_wildfire_risk

storm_events_last_10_years
flood_events_last_10_years
tornado_events_last_10_years
```

### Geography

```text
dim_cbsa
bridge_cbsa_county
```

with all climate and hazard data collected at county level and rolled up to CBSA.

## Recommended Priority Order

1. FEMA National Risk Index
2. NOAA Climate Normals
3. NOAA Storm Events
4. NOAA GHCN Daily
5. PRISM
6. FEMA Flood Layers

This combination provides a rich "quality of life + risk" dimension alongside Zillow, FHFA, Realtor, and FRED data.
