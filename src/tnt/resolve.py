"""Carry IDs from earlier runs, and tell relocations from everything else.

Each new record arrives with freshly hashed IDs (ids.py). Before those are
used, it's matched against the latest record of every location in earlier
runs:

1. Same brand and the brand's own store number (T&T's "id"). Then:
   - pin within SAME_PLACE_M, or no pins to compare: the same place, so both
     IDs carry over;
   - pin moved further AND the address changed: a relocation. store_id
     carries over, the new place keeps its fresh location_id, and
     relocated_from points at the old one;
   - pin moved further, same address: the brand corrected its pin. Same
     place, flagged pin_moved for a person to check.
2. Otherwise same brand and banner, pin within PIN_MATCH_M, and exactly one
   earlier location that close: the same place.
3. Otherwise a relocation a person confirmed in review/relocations.json.
4. Otherwise new. If a store with the same name disappeared within
   CANDIDATE_RADIUS_M in the previous run, it's flagged possible_relocation
   with that location as the candidate, but not linked.

Rules run in that order across all records, so a weaker rule can't take an
earlier location that a stronger one matches. Each earlier location and each
store_id is matched at most once.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from tnt.geocode import haversine_m
from tnt.ids import address_key
from tnt.schema import Run, StoreRecord

SAME_PLACE_M = 150  # a big mall is ~300 m across; pins inside one usually agree to this
PIN_MATCH_M = 50
CANDIDATE_RADIUS_M = 5_000
DECISIONS = Path("review/relocations.json")


@dataclass
class History:
    latest: list[StoreRecord]  # latest record of every location, least recently seen first
    last_run: set[str]  # location_ids in the most recent earlier run

    @classmethod
    def from_runs(cls, runs: list[Run]) -> "History":
        seen: dict[str, tuple] = {}
        for run in sorted(runs, key=lambda r: r.run_date):
            for s in run.stores:
                seen[s.location_id] = (run.run_date, s)
        latest = [s for _, s in sorted(seen.values(), key=lambda pair: pair[0])]
        last = max(runs, key=lambda r: r.run_date) if runs else None
        return cls(latest, {s.location_id for s in last.stores} if last else set())


def load_decisions(path: Path = DECISIONS) -> dict[str, str]:
    """Confirmed relocations as {new location_id: old location_id}."""
    if not path.exists():
        return {}
    return {d["to"]: d["from"] for d in json.loads(path.read_text())["relocations"]}


def _distance(a: StoreRecord, b: StoreRecord) -> float | None:
    if a.location is None or b.location is None:
        return None
    return haversine_m(a.location.lat, a.location.lng, b.location.lat, b.location.lng)


def resolve_ids(stores: list[StoreRecord], history: History, decisions: dict[str, str] | None = None) -> list[StoreRecord]:
    decisions = decisions or {}
    by_location = {p.location_id: p for p in history.latest}
    by_number = {}
    for p in history.latest:  # least recently seen first, so the store's current location wins
        if p.source.id:
            by_number[(p.brand, p.source.id)] = p
    claimed: set[str] = set()  # earlier location_ids
    claimed_stores: set[str] = set()
    out: list[StoreRecord | None] = [None] * len(stores)

    def take(p: StoreRecord) -> None:
        claimed.add(p.location_id)
        claimed_stores.add(p.store_id)

    def free(p: StoreRecord | None) -> bool:
        return p is not None and p.location_id not in claimed and p.store_id not in claimed_stores

    # 1. Brand store number.
    for i, s in enumerate(stores):
        p = by_number.get((s.brand, s.source.id)) if s.source.id else None
        if not free(p):
            continue
        take(p)
        d = _distance(s, p)
        if d is None or d <= SAME_PLACE_M:
            out[i] = s.model_copy(update={"location_id": p.location_id, "store_id": p.store_id,
                                          "matched_by": "store_number"})
        elif address_key(s.address) != address_key(p.address):
            out[i] = s.model_copy(update={"store_id": p.store_id, "matched_by": "store_number",
                                          "relocated_from": p.location_id, "flags": s.flags + ["relocated"]})
        else:
            out[i] = s.model_copy(update={"location_id": p.location_id, "store_id": p.store_id,
                                          "matched_by": "store_number", "flags": s.flags + ["pin_moved"]})

    # 2. Map pin.
    for i, s in enumerate(stores):
        if out[i] is not None:
            continue
        near = [p for p in history.latest
                if free(p) and p.brand == s.brand and p.banner == s.banner
                and (d := _distance(s, p)) is not None and d <= PIN_MATCH_M]
        if len(near) == 1:
            take(near[0])
            out[i] = s.model_copy(update={"location_id": near[0].location_id, "store_id": near[0].store_id,
                                          "matched_by": "pin"})

    # 3. Relocations a person confirmed.
    for i, s in enumerate(stores):
        if out[i] is not None:
            continue
        p = by_location.get(decisions.get(s.location_id, ""))
        if free(p):
            take(p)
            out[i] = s.model_copy(update={"store_id": p.store_id, "matched_by": "review",
                                          "relocated_from": p.location_id, "flags": s.flags + ["relocated"]})

    # 4. New, with a candidate if one just disappeared nearby.
    for i, s in enumerate(stores):
        if out[i] is not None:
            continue
        gone = [p for p in history.latest
                if p.location_id in history.last_run and free(p) and p.brand == s.brand
                and p.banner == s.banner and p.name.lower() == s.name.lower()
                and (d := _distance(s, p)) is not None and d <= CANDIDATE_RADIUS_M]
        if len(gone) == 1:
            out[i] = s.model_copy(update={"matched_by": "new", "relocation_candidate": gone[0].location_id,
                                          "flags": s.flags + ["possible_relocation"]})
        else:
            out[i] = s.model_copy(update={"matched_by": "new"})
    return out
