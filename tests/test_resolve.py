"""Stores keep their IDs across runs. Built on the real capture."""

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from tnt import scrape
from tnt.ids import store_id
from tnt.pipeline import run
from tnt.resolve import latest_records, resolve_ids
from tnt.schema import Point, Run

FIXTURE = Path(__file__).parent / "fixtures" / "tnt_bc_2026-10-29.json"


@pytest.fixture
def week1(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape, "RAW_DIR", tmp_path)
    return run(scrape.import_capture(FIXTURE)).stores


def by_name(stores, name):
    return next(s for s in stores if s.name == name)


def test_reworded_address_keeps_its_id_by_store_number(week1):
    yaohan = by_name(week1, "Yaohan Center")
    # T&T adds the mall name to the street: a rewording the normalizer can't fold.
    address = replace(yaohan.address, street="3700 No. 3 Road (Yaohan Centre)")
    new_hash = store_id(yaohan.brand, yaohan.banner, address)
    assert new_hash != yaohan.store_id
    reworded = yaohan.model_copy(update={"store_id": new_hash, "address": address})
    [out] = resolve_ids([reworded], week1)
    assert (out.store_id, out.matched_by) == (yaohan.store_id, "store_number")


def test_renumbered_store_keeps_its_id_by_pin(week1):
    kingsway = by_name(week1, "Kingsway")
    moved = kingsway.model_copy(update={
        "store_id": "fresh-hash",
        "source": kingsway.source.model_copy(update={"id": "999"}),
        "location": Point(lat=kingsway.location.lat + 0.0002, lng=kingsway.location.lng),  # ~22 m
    })
    [out] = resolve_ids([moved], week1)
    assert (out.store_id, out.matched_by) == (kingsway.store_id, "pin")


def test_far_pin_and_new_number_is_a_new_store(week1):
    kingsway = by_name(week1, "Kingsway")
    elsewhere = kingsway.model_copy(update={
        "store_id": "fresh-hash",
        "source": kingsway.source.model_copy(update={"id": "999"}),
        "location": Point(lat=kingsway.location.lat + 0.01, lng=kingsway.location.lng),  # ~1.1 km
    })
    [out] = resolve_ids([elsewhere], week1)
    assert (out.store_id, out.matched_by) == ("fresh-hash", "new")


def test_ambiguous_pin_match_mints_a_new_id(week1):
    a = by_name(week1, "Kingsway")
    twin = a.model_copy(update={"store_id": "twin", "source": a.source.model_copy(update={"id": "998"})})
    newcomer = a.model_copy(update={"store_id": "fresh-hash", "source": a.source.model_copy(update={"id": "999"})})
    [out] = resolve_ids([newcomer], [a, twin])  # two earlier stores at the same pin
    assert out.matched_by == "new"


def test_each_earlier_store_is_claimed_once(week1):
    a = by_name(week1, "Kingsway")
    # Store number goes to the first record; the copy can't take it by pin too.
    copy = a.model_copy(update={"store_id": "fresh-hash", "source": a.source.model_copy(update={"id": "999"})})
    out = resolve_ids([a, copy], [a])
    assert [o.matched_by for o in out] == ["store_number", "new"]


def test_whole_second_week_keeps_every_id(week1):
    week2 = [s.model_copy(update={"store_id": f"rehashed-{i}"}) for i, s in enumerate(week1)]
    out = resolve_ids(week2, week1)
    assert [o.store_id for o in out] == [s.store_id for s in week1]


def test_latest_records_remembers_stores_that_skipped_a_week(week1):
    from datetime import date
    r1 = Run(run_date=date(2026, 10, 29), captured_from="t", stores=week1)
    r2 = Run(run_date=date(2026, 11, 5), captured_from="t", stores=week1[:12])
    assert {s.store_id for s in latest_records([r2, r1])} == {s.store_id for s in week1}


def test_run_rejects_duplicate_ids(week1):
    from datetime import date
    dup = week1[1].model_copy(update={"store_id": week1[0].store_id})
    with pytest.raises(ValidationError, match="duplicate store IDs"):
        Run(run_date=date(2026, 10, 29), captured_from="t", stores=[week1[0], dup])
