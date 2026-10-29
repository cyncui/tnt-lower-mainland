"""Compare two cleaned runs: which stores appeared, disappeared or changed."""

from dataclasses import dataclass

COMPARED = ["name", "street", "unit", "city", "postal_code", "hours", "lat", "lng"]


@dataclass
class RunDiff:
    added: list[str]
    removed: list[str]
    changed: dict[str, dict[str, tuple]]


def diff_runs(before: list[dict], after: list[dict]) -> RunDiff:
    a = {r["store_id"]: r for r in before}
    b = {r["store_id"]: r for r in after}
    changed = {}
    for sid in a.keys() & b.keys():
        fields = {f: (a[sid].get(f), b[sid].get(f)) for f in COMPARED if a[sid].get(f) != b[sid].get(f)}
        if fields:
            changed[sid] = fields
    return RunDiff(sorted(b.keys() - a.keys()), sorted(a.keys() - b.keys()), changed)
