from fastapi import Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Moderator
from .security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_moderator(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    token: str | None = Query(default=None, include_in_schema=False),
    db: Session = Depends(get_db),
) -> Moderator:
    """Protects moderator routes: valid token in, Moderator out, otherwise 401.

    The token is normally read from the Authorization header. A `?token=` query parameter
    is also accepted, only so the dashboard's evidence links (plain <a> tags, which cannot
    send custom headers) can open an image in a new tab. Every real API client should use
    the Authorization header instead.
    """
    unauthorized = HTTPException(
        status_code=401,
        detail="Invalid or missing token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    raw_token = credentials.credentials if credentials else token
    if raw_token is None:
        raise unauthorized

    username = decode_access_token(raw_token)
    if username is None:
        raise unauthorized

    moderator = db.scalar(select(Moderator).where(Moderator.username == username))
    if moderator is None:
        raise unauthorized
    return moderator
