"""Filling a missing postal code from OSM, using the real Willowbrook case:
ten tenants at 19705 Fraser Highway, three postal codes."""

from tnt.address import Address
from tnt.geocode import GeoResult
from tnt.pipeline import infer_postal_code

SITE = (49.1146628, -122.6741906)  # T&T's pin for the Langley store
ADDR = Address("19705 Fraser Highway", "100", "Township of Langley", "BC", None)


def building(name, postcode, house="19705", lat=49.1145, lng=-122.6745):
    return GeoResult(lat, lng, True, f"{name}, {house}, Fraser Highway, Township of Langley", house, postcode)


WILLOWBROOK = [
    building("Willowbrook Shopping Centre", "V3A 4C7"),
    building("大統華 T&T Supermarket", "V3A 7E9"),
    building("DSW", "V3A 7E9"),
    building("Willowbrook", "V3A 7E0"),
    building("LensCrafters", "V3A 4C7"),
    building("Tim Hortons", "V3A 4C7"),
    building("Freedom Mobile", "V3A 4C7"),
]


def test_store_named_point_beats_the_majority():
    found = infer_postal_code(ADDR, SITE, WILLOWBROOK, ["T&T"])
    assert found.value == "V3A 7E9"  # a vote would pick the mall's V3A 4C7
    assert found.candidates == ["V3A 4C7", "V3A 7E0", "V3A 7E9"]
    assert "T&T Supermarket" in found.evidence


def test_disagreement_without_a_store_point_stays_empty():
    tenants = [b for b in WILLOWBROOK if "T&T" not in b.matched]
    found = infer_postal_code(ADDR, SITE, tenants, ["T&T"])
    assert found.value is None
    assert found.candidates == ["V3A 4C7", "V3A 7E0", "V3A 7E9"]


def test_unanimous_buildings_fill_it():
    found = infer_postal_code(ADDR, SITE, [building("A", "V3A 4C7"), building("B", "v3a4c7")], ["T&T"])
    assert found.value == "V3A 4C7"


def test_suite_in_house_number_still_matches_the_civic():
    found = infer_postal_code(ADDR, SITE, [building("Bell", "V3A 7E9", house="19705, Suite 442")], ["T&T"])
    assert found.value == "V3A 7E9"


def test_other_civic_numbers_and_far_points_are_ignored():
    others = [
        building("Next door", "V3A 1A1", house="19710"),
        building("T&T elsewhere", "V3A 2B2", lat=49.12, lng=-122.674),  # ~600 m north
    ]
    assert infer_postal_code(ADDR, SITE, others, ["T&T"]) is None


def test_brand_postal_code_is_never_overwritten():
    addr = Address("19705 Fraser Highway", "100", "Township of Langley", "BC", "V3A 4C7")
    assert infer_postal_code(addr, SITE, WILLOWBROOK, ["T&T"]) is None
