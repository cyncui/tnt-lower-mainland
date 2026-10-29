"""Small read API over the loaded stores. Responses are StoreRecords."""

from datetime import date

from fastapi import FastAPI, HTTPException, Query

from tnt import db
from tnt.schema import StoreRecord

app = FastAPI(title="T&T in the Lower Mainland")


class StoreOut(StoreRecord):
    first_seen: date
    last_seen: date
    active: bool  # in the most recent run


class NearbyStore(StoreOut):
    meters: int


def _rows(sql: str, params=None) -> list[dict]:
    """Rows of (record, first_seen, last_seen, active[, meters]) -> response dicts."""
    with db.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for record, first_seen, last_seen, active, *rest in rows:
        item = {**record, "first_seen": first_seen, "last_seen": last_seen, "active": active}
        if rest:
            item["meters"] = round(rest[0])
        out.append(item)
    return out


@app.get("/stores", response_model=list[StoreOut])
def stores(flagged: bool = False, include_closed: bool = False):
    conditions = []
    if flagged:
        conditions.append("cardinality(flags) > 0")
    if not include_closed:
        conditions.append("active")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return _rows(f"SELECT record, first_seen, last_seen, active FROM stores {where} ORDER BY city, name")


@app.get("/stores/nearest", response_model=list[NearbyStore])
def nearest(lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180), limit: int = Query(3, ge=1, le=20)):
    return _rows(
        """SELECT record, first_seen, last_seen, active,
                  ST_Distance(geog, ST_MakePoint(%(lng)s, %(lat)s)::geography) AS meters
           FROM store_locations WHERE geog IS NOT NULL AND active
           ORDER BY geog <-> ST_MakePoint(%(lng)s, %(lat)s)::geography LIMIT %(limit)s""",
        {"lat": lat, "lng": lng, "limit": limit},
    )


@app.get("/stores/{store_id}", response_model=StoreOut)
def store(store_id: str):
    # Closed stores are still returned by ID, with active=false, so an old
    # reference resolves instead of 404ing.
    rows = _rows("SELECT record, first_seen, last_seen, active FROM stores WHERE store_id = %s", (store_id,))
    if not rows:
        raise HTTPException(404, "store not found")
    return rows[0]
