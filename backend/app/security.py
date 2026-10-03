"""Password hashing. Login, JWT and require_role() come in Stage 2."""

from argon2 import PasswordHasher

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)
