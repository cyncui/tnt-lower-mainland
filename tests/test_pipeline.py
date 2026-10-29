import base64
import json
from pathlib import Path

import pytest

from tnt import scrape
from dataclasses import replace

from tnt.address import Address, canonical_street
from tnt.diff import diff_runs
from tnt.extract import extract
from tnt.geocode import GeoResult, geocode_queries, haversine_m, validation_flags
from tnt.ids import location_id
from tnt.pipeline import e164, run, split_name
from tnt.schema import Run

FIXTURE = Path(__file__).parent / "fixtures" / "tnt_bc_2026-10-29.json"


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape, "RAW_DIR", tmp_path / "raw")
    return scrape.import_capture(FIXTURE)


def test_extract_reads_the_locator_response(raw):
    stores = extract(raw)
    assert len(stores) == 13
    coquitlam = next(s for s in stores if s.source_id == "19")
    assert coquitlam.address == "2740-2929 Barnet Highway  Coquitlam, BC. V3B 5R5"
    assert (coquitlam.lat, coquitlam.lng) == (49.2778082, -122.8083728)
    assert coquitlam.phone == "604.945.3818"


def test_har_import_keeps_json_and_decodes_base64(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape, "RAW_DIR", tmp_path / "raw")
    body = base64.b64encode(FIXTURE.read_bytes()).decode()
    har = {"log": {"entries": [
        {"request": {"url": "https://www.tntsupermarket.com/stores"},
         "response": {"status": 200, "content": {"text": body, "encoding": "base64", "mimeType": "application/json"}}},
        {"request": {"url": "https://maps.googleapis.com/maps/vt"},
         "response": {"status": 200, "content": {"text": "_xdc_._abc && _xdc_._abc([])", "mimeType": "text/javascript"}}},
    ]}}
    har_path = tmp_path / "capture.har"
    har_path.write_text(json.dumps(har))
    saved = scrape.import_capture(har_path)
    assert len(json.loads(saved.read_text())["captures"]) == 1  # the Maps JSONP is skipped
    assert len(extract(saved)) == 13


def test_run_round_trips_through_json(raw):
    result = run(raw)
    assert Run.model_validate_json(result.model_dump_json()) == result


def test_record_shape(raw):
    parkroyal = next(s for s in run(raw).stores if s.source.id == "17")
    assert (parkroyal.banner, parkroyal.name) == ("Osaka", "Park Royal")
    assert parkroyal.address == Address("2200 Park Royal South", None, "West Vancouver", "BC", "V7T 2W4",
                                        note="Upper Level")
    assert parkroyal.phone == "+17782798988"
    assert list(parkroyal.hours) == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]  # input started on sun
    assert parkroyal.source.name == "Osaka – Park Royal Store"


@pytest.mark.parametrize("raw_name, expected", [
    ("Osaka – Yaohan Center Store", ("Osaka", "Yaohan Center")),
    ("Lougheed Store ", ("T&T Supermarket", "Lougheed")),
    ("Central City Store", ("T&T Supermarket", "Central City")),
])
def test_split_name(raw_name, expected):
    assert split_name(raw_name) == expected


@pytest.mark.parametrize("raw_phone, expected", [
    ("604.945.3818", "+16049453818"),
    ("604-519-8678", "+16045198678"),
    ("1 (604) 519-8678", "+16045198678"),
    ("ext. 12", None),
])
def test_e164(raw_phone, expected):
    assert e164(raw_phone) == expected


@pytest.mark.parametrize("street", ["2800 E. First Ave", "458 S.W. Marine Drive", "3700 No. 3 Rd", "100 St Johns St",
                                    "100 No First", "100 Main St NE", "3700 Number 3 Road"])
def test_canonical_street_is_idempotent(street):
    # Records store the canonical form and the ID canonicalizes again.
    once = canonical_street(street)
    assert canonical_street(once) == once


T = "T&T Supermarket"


