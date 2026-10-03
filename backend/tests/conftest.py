import os
from pathlib import Path

import psycopg
import pytest
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


@pytest.fixture
def api(clean_db, monkeypatch):
    """TestClient on an empty test database. Startup schema/admin/bucket steps are skipped:
    the schema is already applied, tests create their own users, and MinIO is never called."""
    monkeypatch.setattr(db, "apply_schema", lambda: None)
    monkeypatch.setattr(db, "seed_admin", lambda email, password: None)
    monkeypatch.setattr(storage, "ensure_bucket", lambda: None)
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
