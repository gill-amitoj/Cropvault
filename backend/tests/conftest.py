import os

# Dummy settings so app.config can be imported without a real .env.
# Unit tests never talk to a real database or MinIO.
os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("MINIO_ROOT_USER", "test")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "test")