@pytest.mark.parametrize("a, b", [
    (Address("1800 Sheppard Ave. E", "1115", "Toronto", "ON", "M2J 5A7"),
     Address("1800 sheppard avenue east", "1115", "TORONTO", "ON", None)),
    (Address("3700 No. 3 Rd", "1000", "Richmond", "BC"), Address("3700 Number 3 Road", "1000", "Richmond", "BC")),
    (Address("458 SW Marine Drive", None, "Vancouver", "BC"), Address("458 Southwest Marine Dr", None, "Vancouver", "BC")),
    (Address("15277 100th Ave", "101T", "Surrey", "BC"), Address("15277 100 Avenue", "101-T", "Surrey", "BC")),
    (Address("4800 Kingsway", "0147", "Burnaby", "BC"), Address("4800 Kingsway", "147", "Burnaby", "BC")),
    (Address("19705 Fraser Hwy", "100", "Township of Langley", "BC"),
     Address("19705 Fraser Highway", "100", "Langley", "BC")),
    (Address("1 Lonsdale Ave", None, "N. Vancouver", "BC"), Address("1 Lonsdale Avenue", None, "North Vancouver", "BC")),
])
def test_store_id_ignores_formatting(a, b):
    assert location_id(T, T, a) == location_id(T, T, b)


def test_store_id_separates_units_banners_and_floors():
    base = Address("2200 Park Royal South", None, "West Vancouver", "BC", note="Upper Level")
    assert location_id(T, T, base) != location_id(T, T, replace(base, unit="1"))
    assert location_id(T, T, base) != location_id(T, "Osaka", base)
    assert location_id(T, T, base) != location_id(T, T, replace(base, note="Lower Level"))


def test_haversine_known_distance():
    # Vancouver City Hall to Burnaby City Hall, ~9.8 km.
    assert haversine_m(49.2611, -123.1139, 49.2488, -122.9805) == pytest.approx(9_800, rel=0.05)


def test_flags_geocode_more_than_200m_away():
    addr = Address("1 Example Road", None, "Burnaby", "BC", "V5H 2E1")
    site = (49.2270, -123.0000)
    assert validation_flags(addr, site, GeoResult(49.2271, -123.0001, True)) == []
    flags = validation_flags(addr, site, GeoResult(49.2300, -123.0000, True))  # ~330 m north
    assert len(flags) == 1 and flags[0].startswith("geocode_mismatch_")


def test_street_level_geocode_is_not_compared():
    addr = Address("3700 No. 3 Road", "1000", "Richmond", "BC", "V6X 3X2")
    # Nominatim's whole-road match for No. 3 Road is 8 km away; that's not a mismatch.
    flags = validation_flags(addr, (49.1863, -123.1333), GeoResult(49.1110, -123.1350, False))
    assert flags == ["geocode_street_level"]


@pytest.mark.parametrize("street, city, expected", [
    # The ordinal-free spelling is a fallback, only sent if the first misses.
    ("2800 E. First Ave", "Vancouver", ["2800 East 1st Avenue, Vancouver, BC, Canada",
                                         "2800 East 1 Avenue, Vancouver, BC, Canada"]),
    ("458 S.W. Marine Drive", "Vancouver", ["458 SW Marine Drive, Vancouver, BC, Canada"]),
    ("15277 100th Ave", "Surrey", ["15277 100th Avenue, Surrey, BC, Canada", "15277 100 Avenue, Surrey, BC, Canada"]),
])
def test_geocode_queries_match_what_nominatim_accepts(street, city, expected):
    assert geocode_queries(Address(street, "1", city, "BC", "V5M 4N8")) == expected


def test_diff_reports_events_and_changes(raw):
    from datetime import date
    week1 = run(raw)
    stores = week1.stores
    renamed = stores[1].model_copy(update={"name": "Renamed"})
    week2 = Run(run_date=date(2026, 11, 5), captured_from="t", stores=[stores[0], renamed, *stores[3:]])
    d = diff_runs(week1, week2)
    assert [(e.type, e.store_id) for e in d.events] == [("closed", stores[2].store_id)]
    assert d.changed == {stores[1].location_id: {"name": (stores[1].name, "Renamed")}}
