"""The event log: what happened to each brand store between runs.

Derived from the runs alone, by comparing consecutive runs by store_id:

- opened: a store_id seen for the first time;
- reopened: a store_id that was missing from the previous run and is back;
- relocated: a store_id whose location_id changed since its last run;
- closed: a store_id in the previous run and missing from this one.

A location ends when its store closes or relocates away; that's the
location-level view of the same events.
"""

from tnt.schema import Event, Run


def events(runs: list[Run]) -> list[Event]:
    out: list[Event] = []
    last_location: dict[str, str] = {}  # store_id -> location it was last seen at
    previous: set[str] = set()  # store_ids in the previous run
    for run in sorted(runs, key=lambda r: r.run_date):
        current = {s.store_id: s.location_id for s in run.stores}
        for sid, loc in current.items():
            if sid not in last_location:
                out.append(Event(run_date=run.run_date, type="opened", store_id=sid, location_id=loc))
            else:
                if sid not in previous:
                    out.append(Event(run_date=run.run_date, type="reopened", store_id=sid, location_id=loc))
                if last_location[sid] != loc:
                    out.append(Event(run_date=run.run_date, type="relocated", store_id=sid, location_id=loc,
                                     from_location_id=last_location[sid]))
        for sid in previous - current.keys():
            out.append(Event(run_date=run.run_date, type="closed", store_id=sid, location_id=last_location[sid]))
        last_location.update(current)
        previous = set(current)
    return out


def ended_reasons(evts: list[Event]) -> dict[str, str]:
    """Why each location ended, for locations that did: 'relocated' or 'closed'.
    A later event at the same location (a reopening) clears it."""
    reasons: dict[str, str] = {}
    for e in sorted(evts, key=lambda e: e.run_date):
        if e.type == "relocated":
            reasons[e.from_location_id] = "relocated"
            reasons.pop(e.location_id, None)
        elif e.type == "closed":
            reasons[e.location_id] = "closed"
        else:
            reasons.pop(e.location_id, None)
    return reasons
