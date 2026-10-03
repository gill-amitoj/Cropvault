"""Image upload, metadata, streaming and delete."""

import datetime as dt
import logging
import uuid
from typing import Annotated
from urllib.parse import quote

import psycopg
from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from app import audit, db, images, security, storage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/images", tags=["images"])

CanWrite = Annotated[dict, security.require_role("admin", "researcher")]


class ImageOut(BaseModel):
    """What the API returns for an image. Storage keys stay internal."""

    id: int
    experiment_id: int | None
    experiment_code: str | None
    crop_species: str | None
    capture_date: dt.date | None
    station_id: str | None
    original_filename: str
    content_type: str
    size_bytes: int
    width: int
    height: int
    sha256: str
    exif: dict | None
    tags: list[str]
    uploaded_by: int
    parent_image_id: int | None
    derivation: str | None
    created_at: dt.datetime


class ImageUpdate(BaseModel):
    """Editable metadata. Omitted fields are unchanged; null clears a field."""

    experiment_code: str | None = None
    crop_species: str | None = None
    station_id: str | None = None
    capture_date: dt.date | None = None
    tags: list[str] | None = None


IMAGE_SELECT = """
    SELECT i.id, i.experiment_id, e.code AS experiment_code, i.crop_species, i.capture_date,
           i.station_id, i.original_filename, i.content_type, i.size_bytes, i.width, i.height,
           i.sha256, i.exif, i.tags, i.uploaded_by, i.parent_image_id, i.derivation, i.created_at
    FROM images i LEFT JOIN experiments e ON e.id = i.experiment_id
"""


# --- helpers ------------------------------------------------------------------------------


def clean_tags(tags: list[str]) -> list[str]:
    """Strip, lowercase, drop empties and duplicates (keeping order)."""
    result = []
    for tag in tags:
        tag = tag.strip().lower()
        if tag and tag not in result:
            result.append(tag)
    return result


def clean_text(value: str | None) -> str | None:
    value = value.strip() if value else None
    return value or None


def experiment_id_for(conn, code: str | None) -> int | None:
    if code is None:
        return None
    row = conn.execute("SELECT id FROM experiments WHERE code = %s", (code,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"Unknown experiment code: {code}")
    return row["id"]


def get_image_or_404(image_id: int) -> dict:
    image = db.fetch_one(IMAGE_SELECT + " WHERE i.id = %s", (image_id,))
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Image not found")
    return image


def check_owner_or_admin(user: dict, owner_id: int) -> None:
    if user["role"] != "admin" and user["id"] != owner_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="You can only change your own images")


def duplicate_error(image_id: int) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, detail={"message": "Duplicate image", "image_id": image_id}
    )


def jsonable(value):
    """Dates aren't JSON; store them as YYYY-MM-DD in audit details."""
    return value.isoformat() if isinstance(value, dt.date) else value


def delete_objects_quietly(keys: list[str]) -> None:
    """Best-effort object delete. A failure leaves an orphan object, which we log loudly."""
    for key in keys:
        try:
            storage.delete_object(key)
        except Exception:
            logger.error("ORPHAN object could not be deleted from storage: %s", key)


# --- routes -------------------------------------------------------------------------------


