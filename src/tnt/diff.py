"""Compare two cleaned runs: store events, plus field changes at the same place."""

from dataclasses import dataclass

from tnt.events import events
from tnt.schema import Event, Run

# source is left out: a change in raw formatting that cleans to the same
# record is not a change to the store.
COMPARED = ["banner", "name", "address", "phone", "location", "hours"]


@dataclass
class RunDiff:
    events: list[Event]  # opened, closed, relocated, reopened in the later run
    changed: dict[str, dict[str, tuple]]  # location_id -> field -> (before, after)


def diff_runs(before: Run, after: Run) -> RunDiff:
    # Opened and reopened can't be told apart from two runs alone, so a store
    # that's new relative to `before` is reported as opened.
    evts = [e for e in events([before, after]) if e.run_date == after.run_date]
    a = {r.location_id: r.model_dump(include=set(COMPARED)) for r in before.stores}
    b = {r.location_id: r.model_dump(include=set(COMPARED)) for r in after.stores}
    changed = {}
    for loc in a.keys() & b.keys():
        fields = {f: (a[loc][f], b[loc][f]) for f in COMPARED if a[loc][f] != b[loc][f]}
        if fields:
            changed[loc] = fields
    return RunDiff(evts, changed)
