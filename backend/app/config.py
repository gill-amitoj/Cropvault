"""All settings come from environment variables, read here and nowhere else."""

import os


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


POSTGRES_DB = _require("POSTGRES_DB")
POSTGRES_USER = _require("POSTGRES_USER")
POSTGRES_PASSWORD = _require("POSTGRES_PASSWORD")
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "db")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))

MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio:9000")
MINIO_ROOT_USER = _require("MINIO_ROOT_USER")
MINIO_ROOT_PASSWORD = _require("MINIO_ROOT_PASSWORD")
MINIO_BUCKET = os.environ.get("MINIO_BUCKET", "cropvault-images")
MINIO_SECURE = os.environ.get("MINIO_SECURE", "false").lower() == "true"

# Folder holding schema.sql and seed.sql (mounted at /db in Docker)
DB_DIR = os.environ.get("DB_DIR", "/db")

ADMIN_EMAIL = _require("ADMIN_EMAIL")
ADMIN_PASSWORD = _require("ADMIN_PASSWORD")
