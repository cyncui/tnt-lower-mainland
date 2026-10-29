"""IDs across runs, relocations and the event log, as week-2 scenarios on
the real 2026-10-29 capture."""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from tnt import scrape
from tnt.events import ended_reasons, events
from tnt.ids import first_store_id, location_id
from tnt.pipeline import run
from tnt.resolve import History, resolve_ids
from tnt.schema import Point, Run

FIXTURE = Path(__file__).parent / "fixtures" / "tnt_bc_2026-10-29.json"
WEEK1, WEEK2, WEEK3 = date(2026, 10, 29), date(2026, 11, 5), date(2026, 11, 12)


@pytest.fixture
def week1(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape, "RAW_DIR", tmp_path)
    return run(scrape.import_capture(FIXTURE))


def named(stores, name):
    return next(s for s in stores if s.name == name)


def rehash(s, **changes):
    """A week-2 record as clean() would make it: fresh IDs from the (changed) address."""
    s = s.model_copy(update=changes)
    loc = location_id(s.brand, s.banner, s.address)
    return s.model_copy(update={"location_id": loc, "store_id": first_store_id(loc)})


def moved(s, lat_offset):
    return Point(lat=s.location.lat + lat_offset, lng=s.location.lng)


def week2_with(week1, name, record, decisions=None):
    """Week 1's stores with `name` replaced by `record` (or dropped if None), resolved."""
    others = [rehash(s) for s in week1.stores if s.name != name]
    stores = others + ([record] if record else [])
    return Run(run_date=WEEK2, captured_from="t", stores=resolve_ids(stores, History.from_runs([week1]), decisions))


def test_unchanged_week_keeps_every_id_and_has_no_events(week1):
    week2 = Run(run_date=WEEK2, captured_from="t",
                stores=resolve_ids([rehash(s) for s in week1.stores], History.from_runs([week1])))
    assert {(s.location_id, s.store_id) for s in week2.stores} == {(s.location_id, s.store_id) for s in week1.stores}
    assert [e for e in events([week1, week2]) if e.run_date == WEEK2] == []


def test_reworded_address_is_the_same_place(week1):
    yaohan = named(week1.stores, "Yaohan Center")
    reworded = rehash(yaohan, address=replace(yaohan.address, street="3700 No. 3 Road (Yaohan Centre)"))
    assert reworded.location_id != yaohan.location_id  # the hash alone would re-key it
    week2 = week2_with(week1, "Yaohan Center", reworded)
    out = named(week2.stores, "Yaohan Center")
    assert (out.location_id, out.store_id, out.matched_by) == (yaohan.location_id, yaohan.store_id, "store_number")


def test_relocation_keeps_the_store_and_ends_the_old_location(week1):
    lougheed = named(week1.stores, "Lougheed")
    new_site = rehash(lougheed, address=replace(lougheed.address, street="9855 Austin Road"),
                      location=moved(lougheed, 0.02))  # ~2.2 km, same store number
    week2 = week2_with(week1, "Lougheed", new_site)
    out = named(week2.stores, "Lougheed")
    assert out.store_id == lougheed.store_id
    assert out.location_id != lougheed.location_id
    assert out.relocated_from == lougheed.location_id and "relocated" in out.flags

    evts = [e for e in events([week1, week2]) if e.run_date == WEEK2]
    assert [(e.type, e.store_id, e.from_location_id) for e in evts] == [
        ("relocated", lougheed.store_id, lougheed.location_id)]
    assert ended_reasons(events([week1, week2])) == {lougheed.location_id: "relocated"}


def test_corrected_pin_at_the_same_address_is_not_a_relocation(week1):
    kingsway = named(week1.stores, "Kingsway")
    week2 = week2_with(week1, "Kingsway", rehash(kingsway, location=moved(kingsway, 0.005)))  # ~550 m, same address
    out = named(week2.stores, "Kingsway")
    assert (out.location_id, out.store_id) == (kingsway.location_id, kingsway.store_id)
    assert "pin_moved" in out.flags and out.relocated_from is None


