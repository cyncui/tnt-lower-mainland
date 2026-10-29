"""Runs against the docker compose database; skipped when it isn't up."""

from datetime import date

import psycopg
import pytest

from tnt import db
from tnt.address import Address
from tnt.schema import DayHours, Point, Run, Source, StoreRecord


def _connect():
    try:
        return db.connect()
    except psycopg.OperationalError:
        pytest.skip("Postgres not running (docker compose up -d db)")


def store(sid, name, lat, lng, close="22:00"):
    return StoreRecord(
        store_id=sid, brand="T&T Supermarket", banner="T&T Supermarket", name=name,
        address=Address("1 Test Road", None, "Burnaby", "BC", None), phone=None,
        location=Point(lat=lat, lng=lng), geocode=None,
        hours={"mon": DayHours(open="09:00", close=close)}, hours_notes=[], flags=[],
        source=Source(id=sid, name=name, address="x", phone=None, hours="x", special_hours=None),
    )


def load(conn, run_date, stores):
    db.load(conn, Run(run_date=run_date, captured_from="test", stores=stores))


@pytest.fixture
def conn(monkeypatch):
    conn = _connect()
    # Isolate in a throwaway schema so the real tables are untouched.
    conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    conn.execute("DROP SCHEMA IF EXISTS test CASCADE; CREATE SCHEMA test; SET search_path = test, public")
    yield conn
    conn.rollback()
    conn.execute("DROP SCHEMA test CASCADE")
    conn.commit()
    conn.close()


def test_first_and_last_seen_survive_out_of_order_loads(conn):
    load(conn, date(2026, 11, 5), [store("a", "A", 49.25, -123.0)])
    load(conn, date(2026, 10, 29), [store("a", "A", 49.25, -123.0), store("b", "B", 49.26, -123.0)])
    rows = dict(conn.execute("SELECT store_id, (first_seen, last_seen) FROM stores").fetchall())
    assert rows["a"] == (date(2026, 10, 29), date(2026, 11, 5))
    assert rows["b"] == (date(2026, 10, 29), date(2026, 10, 29))  # gone in the later run


def test_queries_use_meters_and_list_pairs_once(conn):
    load(conn, date(2026, 10, 29), [
        store("a", "Near", 49.2798, -122.7986, close="23:00"),   # at Coquitlam Centre
        store("b", "Close by", 49.2900, -122.7986),               # ~1.1 km north
        store("c", "Far", 49.2000, -123.1000, close="22:00"),     # Vancouver
    ])

    nearest = db.run_query(conn, "nearest_to_coquitlam_centre")
    assert nearest[0]["name"] == "Near" and nearest[0]["meters"] < 50

    pairs = db.run_query(conn, "stores_within_3km")
    assert [(p["store_a"], p["store_b"]) for p in pairs] == [("Near", "Close by")]
    assert 1_000 < pairs[0]["meters"] < 1_300

    late = db.run_query(conn, "open_past_10pm")
    assert [(r["name"], r["closes"]) for r in late] == [("Near", "23:00")]
