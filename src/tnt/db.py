"""Postgres/PostGIS loading.

store_snapshots is an append-only log (one row per store per scrape).
stores and store_hours are rebuilt from it on every load, so first_seen /
last_seen are just min/max run_date and loading runs out of order is safe.
"""

import json
import os
from datetime import date
from pathlib import Path

import psycopg

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://tnt:tnt@localhost:5433/tnt")
SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def connect() -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL)


def init(conn: psycopg.Connection) -> None:
    conn.execute((SQL_DIR / "schema.sql").read_text())


def _hm(text: str) -> int:
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def load(conn: psycopg.Connection, records: list[dict], run_date: date) -> None:
    init(conn)
    with conn.transaction():
        for r in records:
            conn.execute(
                """INSERT INTO store_snapshots (store_id, run_date, record) VALUES (%s, %s, %s)
                   ON CONFLICT (store_id, run_date) DO UPDATE SET record = EXCLUDED.record""",
                (r["store_id"], run_date, json.dumps(r)),
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
        SELECT l.store_id, r->>'brand', r->>'name', r->>'street', r->>'unit', r->>'city',
               r->>'province', r->>'postal_code', r->>'raw_address', r->>'raw_hours', r->'hours',
               CASE WHEN r->>'lng' IS NOT NULL
                    THEN ST_MakePoint((r->>'lng')::float8, (r->>'lat')::float8)::geography END,
               CASE WHEN r->>'geocoded_lng' IS NOT NULL
                    THEN ST_MakePoint((r->>'geocoded_lng')::float8, (r->>'geocoded_lat')::float8)::geography END,
               ARRAY(SELECT jsonb_array_elements_text(r->'flags')),
               s.first_seen, s.last_seen
        FROM latest l JOIN seen s USING (store_id)
        """
    )
    rows = conn.execute("SELECT store_id, hours FROM stores").fetchall()
    for store_id, hours in rows:
        for day, (open_, close) in hours.items():
            conn.execute(
                "INSERT INTO store_hours VALUES (%s, %s, %s, %s)",
                (store_id, day, _hm(open_), _hm(close)),
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
