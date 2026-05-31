# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas", "openpyxl", "requests", "rapidfuzz"]
# ///
"""Build the geography crosswalk reference data for Silver dim_geo.

Outputs two committed CSVs under data/crosswalks/:
  cbsa_master.csv             canonical CBSA universe from the OMB/Census 2023 delineation
                              (cbsa_code, cbsa_title, cbsa_type, primary_state, state_list)
  zillow_region_to_cbsa.csv   Zillow RegionID -> cbsa_code, with match_method/score and a
                              `needs_review` flag for low-confidence / unmatched rows

Realtor and FHFA already use CBSA codes, so only Zillow needs matching. The Zillow metro
list is pulled canonically from bronze.zillow_zhvi (region_type='msa') via the SQL warehouse.

Run:  uv run --script scripts/build_crosswalk.py
Re-run only when Zillow adds metros or OMB redefines CBSAs — this is reference data, not
pipeline output (lifecycle longer than any single run).
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd
import requests
from rapidfuzz import fuzz

OMB_URL = ("https://www2.census.gov/programs-surveys/metro-micro/geographies/"
           "reference-files/2023/delineation-files/list1_2023.xlsx")
WAREHOUSE_ID = "44d180bfae8c6d2b"
CATALOG = "dev_marketpulse"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "crosswalks"

# Confidence thresholds for the fuzzy principal-city match (rapidfuzz 0-100).
HIGH = 90      # >= HIGH -> accept
REVIEW = 80    # [REVIEW, HIGH) -> accept but flag needs_review; < REVIEW -> unmatched

# Full state name -> postal, to widen a CBSA's matchable state set using the county-level
# "State Name" column (the title alone can omit a spanning state, e.g. "Salisbury, MD" really
# spans MD-DE).
STATE_NAME_TO_POSTAL = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL",
    "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR",
    "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA",
    "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
    "Puerto Rico": "PR",
}


def _norm(s: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace, expand 'St.' -> 'Saint'."""
    s = (s or "").lower().replace("st.", "saint").replace("ste.", "sainte")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def sql(stmt: str) -> list[list]:
    payload = {"warehouse_id": WAREHOUSE_ID, "wait_timeout": "50s", "statement": stmt}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as t:
        json.dump(payload, t)
        path = t.name
    out = subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements",
                          "--json", f"@{path}"], capture_output=True, text=True)
    Path(path).unlink()
    d = json.loads(out.stdout)
    if d.get("status", {}).get("state") != "SUCCEEDED":
        sys.exit(f"SQL failed: {d.get('status')}")
    return d.get("result", {}).get("data_array", []) or []


def load_cbsa_master() -> pd.DataFrame:
    print(f"Downloading OMB delineation: {OMB_URL}")
    raw = requests.get(OMB_URL, timeout=60)
    raw.raise_for_status()
    # Row layout: 2-row banner, header on the 3rd row, ~3 footer note rows at the bottom.
    df = pd.read_excel(io.BytesIO(raw.content), skiprows=2, dtype=str)
    df = df.rename(columns=lambda c: str(c).strip())
    df = df[df["CBSA Code"].notna() & df["CBSA Code"].str.match(r"^\d{5}$", na=False)]

    rows, index = [], []
    for code, g in df.groupby("CBSA Code"):
        title = g["CBSA Title"].iloc[0]
        kind = g["Metropolitan/Micropolitan Statistical Area"].iloc[0] or ""
        cbsa_type = "metro" if "Metropolitan" in kind else "micro"
        # Canonical title postals (after the last comma: "..., NY-NJ-PA").
        state_part = title.rsplit(",", 1)[1].strip() if "," in title else ""
        title_states = [s.strip() for s in state_part.split("-") if s.strip()]
        # Widen the matchable state set with every state that has a county in this CBSA.
        county_states = {STATE_NAME_TO_POSTAL.get(s) for s in g["State Name"].dropna().unique()}
        match_states = {s for s in (set(title_states) | county_states) if s}
        # Principal cities: split the raw city blob on the hyphen BEFORE normalizing.
        city_blob = title.rsplit(",", 1)[0]
        principal_cities = [_norm(c) for c in city_blob.split("-") if _norm(c)]
        rows.append({
            "cbsa_code": code,
            "cbsa_title": title,
            "cbsa_type": cbsa_type,
            "primary_state": title_states[0] if title_states else "",
            "state_list": "-".join(title_states),
        })
        index.append((code, title, _norm(city_blob), principal_cities, match_states))
    out = pd.DataFrame(rows).sort_values("cbsa_code").reset_index(drop=True)
    print(f"  CBSA universe: {len(out)} ({(out.cbsa_type=='metro').sum()} metro, "
          f"{(out.cbsa_type=='micro').sum()} micro)")
    return out, index


