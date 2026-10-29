"""Small read API over the loaded runs.

/locations are places (location_id, never moves). /stores/{store_id} is one
brand store across the places it has been. /events is what changed, run by
run.
"""

from datetime import date
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from tnt import db
from tnt.schema import Event, StoreRecord

app = FastAPI(title="T&T in the Lower Mainland")

LOCATION_COLUMNS = "record, first_seen, last_seen, active, ended_reason"
EVENT_COLUMNS = "run_date, type, store_id, location_id, from_location_id"


class LocationOut(StoreRecord):
    first_seen: date
    last_seen: date
    active: bool  # in the most recent run
    ended_reason: Literal["closed", "relocated"] | None


class NearbyLocation(LocationOut):
    meters: int


class StoreOut(BaseModel):
    store_id: str
    locations: list[LocationOut]  # in the order the store was there
    events: list[Event]


def _locations(sql: str, params=None) -> list[dict]:
    """Rows of (record, first_seen, last_seen, active, ended_reason[, meters]) -> response dicts."""
    with db.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for record, first_seen, last_seen, active, ended_reason, *rest in rows:
        item = {**record, "first_seen": first_seen, "last_seen": last_seen, "active": active,
                "ended_reason": ended_reason}
        if rest:
            item["meters"] = round(rest[0])
        out.append(item)
    return out


def _event(row) -> dict:
    return dict(zip(["run_date", "type", "store_id", "location_id", "from_location_id"], row))


@app.get("/locations", response_model=list[LocationOut])
def locations(flagged: bool = False, include_ended: bool = False):
    conditions = []
    if flagged:
        conditions.append("cardinality(flags) > 0")
    if not include_ended:
        conditions.append("active")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return _locations(f"SELECT {LOCATION_COLUMNS} FROM locations {where} ORDER BY city, name")


@app.get("/locations/nearest", response_model=list[NearbyLocation])
def nearest(lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180), limit: int = Query(3, ge=1, le=20)):
    return _locations(
        f"""SELECT {LOCATION_COLUMNS},
                   ST_Distance(geog, ST_MakePoint(%(lng)s, %(lat)s)::geography) AS meters
            FROM location_points WHERE geog IS NOT NULL AND active
            ORDER BY geog <-> ST_MakePoint(%(lng)s, %(lat)s)::geography LIMIT %(limit)s""",
        {"lat": lat, "lng": lng, "limit": limit},
    )


@app.get("/locations/{location_id}", response_model=LocationOut)
def location(location_id: str):
    # Ended locations are still returned, with active=false and the reason,
    # so an old reference resolves instead of 404ing.
    rows = _locations(f"SELECT {LOCATION_COLUMNS} FROM locations WHERE location_id = %s", (location_id,))
    if not rows:
        raise HTTPException(404, "location not found")
    return rows[0]


@app.get("/stores/{store_id}", response_model=StoreOut)
def store(store_id: str):
    with db.connect() as conn:
        evts = [_event(r) for r in conn.execute(
            f"SELECT {EVENT_COLUMNS} FROM store_events WHERE store_id = %s ORDER BY run_date", (store_id,))]
    if not evts:
        raise HTTPException(404, "store not found")
    # Every place the store has been comes from its events: locations.store_id
    # only names the store that was at a place most recently.
    order = []
    for e in evts:
        for lid in (e["from_location_id"], e["location_id"]):
            if lid and lid not in order:
                order.append(lid)
    places = _locations(f"SELECT {LOCATION_COLUMNS} FROM locations WHERE location_id = ANY(%s)", (order,))
    places.sort(key=lambda p: order.index(p["location_id"]))
    return {"store_id": store_id, "locations": places, "events": evts}


@app.get("/events", response_model=list[Event])
def store_events(since: date | None = None,
                 type: Literal["opened", "closed", "relocated", "reopened"] | None = None):
    conditions, params = [], {}
    if since:
        conditions.append("run_date >= %(since)s")
        params["since"] = since
    if type:
        conditions.append("type = %(type)s")
        params["type"] = type
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with db.connect() as conn:
        rows = conn.execute(f"SELECT {EVENT_COLUMNS} FROM store_events {where} "
                            "ORDER BY run_date, type, store_id", params).fetchall()
    return [_event(r) for r in rows]
