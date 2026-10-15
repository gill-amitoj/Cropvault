"""Annotations: bounding boxes and polygons drawn on an image.

Coordinates are fractions (0-1) of the image's displayed width/height (trap #9), so they line up
at any display size. Anyone logged in can see annotations; admins and researchers can create them
on any image; researchers can change or delete only their OWN annotations; admins any.
"""

import datetime as dt
import math
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Response, status
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app import audit, db, security

router = APIRouter(tags=["annotations"])
CanWrite = Annotated[dict, security.require_role("admin", "researcher")]

Kind = Literal["bbox", "polygon"]
MAX_POLYGON_POINTS = 200
EPSILON = 1e-9  # tolerance for float rounding at the image edge (e.g. 0.3 + 0.7)


class BBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def inside_image(self):
        if self.x + self.width > 1 + EPSILON or self.y + self.height > 1 + EPSILON:
            raise ValueError("box must lie inside the image")
        return self


class Polygon(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: list[tuple[float, float]] = Field(min_length=3, max_length=MAX_POLYGON_POINTS)

    @field_validator("points")
    @classmethod
    def inside_image(cls, points):
        for x, y in points:
            if not (math.isfinite(x) and math.isfinite(y) and 0 <= x <= 1 and 0 <= y <= 1):
                raise ValueError("every point must have x and y between 0 and 1")
        return points


def validate_geometry(kind: str, geometry: dict) -> dict:
    """Check the geometry matches its kind; return it in a clean, normalized form."""
    model = BBox if kind == "bbox" else Polygon
    try:
        return model.model_validate(geometry).model_dump()
    except ValidationError as exc:
        messages = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or kind}: {err['msg']}" for err in exc.errors()
        )
        raise ValueError(f"invalid {kind} geometry: {messages}") from None


def clean_label(value: str) -> str:
    value = value.strip()
    if not 1 <= len(value) <= 100:
        raise ValueError("label must be 1-100 characters")
    return value


class AnnotationCreate(BaseModel):
    label: str
    kind: Kind
    geometry: dict

    @field_validator("label")
    @classmethod
    def label_ok(cls, value):
        return clean_label(value)

    @model_validator(mode="after")
    def check_geometry(self):
        self.geometry = validate_geometry(self.kind, self.geometry)
        return self


class AnnotationUpdate(BaseModel):
    """Change the label and/or the shape. The kind stays the same."""

    label: str | None = None
    geometry: dict | None = None

    @field_validator("label")
    @classmethod
    def label_ok(cls, value):
        return None if value is None else clean_label(value)

    @model_validator(mode="after")
    def at_least_one(self):
        if self.label is None and self.geometry is None:
            raise ValueError("provide label and/or geometry")
        return self


class AnnotationOut(BaseModel):
    id: int
    image_id: int
    label: str
    kind: Kind
    geometry: dict
    created_by: int
    created_at: dt.datetime
    updated_at: dt.datetime


COLUMNS = "id, image_id, label, kind, geometry, created_by, created_at, updated_at"


def require_image(conn, image_id: int) -> None:
    if conn.execute("SELECT 1 FROM images WHERE id = %s", (image_id,)).fetchone() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Image not found")


def load_own_annotation(conn, annotation_id: int, user: dict) -> dict:
    """Lock the row, 404 if missing, 403 unless it's yours (admins may change any)."""
    annotation = conn.execute(
        f"SELECT {COLUMNS} FROM annotations WHERE id = %s FOR UPDATE", (annotation_id,)
    ).fetchone()
    if annotation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Annotation not found")
    if user["role"] != "admin" and annotation["created_by"] != user["id"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail="You can only change your own annotations"
        )
    return annotation


@router.get("/images/{image_id}/annotations", response_model=list[AnnotationOut])
def list_annotations(image_id: int, user: security.CurrentUser):
    with db.get_connection() as conn:
        require_image(conn, image_id)
        return conn.execute(
            f"SELECT {COLUMNS} FROM annotations WHERE image_id = %s ORDER BY id", (image_id,)
        ).fetchall()


@router.post(
    "/images/{image_id}/annotations",
    response_model=AnnotationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_annotation(image_id: int, body: AnnotationCreate, user: CanWrite):
    with db.get_connection() as conn:
        require_image(conn, image_id)
        annotation = conn.execute(
            f"""INSERT INTO annotations (image_id, label, kind, geometry, created_by)
                VALUES (%s, %s, %s, %s, %s) RETURNING {COLUMNS}""",
            (image_id, body.label, body.kind, Jsonb(body.geometry), user["id"]),
        ).fetchone()
        audit.write_audit(
            conn,
            user["id"],
            "ANNOTATE",
            "annotation",
            annotation["id"],
            {"image_id": image_id, "kind": body.kind, "label": body.label},
        )
    return annotation


@router.patch("/annotations/{annotation_id}", response_model=AnnotationOut)
def update_annotation(annotation_id: int, body: AnnotationUpdate, user: CanWrite):
    with db.get_connection() as conn:
        old = load_own_annotation(conn, annotation_id, user)
        label = body.label if body.label is not None else old["label"]
        geometry = old["geometry"]
        if body.geometry is not None:
            try:
                geometry = validate_geometry(old["kind"], body.geometry)
            except ValueError as exc:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
                ) from None
        annotation = conn.execute(
            f"""UPDATE annotations SET label = %s, geometry = %s, updated_at = now()
                WHERE id = %s RETURNING {COLUMNS}""",
            (label, Jsonb(geometry), annotation_id),
        ).fetchone()
        changes = {}
        if label != old["label"]:
            changes["label"] = {"from": old["label"], "to": label}
        if geometry != old["geometry"]:
            changes["geometry"] = {"from": old["geometry"], "to": geometry}
        if changes:
            audit.write_audit(conn, user["id"], "UPDATE", "annotation", annotation_id, changes)
    return annotation


@router.delete("/annotations/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_annotation(annotation_id: int, user: CanWrite):
    with db.get_connection() as conn:
        old = load_own_annotation(conn, annotation_id, user)
        conn.execute("DELETE FROM annotations WHERE id = %s", (annotation_id,))
        audit.write_audit(
            conn,
            user["id"],
            "DELETE",
            "annotation",
            annotation_id,
            {"image_id": old["image_id"], "kind": old["kind"], "label": old["label"]},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