def load_zillow_metros() -> pd.DataFrame:
    print("Querying canonical Zillow metros from bronze.zillow_zhvi ...")
    data = sql(f"SELECT DISTINCT region_id, region_name, state_name "
               f"FROM {CATALOG}.bronze.zillow_zhvi WHERE region_type='msa'")
    df = pd.DataFrame(data, columns=["region_id", "region_name", "state_name"])
    print(f"  Zillow msa metros: {len(df)}")
    return df


def match(zillow: pd.DataFrame, index: list) -> pd.DataFrame:
    results = []
    for _, z in zillow.iterrows():
        zcity = _norm(z["region_name"].rsplit(",", 1)[0])
        zstate = z["state_name"]
        best = (None, None, -1, None)  # code, title, score, method
        for code, title, city_blob, principal_cities, cstates in index:
            if zstate and cstates and zstate not in cstates:
                continue
            # Best of: fuzzy vs the whole city blob (handles hyphenated single cities like
            # 'Winston-Salem'), and an exact / fuzzy hit on ANY principal city (handles
            # multi-city titles like 'Wildwood-The Villages' or 'Massena-Ogdensburg').
            score = fuzz.token_sort_ratio(zcity, city_blob)
            for pc in principal_cities:
                score = max(score, 100 if zcity == pc else fuzz.token_sort_ratio(zcity, pc))
            if city_blob.startswith(zcity):
                score = max(score, 96)
            if score > best[2]:
                best = (code, title, score, "city+state_fuzzy")
        code, title, score, method = best
        # NB: matching is deliberately state-filtered. A no-state exact-city fallback was
        # tried and rejected — it mapped namesakes across states (Dayton TN -> Dayton OH,
        # Helena AR -> Helena MT). Genuine bad-state Zillow tags (e.g. Salisbury) are handled
        # by the manual override file instead (see apply_overrides).
        if score >= HIGH:
            matched, needs_review = code, False
        elif score >= REVIEW:
            matched, needs_review = code, True
        else:
            matched, needs_review, method = None, True, "unmatched"
        results.append({
            "region_id": z["region_id"],
            "region_name": z["region_name"],
            "state_name": zstate,
            "cbsa_code": matched,
            "cbsa_title": title if matched else None,
            "match_score": int(score) if score >= 0 else None,
            "match_method": method,
            "needs_review": needs_review,
        })
    return pd.DataFrame(results)


def apply_overrides(xwalk: pd.DataFrame, cbsa: pd.DataFrame) -> pd.DataFrame:
    """Apply hand-verified region_id -> cbsa_code corrections from the committed override
    CSV (data/crosswalks/zillow_overrides.csv, cols: region_id, cbsa_code[, note]). Overrides
    win over the fuzzy match and are marked method='manual'. This is the durable home for the
    manual-verification pass — re-running the build never loses these."""
    path = OUT_DIR / "zillow_overrides.csv"
    if not path.exists():
        return xwalk
    ov = pd.read_csv(path, dtype=str)
    titles = dict(zip(cbsa["cbsa_code"], cbsa["cbsa_title"]))
    applied = 0
    for _, o in ov.iterrows():
        rid, code = str(o["region_id"]), str(o["cbsa_code"])
        m = xwalk["region_id"].astype(str) == rid
        if m.any():
            xwalk.loc[m, ["cbsa_code", "cbsa_title", "match_method", "needs_review"]] = [
                code, titles.get(code), "manual", False]
            applied += 1
    print(f"Applied {applied} manual override(s) from {path.name}")
    return xwalk


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cbsa, index = load_cbsa_master()
    cbsa.to_csv(OUT_DIR / "cbsa_master.csv", index=False)

    zillow = load_zillow_metros()
    xwalk = match(zillow, index)
    xwalk = apply_overrides(xwalk, cbsa)
    xwalk.to_csv(OUT_DIR / "zillow_region_to_cbsa.csv", index=False)

    matched = xwalk["cbsa_code"].notna().sum()
    review = (xwalk["needs_review"] & xwalk["cbsa_code"].notna()).sum()
    unmatched = xwalk["cbsa_code"].isna().sum()
    print(f"\nWrote {OUT_DIR}/cbsa_master.csv ({len(cbsa)} rows)")
    print(f"Wrote {OUT_DIR}/zillow_region_to_cbsa.csv ({len(xwalk)} rows)")
    print(f"  matched high-confidence : {matched - review}")
    print(f"  matched needs_review    : {review}")
    print(f"  UNMATCHED               : {unmatched}")
    if unmatched or review:
        print("\nRows needing review:")
        cols = ["region_id", "region_name", "state_name", "cbsa_code", "cbsa_title",
                "match_score", "match_method"]
        with pd.option_context("display.max_rows", None, "display.width", 160):
            print(xwalk.loc[xwalk["needs_review"], cols].to_string(index=False))


if __name__ == "__main__":
    main()