@router.post("", response_model=ImageOut, status_code=status.HTTP_201_CREATED)
def upload_image(
    user: CanWrite,
    file: Annotated[UploadFile, File()],
    experiment_code: Annotated[str | None, Form()] = None,
    crop_species: Annotated[str | None, Form()] = None,
    station_id: Annotated[str | None, Form()] = None,
    capture_date: Annotated[dt.date | None, Form()] = None,
    tags: Annotated[str | None, Form(description="Comma-separated")] = None,
):
    # 1. Size: read at most one byte past the limit, so we never hold more than that.
    data = file.file.read(images.MAX_UPLOAD_BYTES + 1)
    if len(data) > images.MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="File is larger than 20 MB")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="File is empty")

    # 2. Content: must really be a JPEG/PNG/TIFF, whatever the name or Content-Type says.
    try:
        img = images.open_image(data)
    except images.ImageTooLarge as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)) from None
    except images.InvalidImage as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from None

    # 3. Duplicate check by checksum (the UNIQUE constraint below also catches races).
    sha256 = images.sha256_hex(data)
    existing = db.fetch_one("SELECT id FROM images WHERE sha256 = %s", (sha256,))
    if existing:
        raise duplicate_error(existing["id"])

    experiment_code = clean_text(experiment_code)
    with db.get_connection() as conn:
        experiment_id = experiment_id_for(conn, experiment_code)

    content_type, extension = images.ALLOWED_FORMATS[img.format]
    exif = images.extract_exif(img)
    width, height = images.display_size(img)
    thumbnail = images.make_thumbnail(img)
    object_id = uuid.uuid4().hex
    storage_key = f"originals/{object_id}{extension}"
    thumbnail_key = f"thumbnails/{object_id}.jpg"

    # 4. Storage first, then the DB row. If anything after the first put fails,
    #    remove the objects we wrote so storage and DB stay in sync.
    written = []
    try:
        storage.put_object(storage_key, data, content_type)
        written.append(storage_key)
        storage.put_object(thumbnail_key, thumbnail, "image/jpeg")
        written.append(thumbnail_key)
        with db.get_connection() as conn:
            row = conn.execute(
                """INSERT INTO images (experiment_id, crop_species, capture_date, station_id,
                       original_filename, storage_key, thumbnail_key, content_type, size_bytes,
                       width, height, sha256, exif, tags, uploaded_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    experiment_id,
                    clean_text(crop_species),
                    capture_date or images.capture_date_from_exif(exif),
                    clean_text(station_id),
                    file.filename or "unnamed",
                    storage_key,
                    thumbnail_key,
                    content_type,
                    len(data),
                    width,
                    height,
                    sha256,
                    Jsonb(exif),
                    clean_tags(tags.split(",")) if tags else [],
                    user["id"],
                ),
            ).fetchone()
            audit.write_audit(
                conn,
                user["id"],
                "UPLOAD",
                "image",
                row["id"],
                {"original_filename": file.filename, "sha256": sha256},
            )
    except psycopg.errors.UniqueViolation:
        # Another upload of the same bytes won the race between our check and our insert.
        delete_objects_quietly(written)
        existing = db.fetch_one("SELECT id FROM images WHERE sha256 = %s", (sha256,))
        raise duplicate_error(existing["id"]) from None
    except Exception:
        delete_objects_quietly(written)
        raise

    logger.info("Uploaded image %s (%s) by user %s", row["id"], file.filename, user["id"])
    return get_image_or_404(row["id"])


@router.get("/{image_id}", response_model=ImageOut)
def get_image(image_id: int, user: security.CurrentUser):
    return get_image_or_404(image_id)


@router.patch("/{image_id}", response_model=ImageOut)
def update_image(image_id: int, body: ImageUpdate, user: CanWrite):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Nothing to update")

    with db.get_connection() as conn:
        old = conn.execute(
            IMAGE_SELECT + " WHERE i.id = %s FOR UPDATE OF i", (image_id,)
        ).fetchone()
        if old is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Image not found")
        check_owner_or_admin(user, old["uploaded_by"])

        new = {
            "experiment_code": old["experiment_code"],
            "crop_species": old["crop_species"],
            "station_id": old["station_id"],
            "capture_date": old["capture_date"],
            "tags": old["tags"],
        }
        for field, value in changes.items():
            if field == "tags":
                new["tags"] = clean_tags(value or [])
            elif field == "capture_date":
                new["capture_date"] = value
            else:
                new[field] = clean_text(value)

        conn.execute(
            """UPDATE images SET experiment_id = %s, crop_species = %s, station_id = %s,
                   capture_date = %s, tags = %s
               WHERE id = %s""",
            (
                experiment_id_for(conn, new["experiment_code"]),
                new["crop_species"],
                new["station_id"],
                new["capture_date"],
                new["tags"],
                image_id,
            ),
        )
        diff = {
            field: {"from": jsonable(old[field]), "to": jsonable(new[field])}
            for field in new
            if new[field] != old[field]
        }
        if diff:
            audit.write_audit(conn, user["id"], "UPDATE", "image", image_id, diff)

    return get_image_or_404(image_id)


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_image(image_id: int, user: CanWrite):
    # DB row first, then the objects. If an object delete fails, it's logged as an orphan.
    try:
        with db.get_connection() as conn:
            image = conn.execute(
                """SELECT id, uploaded_by, original_filename, sha256, storage_key, thumbnail_key
                   FROM images WHERE id = %s FOR UPDATE""",
                (image_id,),
            ).fetchone()
            if image is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Image not found")
            check_owner_or_admin(user, image["uploaded_by"])
            conn.execute("DELETE FROM images WHERE id = %s", (image_id,))
            audit.write_audit(
                conn,
                user["id"],
                "DELETE",
                "image",
                image_id,
                {"original_filename": image["original_filename"], "sha256": image["sha256"]},
            )
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This image has derived images (crops/masks). Delete those first.",
        ) from None

    delete_objects_quietly([k for k in (image["storage_key"], image["thumbnail_key"]) if k])
    logger.info("Deleted image %s by user %s", image_id, user["id"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def stream_object(key: str | None, media_type: str, headers: dict | None = None):
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File not found")
    try:
        chunks = storage.open_object(key)
    except storage.ObjectNotFound:
        logger.error("Object missing from storage: %s", key)
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File not found") from None
    return StreamingResponse(chunks, media_type=media_type, headers=headers)


@router.get("/{image_id}/file")
def get_image_file(image_id: int, user: security.CurrentUser):
    """Stream the original through the API (the browser can't reach MinIO directly)."""
    image = db.fetch_one(
        "SELECT storage_key, content_type, original_filename FROM images WHERE id = %s",
        (image_id,),
    )
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Image not found")
    disposition = f"inline; filename*=UTF-8''{quote(image['original_filename'])}"
    return stream_object(
        image["storage_key"], image["content_type"], {"Content-Disposition": disposition}
    )


@router.get("/{image_id}/thumbnail")
def get_image_thumbnail(image_id: int, user: security.CurrentUser):
    image = db.fetch_one("SELECT thumbnail_key FROM images WHERE id = %s", (image_id,))
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Image not found")
    return stream_object(image["thumbnail_key"], "image/jpeg")
