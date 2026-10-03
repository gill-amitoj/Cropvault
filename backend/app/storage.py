"""Object storage (MinIO) helpers as plain functions."""

import logging

from minio import Minio

from app import config

logger = logging.getLogger(__name__)


def get_client() -> Minio:
    return Minio(
        config.MINIO_ENDPOINT,
        access_key=config.MINIO_ROOT_USER,
        secret_key=config.MINIO_ROOT_PASSWORD,
        secure=config.MINIO_SECURE,
    )


def ensure_bucket() -> None:
    """Create the images bucket if it does not exist yet."""
    client = get_client()
    if not client.bucket_exists(config.MINIO_BUCKET):
        client.make_bucket(config.MINIO_BUCKET)
        logger.info("Created bucket %s", config.MINIO_BUCKET)


def check_storage() -> None:
    """Raise if MinIO is unreachable or the bucket is missing."""
    if not get_client().bucket_exists(config.MINIO_BUCKET):
        raise RuntimeError(f"Bucket {config.MINIO_BUCKET} does not exist")
