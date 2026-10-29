"""Small read API over the loaded stores. Responses are StoreRecords."""

from datetime import date

from fastapi import FastAPI, HTTPException, Query

from tnt import db
from tnt.schema import StoreRecord

app = FastAPI(title="T&T in the Lower Mainland")


class StoreOut(StoreRecord):
    first_seen: date
    last_seen: date


class NearbyStore(StoreOut):
    meters: int


def _rows(sql: str, params=None) -> list[dict]:
    """Rows of (record, first_seen, last_seen[, meters]) -> response dicts."""
    with db.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for record, first_seen, last_seen, *rest in rows:
        item = {**record, "first_seen": first_seen, "last_seen": last_seen}
        if rest:
            item["meters"] = round(rest[0])
        out.append(item)
    return out


@app.get("/stores", response_model=list[StoreOut])
def stores(flagged: bool = False):
    where = "WHERE cardinality(flags) > 0" if flagged else ""
    return _rows(f"SELECT record, first_seen, last_seen FROM stores {where} ORDER BY city, name")


@app.get("/stores/nearest", response_model=list[NearbyStore])
def nearest(lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180), limit: int = Query(3, ge=1, le=20)):
    return _rows(
        """SELECT record, first_seen, last_seen,
                  ST_Distance(geog, ST_MakePoint(%(lng)s, %(lat)s)::geography) AS meters
           FROM store_locations WHERE geog IS NOT NULL
           ORDER BY geog <-> ST_MakePoint(%(lng)s, %(lat)s)::geography LIMIT %(limit)s""",
        {"lat": lat, "lng": lng, "limit": limit},
    )


@app.get("/stores/{store_id}", response_model=StoreOut)
def store(store_id: str):
    rows = _rows("SELECT record, first_seen, last_seen FROM stores WHERE store_id = %s", (store_id,))
    if not rows:
        raise HTTPException(404, "store not found")
    return rows[0]
