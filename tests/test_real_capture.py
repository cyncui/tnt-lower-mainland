"""The BC store-locator response captured from a browser on 2026-10-29.

Expected values were checked by hand against the raw strings, not copied
from the parser's output.
"""

from pathlib import Path

import pytest

from tnt import scrape
from tnt.address import Address, parse_address
from tnt.hours import parse_hours
from tnt.pipeline import run

FIXTURE = Path(__file__).parent / "fixtures" / "tnt_bc_2026-10-29.json"


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Two spaces separate street and city; "Kingsway" has no street type to split on.
        ("147-4800 Kingsway  Burnaby, BC. V5H 4J2",
         Address("4800 Kingsway", "147", "Burnaby", "BC", "V5H 4J2")),
        ("2206 Kingsway  Vancouver, BC. V5N 2T7",
         Address("2206 Kingsway", None, "Vancouver", "BC", "V5N 2T7")),
        # Leading cross-street hint, unit with a letter.
        ("(100 Ave. & 152 St.)  101T-15277 100th Ave  Surrey, BC. V3R 8X2",
         Address("15277 100th Ave", "101T", "Surrey", "BC", "V3R 8X2", note="100 Ave. & 152 St.")),
        # "#unit-civic" with no space.
        ("#3000-10153 King George Boulevard  Surrey, BC. V3T 2W1",
         Address("10153 King George Boulevard", "3000", "Surrey", "BC", "V3T 2W1")),
        ("Unit #MAJ1, 8311 Lansdowne Road  Richmond, British Columbia. V6X 3A4",
         Address("8311 Lansdowne Road", "MAJ1", "Richmond", "BC", "V6X 3A4")),
        # Floor between street and city.
        ("2200 Park Royal South, Upper Level  West Vancouver, BC. V7T 2W4",
         Address("2200 Park Royal South", None, "West Vancouver", "BC", "V7T 2W4", note="Upper Level")),
        # Postal code with no space and a trailing space.
        ("1085 Woolridge St, Coquitlam, BC V3K7A9 ",
         Address("1085 Woolridge St", None, "Coquitlam", "BC", "V3K 7A9")),
        # No postal code at all.
        ("Unit 100, 19705 Fraser HWY, Township of Langley, BC",
         Address("19705 Fraser HWY", "100", "Township of Langley", "BC", None)),
    ],
)
def test_real_addresses(raw, expected):
    assert parse_address(raw) == expected


def test_br_tag_between_days_and_times():
    r = parse_hours("Monday to Sunday<br />9:00am - 10:00pm<br />")
    assert r.hours["sun"] == ["09:00", "22:00"] and r.notes == []


def test_split_week_across_crlf_lines():
    r = parse_hours("Sunday - Thursday \r\n9:00 am - 10:00 pm\r\nFriday – Saturday\r\n8:30 am - 10:30 pm\r\n")
    assert r.hours["sun"] == r.hours["thu"] == ["09:00", "22:00"]
    assert r.hours["fri"] == r.hours["sat"] == ["08:30", "22:30"]


def test_whole_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape, "RAW_DIR", tmp_path)
    stores = run(scrape.import_capture(FIXTURE))
    assert len(stores) == 13
    assert all(len(s.hours) == 7 for s in stores)
    assert len({s.store_id for s in stores}) == 13
    assert [s.name for s in stores if s.flags] == ["Langley Store"]  # no postal code

    late = {s.name for s in stores if any(close > "22:00" for _, close in s.hours.values())}
    # Kingsway closes at exactly 22:00, which is not "past" 10 pm.
    assert late == {"Metrotown Store", "Marine Gateway Store", "Lansdowne Store"}
