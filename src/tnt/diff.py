"""Compare two cleaned runs: which stores appeared, disappeared or changed."""

from dataclasses import dataclass

from tnt.schema import StoreRecord

# source is left out: a change in raw formatting that cleans to the same
# record is not a change to the store.
COMPARED = ["banner", "name", "address", "phone", "location", "hours"]


@dataclass
class RunDiff:
    added: list[str]
    removed: list[str]
    changed: dict[str, dict[str, tuple]]


def diff_runs(before: list[StoreRecord], after: list[StoreRecord]) -> RunDiff:
    a = {r.store_id: r.model_dump(include=set(COMPARED)) for r in before}
    b = {r.store_id: r.model_dump(include=set(COMPARED)) for r in after}
    changed = {}
    for sid in a.keys() & b.keys():
        fields = {f: (a[sid][f], b[sid][f]) for f in COMPARED if a[sid][f] != b[sid][f]}
        if fields:
            changed[sid] = fields
    return RunDiff(sorted(b.keys() - a.keys()), sorted(a.keys() - b.keys()), changed)
