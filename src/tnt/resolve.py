"""Keep a store's ID across runs.

A hash of the address alone re-keys a store whenever its text changes:
T&T rewords it, a street is renamed, or this repo's parser improves. So each
new record is matched to stores from earlier runs before its hash ID is
used:

1. Same brand and the brand's own store number (T&T's "id" field).
2. Otherwise same brand and banner, with the brand's map pin within
   MATCH_RADIUS_M, and exactly one earlier store that close.

Store-number matches run first for every record, so a pin match can't take
an earlier store that another record matches by number. Each earlier store
is matched at most once. Anything unmatched keeps its hash ID and counts as
new.
"""

from tnt.geocode import haversine_m
from tnt.schema import StoreRecord

MATCH_RADIUS_M = 50


def _distance(a: StoreRecord, b: StoreRecord) -> float | None:
    if a.location is None or b.location is None:
        return None
    return haversine_m(a.location.lat, a.location.lng, b.location.lat, b.location.lng)


def resolve_ids(stores: list[StoreRecord], previous: list[StoreRecord]) -> list[StoreRecord]:
    by_number = {(p.brand, p.source.id): p for p in previous if p.source.id}
    claimed: set[str] = set()
    out: list[StoreRecord | None] = [None] * len(stores)

    for i, s in enumerate(stores):
        p = by_number.get((s.brand, s.source.id)) if s.source.id else None
        if p and p.store_id not in claimed:
            claimed.add(p.store_id)
            out[i] = s.model_copy(update={"store_id": p.store_id, "matched_by": "store_number"})

    for i, s in enumerate(stores):
        if out[i] is not None:
            continue
        near = [p for p in previous
                if p.store_id not in claimed and p.brand == s.brand and p.banner == s.banner
                and (d := _distance(s, p)) is not None and d <= MATCH_RADIUS_M]
        if len(near) == 1:
            claimed.add(near[0].store_id)
            out[i] = s.model_copy(update={"store_id": near[0].store_id, "matched_by": "pin"})
        else:
            out[i] = s.model_copy(update={"matched_by": "new"})
    return out


def latest_records(runs) -> list[StoreRecord]:
    """The most recent record of every store across earlier runs, so a store
    that skipped a week is still matched when it comes back."""
    latest: dict[str, StoreRecord] = {}
    for run in sorted(runs, key=lambda r: r.run_date):
        for s in run.stores:
            latest[s.store_id] = s
    return list(latest.values())
