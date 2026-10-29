"""Runs against the docker compose database; skipped when it isn't up."""

from datetime import date

import psycopg
import pytest

from tnt import db
from tnt.address import Address
from tnt.schema import DayHours, Point, Run, Source, StoreRecord

OCT29, NOV5 = date(2026, 10, 29), date(2026, 11, 5)


def _connect():
    try:
        return db.connect()
    except psycopg.OperationalError:
        pytest.skip("Postgres not running (docker compose up -d db)")


def loc(n: int) -> str:
    return f"loc_{n:016x}"


def sto(n: int) -> str:
    return f"sto_{n:016x}"


def store(n, name, lat, lng, close="22:00", location=None):
    return StoreRecord(
        location_id=location or loc(n), store_id=sto(n), brand="T&T Supermarket", banner="T&T Supermarket",
        name=name, address=Address("1 Test Road", None, "Burnaby", "BC", None), phone=None,
        location=Point(lat=lat, lng=lng), geocode=None,
        hours={"mon": DayHours(open="09:00", close=close)}, hours_notes=[], flags=[],
        source=Source(id=str(n), name=name, address="x", phone=None, hours="x", special_hours=None),
    )


def run(day, *stores):
    return Run(run_date=day, captured_from="test", stores=list(stores))


@pytest.fixture
def conn():
    conn = _connect()
    # Isolate in a throwaway schema so the real tables are untouched.
    conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    conn.execute("DROP SCHEMA IF EXISTS test CASCADE; CREATE SCHEMA test; SET search_path = test, public")
    yield conn
    # Nothing is committed (psycopg keeps one transaction open and
    # conn.transaction() blocks inside it are savepoints), so a rollback
    # removes the schema and everything the test wrote.
    conn.rollback()
    conn.close()


def rows(conn, sql):
    return conn.execute(sql).fetchall()


def test_seen_dates_and_active_dont_depend_on_load_order(conn):
    a, b = store(1, "A", 49.25, -123.0), store(2, "B", 49.26, -123.0)
    db.load(conn, [run(NOV5, a), run(OCT29, a, b)])  # out of order on purpose
    got = {r[0]: r[1:] for r in rows(conn, "SELECT location_id, first_seen, last_seen, active, ended_reason FROM locations")}
    assert got == {loc(1): (OCT29, NOV5, True, None), loc(2): (OCT29, OCT29, False, "closed")}


def test_relocation_ends_the_old_location_and_keeps_the_store(conn):
    before = store(1, "Lougheed", 49.25, -123.0)
    after = store(1, "Lougheed", 49.27, -123.0, location=loc(99))  # same store_id, new place
    db.load(conn, [run(OCT29, before), run(NOV5, after)])
    got = {r[0]: r[1:] for r in rows(conn, "SELECT location_id, store_id, active, ended_reason FROM locations")}
    assert got == {loc(1): (sto(1), False, "relocated"), loc(99): (sto(1), True, None)}
    assert rows(conn, "SELECT run_date, type, location_id, from_location_id FROM store_events ORDER BY run_date") == [
        (OCT29, "opened", loc(1), None), (NOV5, "relocated", loc(99), loc(1))]


def test_reloading_rebuilds_from_the_runs_given(conn):
    db.load(conn, [run(OCT29, store(1, "A", 49.25, -123.0))])
    db.load(conn, [run(OCT29, store(2, "A", 49.25, -123.0))])  # the day re-cleaned with new IDs
    assert rows(conn, "SELECT location_id FROM location_snapshots") == [(loc(2),)]


def test_ended_locations_drop_out_of_queries(conn):
    db.load(conn, [run(OCT29, store(1, "Near", 49.2798, -122.7986, close="23:00"), store(2, "Close by", 49.2900, -122.7986)),
                   run(NOV5, store(2, "Close by", 49.2900, -122.7986))])  # "Near" closed
    assert db.run_query(conn, "nearest_to_coquitlam_centre")[0]["name"] == "Close by"
    assert db.run_query(conn, "stores_within_3km") == []
    assert db.run_query(conn, "open_past_10pm") == []


def test_queries_use_meters_and_list_pairs_once(conn):
    db.load(conn, [run(OCT29,
        store(1, "Near", 49.2798, -122.7986, close="23:00"),   # at Coquitlam Centre
        store(2, "Close by", 49.2900, -122.7986),               # ~1.1 km north
        store(3, "Far", 49.2000, -123.1000, close="22:00"),     # Vancouver
    )])
    nearest = db.run_query(conn, "nearest_to_coquitlam_centre")
    assert nearest[0]["name"] == "Near" and nearest[0]["meters"] < 50

    pairs = db.run_query(conn, "stores_within_3km")
    assert [(p["store_a"], p["store_b"]) for p in pairs] == [("Near", "Close by")]
    assert 1_000 < pairs[0]["meters"] < 1_300

    late = db.run_query(conn, "open_past_10pm")
    assert [(r["name"], r["days"], r["closes"]) for r in late] == [("Near", "mon", "23:00")]
