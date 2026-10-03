"""Object storage (MinIO) helpers as plain functions."""

import io
import logging
from collections.abc import Iterator

from minio import Minio
from minio.error import S3Error

from app import config

logger = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024


class ObjectNotFound(Exception):
    """The key does not exist in the bucket."""


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


def put_object(key: str, data: bytes, content_type: str) -> None:
    get_client().put_object(
        config.MINIO_BUCKET, key, io.BytesIO(data), length=len(data), content_type=content_type
    )


def open_object(key: str) -> Iterator[bytes]:
    """Start reading an object and return an iterator over its bytes.
    Raises ObjectNotFound up front (before any bytes are streamed to the client)."""
    try:
        response = get_client().get_object(config.MINIO_BUCKET, key)
    except S3Error as exc:
        if exc.code == "NoSuchKey":
            raise ObjectNotFound(key) from None
        raise

    def chunks():
        try:
            yield from response.stream(CHUNK_SIZE)
        finally:
            response.close()
            response.release_conn()

    return chunks()


def delete_object(key: str) -> None:
    get_client().remove_object(config.MINIO_BUCKET, key)
