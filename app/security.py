import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# In production set WHISTLEDROP_SECRET to a long random string.
SECRET_KEY = os.getenv("WHISTLEDROP_SECRET", "dev-only-secret-key-please-change-before-deploying")

# Refuse to start in production with the built-in dev key or a short key.
if os.getenv("WHISTLEDROP_ENV") == "production" and (
    SECRET_KEY.startswith("dev-only") or len(SECRET_KEY) < 32
):
    raise RuntimeError("Set WHISTLEDROP_SECRET to a random string of at least 32 characters.")
ALGORITHM = "HS256"
TOKEN_MINUTES = 60

_password_hasher = PasswordHasher()


# ---------- case codes (for reporters) ----------
def generate_case_code() -> str:
    """16 random bytes = 128 bits of entropy. Impossible to guess."""
    return "WD-" + secrets.token_urlsafe(16)


def hash_case_code(code: str) -> str:
    """SHA-256 is fine here because the code is already long and random."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


# ---------- moderator passwords ----------
def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


# ---------- moderator tokens ----------
def create_access_token(username: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=TOKEN_MINUTES)
    return jwt.encode({"sub": username, "exp": expires}, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Returns the username inside a valid token, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload.get("sub")
