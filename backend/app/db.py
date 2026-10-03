"""Database connection helpers (plain SQL with psycopg, no ORM)."""

import logging
from pathlib import Path

import psycopg

from app import config, security

logger = logging.getLogger(__name__)


def get_connection() -> psycopg.Connection:
    return psycopg.connect(
        dbname=config.POSTGRES_DB,
        user=config.POSTGRES_USER,
        password=config.POSTGRES_PASSWORD,
        host=config.POSTGRES_HOST,
        port=config.POSTGRES_PORT,
        connect_timeout=3,
    )


def check_db() -> None:
    """Raise if the database cannot answer a trivial query."""
    with get_connection() as conn:
        conn.execute("SELECT 1")


def apply_schema() -> None:
    """Run schema.sql then seed.sql. Both are safe to run on every startup."""
    with get_connection() as conn:
        for name in ("schema.sql", "seed.sql"):
            conn.execute(Path(config.DB_DIR, name).read_text())
    logger.info("Applied schema and seed from %s", config.DB_DIR)


def seed_admin(email: str, password: str) -> None:
    """Create the first admin if that email doesn't exist yet. Never overwrites."""
    email = email.strip().lower()
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
        if existing:
            logger.info("Admin %s already exists; leaving it unchanged", email)
            return
        conn.execute(
            "INSERT INTO users (email, password_hash, role) VALUES (%s, %s, 'admin')",
            (email, security.hash_password(password)),
        )
    logger.info("Created admin %s", email)
