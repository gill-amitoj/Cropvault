"""User management (admin only)."""

import datetime as dt
import re
from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator

from app import audit, db, security

router = APIRouter(prefix="/users", tags=["users"])
AdminUser = Annotated[dict, security.require_role("admin")]

Role = Literal["admin", "researcher", "viewer"]
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserOut(BaseModel):
    """What the API returns for a user. password_hash is never included."""

    id: int
    email: str
    role: Role
    is_active: bool
    created_at: dt.datetime


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8)
    role: Role

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not EMAIL_PATTERN.match(value):
            raise ValueError("not a valid email address")
        return value


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def at_least_one_field(self):
        if self.role is None and self.is_active is None:
            raise ValueError("provide role and/or is_active")
        return self


USER_COLUMNS = "id, email, role, is_active, created_at"


@router.get("", response_model=list[UserOut])
def list_users(admin: AdminUser):
    return db.fetch_all(f"SELECT {USER_COLUMNS} FROM users ORDER BY id")


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, admin: AdminUser):
    try:
        with db.get_connection() as conn:
            user = conn.execute(
                f"""INSERT INTO users (email, password_hash, role) VALUES (%s, %s, %s)
                    RETURNING {USER_COLUMNS}""",
                (body.email, security.hash_password(body.password), body.role),
            ).fetchone()
            audit.write_audit(
                conn,
                admin["id"],
                "USER_CREATE",
                "user",
                user["id"],
                {"email": body.email, "role": body.role},
            )
    except psycopg.errors.UniqueViolation:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Email already exists") from None
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, admin: AdminUser):
    # Stops an admin from locking themselves (and possibly everyone) out of admin.
    if user_id == admin["id"]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own role or active status",
        )
    with db.get_connection() as conn:
        old = conn.execute(
            f"SELECT {USER_COLUMNS} FROM users WHERE id = %s FOR UPDATE", (user_id,)
        ).fetchone()
        if old is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")

        new_role = body.role if body.role is not None else old["role"]
        new_active = body.is_active if body.is_active is not None else old["is_active"]
        user = conn.execute(
            f"UPDATE users SET role = %s, is_active = %s WHERE id = %s RETURNING {USER_COLUMNS}",
            (new_role, new_active, user_id),
        ).fetchone()

        if new_role != old["role"]:
            audit.write_audit(
                conn,
                admin["id"],
                "ROLE_CHANGE",
                "user",
                user_id,
                {"from": old["role"], "to": new_role},
            )
        if new_active != old["is_active"]:
            audit.write_audit(
                conn,
                admin["id"],
                "UPDATE",
                "user",
                user_id,
                {"is_active": {"from": old["is_active"], "to": new_active}},
            )
    return user
