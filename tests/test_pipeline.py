import base64
import json
from pathlib import Path

import pytest

from tnt import scrape
from tnt.address import Address
from tnt.diff import diff_runs
from tnt.extract import extract
from tnt.geocode import haversine_m, validation_flags
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
        {"request": {"url": "https://www.tntsupermarket.com/graphql", "postData": {"text": "{}"}},
         "response": {"status": 200, "content": {"text": body, "encoding": "base64"}}},
        {"request": {"url": "https://www.tntsupermarket.com/static/app.js"},
         "response": {"status": 200, "content": {"text": "x"}}},
    ]}}
    har_path = tmp_path / "capture.har"
    har_path.write_text(json.dumps(har))
    saved = scrape.import_capture(har_path)
    assert len(json.loads(saved.read_text())["captures"]) == 1  # app.js skipped
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
    assert validation_flags(addr, site, (49.2271, -123.0001)) == []
    flags = validation_flags(addr, site, (49.2300, -123.0000))  # ~330 m north
    assert len(flags) == 1 and flags[0].startswith("geocode_mismatch_")


def test_diff_runs():
    before = [{"store_id": "a", "name": "A"}, {"store_id": "b", "name": "B"}]
    after = [{"store_id": "b", "name": "B2"}, {"store_id": "c", "name": "C"}]
    d = diff_runs(before, after)
    assert d.added == ["c"] and d.removed == ["a"]
    assert d.changed == {"b": {"name": ("B", "B2")}}
