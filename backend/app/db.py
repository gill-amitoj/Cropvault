"""Database connection helpers (plain SQL with psycopg, no ORM)."""

import psycopg

from app import config


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
