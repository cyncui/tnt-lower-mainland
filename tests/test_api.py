"""API responses use the StoreRecord shape. The database is faked here;
tests/test_db.py covers the SQL against a real PostGIS."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tnt import api, scrape
from tnt.pipeline import run

FIXTURE = Path(__file__).parent / "fixtures" / "tnt_bc_2026-10-29.json"


class FakeConn:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        return self

    def fetchall(self):
        return self.rows


@pytest.fixture
def records(tmp_path, monkeypatch):
    monkeypatch.setattr(scrape, "RAW_DIR", tmp_path)
    return run(scrape.import_capture(FIXTURE)).stores


def test_stores_returns_records_with_seen_dates(records, monkeypatch):
    rows = [(r.model_dump(mode="json"), date(2026, 10, 29), date(2026, 11, 5), True) for r in records]
    monkeypatch.setattr(api.db, "connect", lambda: FakeConn(rows))
    body = TestClient(api.app).get("/stores").json()
    assert len(body) == 13
    assert body[0]["address"]["city"] and body[0]["source"]["address"]
    assert body[0]["first_seen"] == "2026-10-29" and body[0]["last_seen"] == "2026-11-05"
    assert body[0]["active"] is True


def test_nearest_adds_meters(records, monkeypatch):
    rows = [(records[0].model_dump(mode="json"), date(2026, 10, 29), date(2026, 10, 29), True, 742.6)]
    monkeypatch.setattr(api.db, "connect", lambda: FakeConn(rows))
    body = TestClient(api.app).get("/stores/nearest", params={"lat": 49.28, "lng": -122.80, "limit": 1}).json()
    assert body[0]["meters"] == 743


def test_stores_hides_closed_unless_asked(records, monkeypatch):
    seen_sql = []

    class Recording(FakeConn):
        def execute(self, sql, params=None):
            seen_sql.append(sql)
            return self

    monkeypatch.setattr(api.db, "connect", lambda: Recording([]))
    client = TestClient(api.app)
    client.get("/stores")
    client.get("/stores", params={"include_closed": "true"})
    assert "WHERE active" in seen_sql[0] and "active" not in seen_sql[1].split("FROM")[1]


def test_unknown_store_is_404(monkeypatch):
    monkeypatch.setattr(api.db, "connect", lambda: FakeConn([]))
    assert TestClient(api.app).get("/stores/nope").status_code == 404
