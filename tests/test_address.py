import pytest

from tnt.address import Address, canonical_street, parse_address


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Real T&T strings.
        (
            "#Y007 - 1 Promenade Circle Thornhill, ON. L4J 4P8",
            Address("1 Promenade Circle", "Y007", "Thornhill", "ON", "L4J 4P8"),
        ),
        ("26 Edward St, Toronto", Address("26 Edward St", None, "Toronto", None, None)),
        (
            "Unit 1115, 1800 Sheppard Avenue East",
            Address("1800 Sheppard Avenue East", "1115", None, None, None),
        ),
        # Lower Mainland shapes.
        (
            "1000-3700 No. 3 Road, Richmond, BC V6X 3X2",
            Address("3700 No. 3 Road", "1000", "Richmond", "BC", "V6X 3X2"),
        ),
        (
            "2800 East 1st Avenue, Vancouver, British Columbia v5m4v8",
            Address("2800 East 1st Avenue", None, "Vancouver", "BC", "V5M 4V8"),
        ),
    ],
)
def test_parse_address(raw, expected):
    assert parse_address(raw) == expected


@pytest.mark.parametrize("raw", [
    "2206 Kingsway  Vancouver, BC. V5N 2TO",   # letter O, not zero
    "2206 Kingsway  Vancouver, BC. V5N2T",     # truncated
])
def test_malformed_postal_code_is_removed_not_parsed_as_city(raw):
    addr = parse_address(raw)
    assert (addr.street, addr.city, addr.province, addr.postal_code) == ("2206 Kingsway", "Vancouver", "BC", None)
    assert addr.issues and addr.issues[0].startswith("invalid postal code")


@pytest.mark.parametrize("raw", [
    "2206 Kingsway  Vancouver, BC. V5N-2T7",
    "2206 Kingsway, Vancouver, B.C. V5N 2T7",
    "2206 Kingsway, Vancouver, BC V5N 2T7, Canada",
])
def test_postal_and_province_variants(raw):
    addr = parse_address(raw)
    assert (addr.city, addr.province, addr.postal_code) == ("Vancouver", "BC", "V5N 2T7")


@pytest.mark.parametrize("raw", ["147–4800 Kingsway  Burnaby, BC. V5H 4J2", "Unit 147 – 4800 Kingsway  Burnaby, BC. V5H 4J2"])
def test_en_dash_between_unit_and_civic(raw):
    addr = parse_address(raw)
    assert (addr.unit, addr.street) == ("147", "4800 Kingsway")


def test_postal_code_rejects_letters_canada_post_never_uses():
    # D, F, I, O, Q, U are never valid; a naive [A-Z]\d[A-Z] accepts this.
    assert parse_address("123 Main St, Vancouver, BC D5K 1O2").postal_code is None


@pytest.mark.parametrize("raw, canonical", [
    ("1800 Sheppard Ave. E", "1800 Sheppard Avenue East"),
    ("2800 E. First Ave", "2800 East 1st Avenue"),
    ("2800 E 1st Ave", "2800 East 1st Avenue"),
    ("458 S.W. Marine Drive", "458 SW Marine Drive"),
    ("3700 No. 3 Rd", "3700 No. 3 Road"),
    ("19705 Fraser HWY", "19705 Fraser Highway"),
    ("15277 100th Ave", "15277 100th Avenue"),
    ("4800 Kingsway", "4800 Kingsway"),
    ("26 Edward St", "26 Edward Street"),
    ("100 St Johns St", "100 Saint Johns Street"),
    ("50 Main St E", "50 Main Street East"),
    ("100 Main St NE", "100 Main Street NE"),
    ("3700 Number 3 Road", "3700 No. 3 Road"),
    ("2800 Southwest Marine Dr", "2800 SW Marine Drive"),
    ("12 Oak Ter", "12 Oak Terrace"),
])
def test_canonical_street(raw, canonical):
    assert canonical_street(raw) == canonical
