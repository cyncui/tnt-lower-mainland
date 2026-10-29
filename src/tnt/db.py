"""Postgres/PostGIS loading.

store_snapshots is an append-only log (one row per store per scrape).
stores and store_hours are rebuilt from it on every load, so first_seen /
last_seen are just min/max run_date and loading runs out of order is safe.
"""

import os
from pathlib import Path

import psycopg

from tnt.schema import Run

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://tnt:tnt@localhost:5433/tnt")
SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL)


def init(conn: psycopg.Connection) -> None:
    conn.execute((SQL_DIR / "schema.sql").read_text())


def _hm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def load(conn: psycopg.Connection, run: Run) -> None:
    init(conn)
    with conn.transaction():
        # A run replaces everything stored for its date. Upserting per store
        # would leave rows behind when re-cleaning a day changes its IDs.
        conn.execute("DELETE FROM store_snapshots WHERE run_date = %s", (run.run_date,))
        for r in run.stores:
            conn.execute(
                "INSERT INTO store_snapshots (store_id, run_date, record) VALUES (%s, %s, %s)",
                (r.store_id, run.run_date, r.model_dump_json()),
            )
        rebuild(conn)


def rebuild(conn: psycopg.Connection) -> None:
    conn.execute("TRUNCATE stores CASCADE")
    conn.execute(
        """
        WITH seen AS (
            SELECT store_id, min(run_date) AS first_seen, max(run_date) AS last_seen
            FROM store_snapshots GROUP BY store_id
        ), latest AS (
            SELECT DISTINCT ON (store_id) store_id, record AS r
            FROM store_snapshots ORDER BY store_id, run_date DESC
        )
        INSERT INTO stores
        SELECT l.store_id, r->>'brand', r->>'banner', r->>'name',
               r->'address'->>'street', r->'address'->>'unit', r->'address'->>'city',
               r->'address'->>'province', r->'address'->>'postal_code', r->>'phone',
               CASE WHEN jsonb_typeof(r->'location') = 'object'
                    THEN ST_MakePoint((r->'location'->>'lng')::float8, (r->'location'->>'lat')::float8)::geography END,
               CASE WHEN r->'geocode'->>'precision' = 'building'
                    THEN ST_MakePoint((r->'geocode'->>'lng')::float8, (r->'geocode'->>'lat')::float8)::geography END,
               ARRAY(SELECT jsonb_array_elements_text(r->'flags')),
               r, s.first_seen, s.last_seen,
               s.last_seen = (SELECT max(run_date) FROM store_snapshots)
        FROM latest l JOIN seen s USING (store_id)
        """
    )
    rows = conn.execute("SELECT store_id, record->'hours' FROM stores").fetchall()
    for store_id, hours in rows:
        for day, span in hours.items():
            conn.execute(
                "INSERT INTO store_hours VALUES (%s, %s, %s, %s)",
                (store_id, day, _hm(span["open"]), _hm(span["close"])),
            )


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
