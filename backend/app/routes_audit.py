"""Audit log (admin only), newest first, paginated."""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app import db, security

router = APIRouter(prefix="/audit", tags=["audit"])
AdminUser = Annotated[dict, security.require_role("admin")]


class AuditEntry(BaseModel):
    id: int
    user_id: int | None
    user_email: str | None
    action: str
    entity_type: str
    entity_id: int | None
    details: dict | None
    created_at: dt.datetime


class AuditPage(BaseModel):
    items: list[AuditEntry]
    total: int
    page: int
    page_size: int


@router.get("", response_model=AuditPage)
def list_audit(
    admin: AdminUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 24,
):
    items = db.fetch_all(
        """SELECT a.id, a.user_id, u.email AS user_email, a.action, a.entity_type, a.entity_id,
                  a.details, a.created_at
           FROM audit_log a LEFT JOIN users u ON u.id = a.user_id
           ORDER BY a.id DESC
           LIMIT %s OFFSET %s""",
        (page_size, (page - 1) * page_size),
    )
    total = db.fetch_one("SELECT count(*) AS n FROM audit_log")["n"]
    return AuditPage(items=items, total=total, page=page, page_size=page_size)
