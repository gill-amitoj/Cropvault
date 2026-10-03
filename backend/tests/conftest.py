import io
import os
from pathlib import Path

import psycopg
import pytest
from PIL import Image
from psycopg import sql

# Dummy settings so app.config can be imported without a real .env.
# Unit tests never talk to real MinIO.
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("MINIO_ROOT_USER", "test")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test")
os.environ.setdefault("ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-long-enough-for-hs256-signing")
# repo/db, both in Docker (/app/tests -> /db) and in CI (backend/tests -> db)
os.environ.setdefault("DB_DIR", str(Path(__file__).resolve().parents[2] / "db"))

# Always use a separate test database so tests never touch dev data.
os.environ["POSTGRES_DB"] = os.environ.get("TEST_POSTGRES_DB", "cropvault_test")

from fastapi.testclient import TestClient  # noqa: E402

from app import config, db, main, security, storage  # noqa: E402  (after the env setup)


@pytest.fixture(scope="session")
def test_database():
    """Create the test database if needed and apply the schema once per test run."""
    with psycopg.connect(
        dbname="postgres",
        user=config.POSTGRES_USER,
        password=config.POSTGRES_PASSWORD,
        host=config.POSTGRES_HOST,
        port=config.POSTGRES_PORT,
        autocommit=True,
    ) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (config.POSTGRES_DB,)
        ).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(config.POSTGRES_DB)))
    db.apply_schema()


@pytest.fixture
def clean_db(test_database):
    """Empty every table before a test. Refuses to run on a non-test database."""
    assert config.POSTGRES_DB.endswith("_test"), "refusing to truncate a non-test database"
    with db.get_connection() as conn:
        conn.execute(
            "TRUNCATE audit_log, annotations, images, experiments, users RESTART IDENTITY CASCADE"
        )


class FakeStorage:
    """In-memory stand-in for app.storage. Unit tests never call real MinIO."""

    def __init__(self):
        self.objects = {}  # key -> (bytes, content_type)
        self.fail_put_on = None  # key prefix that makes put_object fail
        self.fail_delete = False

    def put_object(self, key, data, content_type):
        if self.fail_put_on and key.startswith(self.fail_put_on):
            raise ConnectionError("fake storage put failure")
        self.objects[key] = (data, content_type)

    def open_object(self, key):
        if key not in self.objects:
            raise storage.ObjectNotFound(key)
        return iter([self.objects[key][0]])

    def delete_object(self, key):
        if self.fail_delete:
            raise ConnectionError("fake storage delete failure")
        self.objects.pop(key, None)


@pytest.fixture
def fake_storage(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr(storage, "put_object", fake.put_object)
    monkeypatch.setattr(storage, "open_object", fake.open_object)
    monkeypatch.setattr(storage, "delete_object", fake.delete_object)
    monkeypatch.setattr(storage, "ensure_bucket", lambda: None)
    return fake


@pytest.fixture
def api(clean_db, fake_storage, monkeypatch):
    """TestClient on an empty test database with fake storage. Startup schema/admin steps are
    skipped: the schema is already applied and tests create their own users."""
    monkeypatch.setattr(db, "apply_schema", lambda: None)
    monkeypatch.setattr(db, "seed_user", lambda email, password, role: None)
    with TestClient(main.app) as client:
        yield client


TEST_PASSWORD = "password123"


def make_user(role="researcher", email=None, is_active=True):
    """Insert a user directly and return it with a ready-to-use auth header."""
    email = email or f"{role}@example.com"
    with db.get_connection() as conn:
        user = conn.execute(
            """INSERT INTO users (email, password_hash, role, is_active)
               VALUES (%s, %s, %s, %s) RETURNING id, email, role""",
            (email, security.hash_password(TEST_PASSWORD), role, is_active),
        ).fetchone()
    user["headers"] = {"Authorization": f"Bearer {security.create_token(user['id'])}"}
    return user


def image_bytes(fmt="JPEG", size=(640, 480), color=(30, 120, 40), mode="RGB", exif=None):
    """Build a real image in memory. Change `color` to get different bytes (different sha256)."""
    img = Image.new(mode, size, color)
    buffer = io.BytesIO()
    kwargs = {"exif": exif} if exif is not None else {}
    img.save(buffer, fmt, **kwargs)
    return buffer.getvalue()


def upload(api, user, data, filename="leaf.jpg", content_type="image/jpeg", **fields):
    return api.post(
        "/api/images",
        files={"file": (filename, data, content_type)},
        data=fields,
        headers=user["headers"],
    )


def make_experiment(code="EXP-2026-001", title="Test experiment"):
    with db.get_connection() as conn:
        return conn.execute(
            "INSERT INTO experiments (code, title) VALUES (%s, %s) RETURNING id, code",
            (code, title),
        ).fetchone()
