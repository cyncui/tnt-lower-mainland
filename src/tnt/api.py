"""Small read API over the loaded stores."""

from fastapi import FastAPI, HTTPException, Query

from tnt import db

app = FastAPI(title="T&T in the Lower Mainland")

STORE_COLUMNS = """store_id, name, street, unit, city, province, postal_code, hours, flags,
    first_seen, last_seen, ST_Y(geog::geometry) AS lat, ST_X(geog::geometry) AS lng"""


@app.get("/stores")
def stores(flagged: bool = False):
    sql = f"SELECT {STORE_COLUMNS} FROM store_locations"
    if flagged:
        sql += " WHERE cardinality(flags) > 0"
    with db.connect() as conn:
        cur = conn.execute(sql + " ORDER BY city, name")
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


@app.get("/stores/nearest")
def nearest(lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180), limit: int = Query(3, ge=1, le=20)):
    with db.connect() as conn:
        cur = conn.execute(
            f"""SELECT {STORE_COLUMNS},
                       round(ST_Distance(geog, ST_MakePoint(%(lng)s, %(lat)s)::geography)) AS meters
                FROM store_locations WHERE geog IS NOT NULL
                ORDER BY geog <-> ST_MakePoint(%(lng)s, %(lat)s)::geography LIMIT %(limit)s""",
            {"lat": lat, "lng": lng, "limit": limit},
        )
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


@app.get("/stores/{store_id}")
def store(store_id: str):
    with db.connect() as conn:
        cur = conn.execute(f"SELECT {STORE_COLUMNS} FROM store_locations WHERE store_id = %s", (store_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, "store not found")
        return dict(zip([c.name for c in cur.description], row))
