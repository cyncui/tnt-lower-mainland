"""Postgres/PostGIS: a queryable copy of the cleaned runs.

The cleaned runs in data/clean/ are the history. load() drops the tables
and rebuilds them from every run, so loading is the same however many times
or in whatever order runs arrive, and schema changes need no migration.
At much larger scale you'd append runs incrementally instead; with a few
runs a full rebuild is simpler and can't drift from the files.
"""

import os
from pathlib import Path

import psycopg

from tnt.events import ended_reasons, events
from tnt.schema import Run

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://tnt:tnt@localhost:5433/tnt")
SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL)


def _hm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def load(conn: psycopg.Connection, runs: list[Run]) -> None:
    with conn.transaction():
        conn.execute((SQL_DIR / "schema.sql").read_text())
        for run in runs:
            for r in run.stores:
                conn.execute("INSERT INTO location_snapshots VALUES (%s, %s, %s)",
                             (r.location_id, run.run_date, r.model_dump_json()))
        _rebuild_locations(conn)
        evts = events(runs)
        for e in evts:
            conn.execute("INSERT INTO store_events VALUES (%s, %s, %s, %s, %s)",
                         (e.run_date, e.type, e.store_id, e.location_id, e.from_location_id))
        for loc, reason in ended_reasons(evts).items():
            conn.execute("UPDATE locations SET ended_reason = %s WHERE location_id = %s AND NOT active",
                         (reason, loc))


def _rebuild_locations(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        WITH seen AS (
            SELECT location_id, min(run_date) AS first_seen, max(run_date) AS last_seen
            FROM location_snapshots GROUP BY location_id
        ), latest AS (
            SELECT DISTINCT ON (location_id) location_id, record AS r
            FROM location_snapshots ORDER BY location_id, run_date DESC
        )
        INSERT INTO locations
        SELECT l.location_id, r->>'store_id', r->>'brand', r->>'banner', r->>'name',
               r->'address'->>'street', r->'address'->>'unit', r->'address'->>'city',
               r->'address'->>'province', r->'address'->>'postal_code', r->>'phone',
               CASE WHEN jsonb_typeof(r->'location') = 'object'
                    THEN ST_MakePoint((r->'location'->>'lng')::float8, (r->'location'->>'lat')::float8)::geography END,
               CASE WHEN r->'geocode'->>'precision' = 'building'
                    THEN ST_MakePoint((r->'geocode'->>'lng')::float8, (r->'geocode'->>'lat')::float8)::geography END,
               ARRAY(SELECT jsonb_array_elements_text(r->'flags')),
               r, s.first_seen, s.last_seen,
               s.last_seen = (SELECT max(run_date) FROM location_snapshots),
               NULL
        FROM latest l JOIN seen s USING (location_id)
        """
    )
    rows = conn.execute("SELECT location_id, record->'hours' FROM locations").fetchall()
    for location_id, hours in rows:
        for day, span in hours.items():
            conn.execute("INSERT INTO location_hours VALUES (%s, %s, %s, %s)",
                         (location_id, day, _hm(span["open"]), _hm(span["close"])))


def named_queries() -> dict[str, str]:
    """Split sql/queries.sql on '-- name:' markers."""
    out, name, buf = {}, None, []
    for line in (SQL_DIR / "queries.sql").read_text().splitlines():
        if line.startswith("-- name:"):
            if name:
                out[name] = "\n".join(buf).strip()
            name, buf = line.split(":", 1)[1].strip(), []
        else:
            buf.append(line)
    if name:
        out[name] = "\n".join(buf).strip()
    return out


def run_query(conn: psycopg.Connection, name: str) -> list[dict]:
    cur = conn.execute(named_queries()[name])
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