def test_closure_is_an_event_and_ends_the_location(week1):
    kingsway = named(week1.stores, "Kingsway")
    week2 = week2_with(week1, "Kingsway", None)
    evts = events([week1, week2])
    assert [(e.type, e.store_id) for e in evts if e.run_date == WEEK2] == [("closed", kingsway.store_id)]
    assert ended_reasons(evts) == {kingsway.location_id: "closed"}


def test_unproven_relocation_is_flagged_not_linked(week1):
    lougheed = named(week1.stores, "Lougheed")
    # Same name 2.2 km away, but T&T gave it a new store number: maybe a move.
    newcomer = rehash(lougheed, address=replace(lougheed.address, street="9855 Austin Road"),
                      location=moved(lougheed, 0.02), source=lougheed.source.model_copy(update={"id": "77"}))
    week2 = week2_with(week1, "Lougheed", newcomer)
    out = named(week2.stores, "Lougheed")
    assert out.matched_by == "new" and out.store_id != lougheed.store_id
    assert out.relocation_candidate == lougheed.location_id and "possible_relocation" in out.flags
    assert {e.type for e in events([week1, week2]) if e.run_date == WEEK2} == {"opened", "closed"}


def test_confirmed_relocation_is_linked(week1):
    lougheed = named(week1.stores, "Lougheed")
    newcomer = rehash(lougheed, address=replace(lougheed.address, street="9855 Austin Road"),
                      location=moved(lougheed, 0.02), source=lougheed.source.model_copy(update={"id": "77"}))
    decisions = {newcomer.location_id: lougheed.location_id}  # what `tnt link` records
    week2 = week2_with(week1, "Lougheed", newcomer, decisions)
    out = named(week2.stores, "Lougheed")
    assert (out.store_id, out.matched_by, out.relocated_from) == (lougheed.store_id, "review", lougheed.location_id)
    assert [e.type for e in events([week1, week2]) if e.run_date == WEEK2] == ["relocated"]


def test_store_that_skips_a_week_reopens_with_its_ids(week1):
    kingsway = named(week1.stores, "Kingsway")
    week2 = week2_with(week1, "Kingsway", None)
    week3 = Run(run_date=WEEK3, captured_from="t",
                stores=resolve_ids([rehash(s) for s in week1.stores], History.from_runs([week1, week2])))
    assert named(week3.stores, "Kingsway").location_id == kingsway.location_id
    evts = events([week1, week2, week3])
    assert [(e.type, e.store_id) for e in evts if e.run_date == WEEK3] == [("reopened", kingsway.store_id)]
    assert ended_reasons(evts) == {}


def test_pin_match_needs_exactly_one_candidate(week1):
    kingsway = named(week1.stores, "Kingsway")
    no_number = kingsway.source.model_copy(update={"id": None})
    twin = kingsway.model_copy(update={"location_id": "loc_" + "0" * 16, "store_id": "sto_" + "0" * 16,
                                       "source": no_number})
    earlier = Run(run_date=WEEK1, captured_from="t", stores=[kingsway.model_copy(update={"source": no_number}), twin])
    [out] = resolve_ids([rehash(kingsway, source=no_number)], History.from_runs([earlier]))
    assert out.matched_by == "new"


def test_v1_files_migrate_with_their_history():
    v1 = {"schema_version": 1, "run_date": "2026-10-29", "captured_from": "t", "stores": []}
    assert Run.model_validate(v1).schema_version == 2


def test_run_rejects_duplicate_ids(week1):
    a, b = week1.stores[0], week1.stores[1]
    with pytest.raises(ValidationError, match="duplicate location_ids"):
        Run(run_date=WEEK1, captured_from="t", stores=[a, b.model_copy(update={"location_id": a.location_id})])
    with pytest.raises(ValidationError, match="duplicate store_ids"):
        Run(run_date=WEEK1, captured_from="t", stores=[a, b.model_copy(update={"store_id": a.store_id})])
