import pytest
from fastapi.testclient import TestClient

from app import db, main, storage


def ok():
    return None


def fail():
    raise RuntimeError("down")


@pytest.fixture
def client(monkeypatch):
    # Skip the real bucket creation at startup.
    monkeypatch.setattr(storage, "ensure_bucket", ok)
    with TestClient(main.app) as c:
        yield c


def test_health_ok(client, monkeypatch):
    monkeypatch.setattr(db, "check_db", ok)
    monkeypatch.setattr(storage, "check_storage", ok)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "minio": "ok"}


def test_health_db_down(client, monkeypatch):
    monkeypatch.setattr(db, "check_db", fail)
    monkeypatch.setattr(storage, "check_storage", ok)

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": "error", "minio": "ok"}


def test_health_minio_down(client, monkeypatch):
    monkeypatch.setattr(db, "check_db", ok)
    monkeypatch.setattr(storage, "check_storage", fail)

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "db": "ok", "minio": "error"}
