"""Password hashing, JWT tokens, and the current-user / role checks used by routes."""

import datetime as dt
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app import config, db

_hasher = PasswordHasher()
# Used when the email doesn't exist, so a failed login takes the same time either way
# and response timing doesn't reveal which emails are registered.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """False on wrong password or missing user (still runs argon2 once, for equal timing)."""
    try:
        _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return password_hash is not None


def create_token(user_id: int) -> str:
    now = dt.datetime.now(dt.UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + dt.timedelta(minutes=config.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict:
    """Decode the bearer token and load the user fresh from the DB on every request,
    so deactivation and role changes take effect immediately."""
    if credentials is None:
        raise _unauthorized("Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, config.JWT_SECRET, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise _unauthorized("Invalid or expired token") from None

    user = db.fetch_one(
        "SELECT id, email, role, is_active, created_at FROM users WHERE id = %s", (user_id,)
    )
    if user is None or not user["is_active"]:
        raise _unauthorized("Invalid or expired token")
    return user


# Route parameter type: `user: CurrentUser` = any logged-in, active user.
CurrentUser = Annotated[dict, Depends(get_current_user)]


def require_role(*roles: str):
    """Route dependency: 403 unless the logged-in user has one of the given roles."""

    def check(user: CurrentUser) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not allowed for your role")
        return user

    return Depends(check)
