import base64
import json
from pathlib import Path

import pytest

from tnt import scrape
from tnt.address import Address
from tnt.diff import diff_runs
from tnt.extract import extract
from tnt.geocode import GeoResult, geocode_queries, haversine_m, validation_flags
from tnt.ids import store_id
from tnt.pipeline import run

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_capture.json"


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape, "RAW_DIR", tmp_path / "raw")
    return scrape.import_capture(FIXTURE)


def test_extract_finds_nested_store_list(raw):
    stores = extract(raw)
    assert {s.source_id for s in stores} == {"101", "102", "103", "201"}
    a = next(s for s in stores if s.source_id == "101")
    assert a.address == "#100 - 1234 Example Road, Burnaby, BC, V5H 2E1"
    assert (a.lat, a.lng) == (49.227, -123.0)


def test_pipeline_keeps_lower_mainland_and_flags(raw):
    stores = {s.source_id: s for s in run(raw)}
    assert set(stores) == {"101", "102", "103"}  # Thornhill is dropped
    assert stores["101"].unit == "100" and stores["101"].flags == []
    assert stores["102"].flags == ["missing_postal_code"]
    assert stores["102"].hours_notes == ["Grand Opening: Oct 8 9am"]
    assert "hours_unparsed" in stores["103"].flags


def test_har_import_decodes_base64_bodies(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape, "RAW_DIR", tmp_path / "raw")
    body = base64.b64encode(FIXTURE.read_bytes()).decode()
    har = {"log": {"entries": [
        {"request": {"url": "https://www.tntsupermarket.com/stores", "postData": {"text": "{}"}},
         "response": {"status": 200, "content": {"text": body, "encoding": "base64", "mimeType": "application/json"}}},
        {"request": {"url": "https://maps.googleapis.com/maps/vt"},
         "response": {"status": 200, "content": {"text": "_xdc_._abc && _xdc_._abc([])", "mimeType": "text/javascript"}}},
    ]}}
    har_path = tmp_path / "capture.har"
    har_path.write_text(json.dumps(har))
    saved = scrape.import_capture(har_path)
    assert len(json.loads(saved.read_text())["captures"]) == 1  # the Maps JSONP is skipped
    assert len(extract(saved)) == 4


def test_store_id_ignores_formatting_and_postal_code():
    a = Address("1800 Sheppard Ave. E", "1115", "Toronto", "ON", "M2J 5A7")
    b = Address("1800 sheppard avenue east", "1115", "TORONTO", "ON", None)
    assert store_id("T&T Supermarket", a) == store_id("T&T Supermarket", b)


def test_store_id_changes_with_unit():
    a = Address("1800 Sheppard Avenue East", "1115", "Toronto", "ON", None)
    b = Address("1800 Sheppard Avenue East", "1116", "Toronto", "ON", None)
    assert store_id("T&T Supermarket", a) != store_id("T&T Supermarket", b)


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
    addr = Address("3700 No. 3 Rd", "1000", "Richmond", "BC", "V6X 3X2")
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


def test_diff_runs():
    before = [{"store_id": "a", "name": "A"}, {"store_id": "b", "name": "B"}]
    after = [{"store_id": "b", "name": "B2"}, {"store_id": "c", "name": "C"}]
    d = diff_runs(before, after)
    assert d.added == ["c"] and d.removed == ["a"]
    assert d.changed == {"b": {"name": ("B", "B2")}}
