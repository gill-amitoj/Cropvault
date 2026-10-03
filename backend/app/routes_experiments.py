"""Experiments: anyone logged in can list; admins and researchers can create."""

import datetime as dt
from typing import Annotated

import psycopg
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app import db, security

router = APIRouter(prefix="/experiments", tags=["experiments"])
CanCreate = Annotated[dict, security.require_role("admin", "researcher")]


class ExperimentOut(BaseModel):
    id: int
    code: str
    title: str
    description: str | None
    created_by: int | None
    created_at: dt.datetime


class ExperimentCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None


EXPERIMENT_COLUMNS = "id, code, title, description, created_by, created_at"


@router.get("", response_model=list[ExperimentOut])
def list_experiments(user: security.CurrentUser):
    return db.fetch_all(f"SELECT {EXPERIMENT_COLUMNS} FROM experiments ORDER BY code")


@router.post("", response_model=ExperimentOut, status_code=status.HTTP_201_CREATED)
def create_experiment(body: ExperimentCreate, user: CanCreate):
    try:
        with db.get_connection() as conn:
            return conn.execute(
                f"""INSERT INTO experiments (code, title, description, created_by)
                    VALUES (%s, %s, %s, %s) RETURNING {EXPERIMENT_COLUMNS}""",
                (body.code.strip(), body.title.strip(), body.description, user["id"]),
            ).fetchone()
    except psycopg.errors.UniqueViolation:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Experiment code already exists"
        ) from None
