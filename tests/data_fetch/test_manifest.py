"""WS-G — SOURCES manifest well-formedness. No network."""

from __future__ import annotations

from data_fetch.manifest import SOURCES, WEATHER_SOURCES
from data_fetch.providers import PROVIDERS


def test_four_sources_with_expected_names():
    assert tuple(s.name for s in SOURCES) == ("zillow", "fhfa", "realtor", "fred")


def test_every_spec_uses_a_registered_provider():
    for s in SOURCES:
        assert s.provider in PROVIDERS, f"{s.name} → unregistered provider {s.provider!r}"


def test_http_file_sources_have_urls_no_series():
    for s in SOURCES:
        if s.provider == "http_file":
            for f in s.files:
                assert f.url and f.url.startswith("https://")
                assert f.series_id is None


def test_fred_source_has_key_env_and_series_ids():
    fred = next(s for s in SOURCES if s.name == "fred")
    assert fred.api_key_env == "FRED_API_KEY"
    assert len(fred.files) == 10
    for f in fred.files:
        assert f.url is None and f.series_id
        assert f.expected_header == ("date", "value", "realtime_start", "realtime_end")


def test_csv_files_carry_a_header_xlsx_do_not():
    for s in SOURCES:
        for f in s.files:
            if f.fmt == "xlsx":
                assert f.expected_header is None
            # csv files: zillow/fhfa-master/fred have headers; realtor csvs intentionally
            # have none (snapshot/history schemas validated in Bronze), so we only assert
            # that any header set is a non-empty tuple.
            if f.expected_header is not None:
                assert isinstance(f.expected_header, tuple) and len(f.expected_header) > 0


def test_landed_filenames_unique_within_each_source():
    for s in SOURCES:
        names = [f.landed_filename for f in s.files]
        assert len(names) == len(set(names)), f"duplicate landed_filename in {s.name}"


# -- WEATHER_SOURCES (separate annual tuple; SOURCES untouched) ---------------

def test_weather_sources_expected_names():
    assert tuple(s.name for s in WEATHER_SOURCES) == ("fema_nri", "climate_normals")


def test_weather_specs_use_registered_providers():
    for s in WEATHER_SOURCES:
        assert s.provider in PROVIDERS, f"{s.name} → unregistered provider {s.provider!r}"


def test_fema_nri_is_arcgis_with_query_url_and_header():
    nri = next(s for s in WEATHER_SOURCES if s.name == "fema_nri")
    assert nri.provider == "arcgis_feature_service"
    (csv_file,) = nri.files
    assert csv_file.url and csv_file.url.endswith("/FeatureServer/0/query")
    assert csv_file.expected_header and csv_file.expected_header[0] == "OBJECTID"


def test_climate_normals_http_file_tarball_and_inventory():
    normals = next(s for s in WEATHER_SOURCES if s.name == "climate_normals")
    assert normals.provider == "http_file"
    landed_names = [f.landed_filename for f in normals.files]
    assert any(name.endswith(".tar.gz") for name in landed_names)
    assert "inventory_30yr.txt" in landed_names
    for source_file in normals.files:
        assert source_file.url and source_file.url.startswith("https://www.ncei.noaa.gov/")
        assert source_file.fmt != "csv"   # tarball/txt → header validation skipped


def test_weather_landed_filenames_unique_within_each_source():
    for s in WEATHER_SOURCES:
        names = [f.landed_filename for f in s.files]
        assert len(names) == len(set(names)), f"duplicate landed_filename in {s.name}"
