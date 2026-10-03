"""Login and current user."""

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app import audit, db, security
from app.routes_users import UserOut

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenOut)
def login(body: LoginRequest):
    email = body.email.strip().lower()
    with db.get_connection() as conn:
        user = conn.execute(
            "SELECT id, password_hash, is_active FROM users WHERE email = %s", (email,)
        ).fetchone()
        password_ok = security.verify_password(
            user["password_hash"] if user else None, body.password
        )
        # Same message for unknown email, wrong password and deactivated account,
        # so the response never reveals which emails exist.
        if not password_ok or not user["is_active"]:
            logger.warning("Failed login for %s", email)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        audit.write_audit(conn, user["id"], "LOGIN", "user", user["id"])
    logger.info("User %s logged in", user["id"])
    return TokenOut(access_token=security.create_token(user["id"]))


@router.get("/me", response_model=UserOut)
def me(user: security.CurrentUser):
    return user
