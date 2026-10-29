"""API responses use the StoreRecord shape. The database is faked here;
tests/test_db.py covers the SQL against a real PostGIS."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tnt import api, scrape
from tnt.pipeline import run

FIXTURE = Path(__file__).parent / "fixtures" / "tnt_bc_2026-10-29.json"
OCT29, NOV5 = date(2026, 10, 29), date(2026, 11, 5)


class FakeConn:
    """Returns the queued result sets in order, and records the SQL it saw."""

    def __init__(self, *results):
        self.results, self.sql = list(results), []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self.current = self.results.pop(0) if self.results else []
        return self

    def fetchall(self):
        return self.current

    def __iter__(self):
        return iter(self.current)


@pytest.fixture
def records(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape, "RAW_DIR", tmp_path)
    return run(scrape.import_capture(FIXTURE)).stores


def fake(monkeypatch, *results):
    conn = FakeConn(*results)
    monkeypatch.setattr(api.db, "connect", lambda: conn)
    return conn


def row(r, active=True, ended=None, *extra):
    return (r.model_dump(mode="json"), OCT29, NOV5, active, ended, *extra)


def test_locations_returns_records_with_seen_dates(records, monkeypatch):
    fake(monkeypatch, [row(r) for r in records])
    body = TestClient(api.app).get("/locations").json()
    assert len(body) == 13
    assert body[0]["location_id"].startswith("loc_") and body[0]["store_id"].startswith("sto_")
    assert (body[0]["first_seen"], body[0]["last_seen"], body[0]["active"]) == ("2026-10-29", "2026-11-05", True)


def test_locations_hides_ended_unless_asked(monkeypatch):
    conn = fake(monkeypatch, [], [])
    client = TestClient(api.app)
    client.get("/locations")
    client.get("/locations", params={"include_ended": "true"})
    assert "WHERE active" in conn.sql[0] and "WHERE" not in conn.sql[1]


def test_nearest_adds_meters(records, monkeypatch):
    fake(monkeypatch, [row(records[0], True, None, 742.6)])
    body = TestClient(api.app).get("/locations/nearest", params={"lat": 49.28, "lng": -122.80, "limit": 1}).json()
    assert body[0]["meters"] == 743


def test_store_lists_every_place_it_has_been(records, monkeypatch):
    old, new = records[0], records[1].model_copy(update={"store_id": records[0].store_id})
    events = [(OCT29, "opened", old.store_id, old.location_id, None),
              (NOV5, "relocated", old.store_id, new.location_id, old.location_id)]
    fake(monkeypatch, events, [row(new), row(old, False, "relocated")])  # DB order needn't match
    body = TestClient(api.app).get(f"/stores/{old.store_id}").json()
    assert [l["location_id"] for l in body["locations"]] == [old.location_id, new.location_id]
    assert body["locations"][0]["ended_reason"] == "relocated"
    assert [e["type"] for e in body["events"]] == ["opened", "relocated"]


def test_unknown_ids_are_404(monkeypatch):
    fake(monkeypatch, [], [])
    client = TestClient(api.app)
    assert client.get("/locations/loc_nope").status_code == 404
    assert client.get("/stores/sto_nope").status_code == 404
