"""Optional: create the first moderator from environment variables on startup.

Useful on hosts where you cannot open a shell to run create_moderator.py.
Set BOOTSTRAP_MODERATOR_USERNAME and BOOTSTRAP_MODERATOR_PASSWORD (min 8 characters).
If that username already exists, nothing happens.
"""
import os

from sqlalchemy import select

from .database import SessionLocal
from .models import Moderator
from .security import hash_password


def bootstrap_moderator() -> None:
    username = os.getenv("BOOTSTRAP_MODERATOR_USERNAME", "").strip()
    password = os.getenv("BOOTSTRAP_MODERATOR_PASSWORD", "")
    if not username or not password:
        return
    if len(password) < 8:
        print("Bootstrap moderator skipped: password must be at least 8 characters.")
        return

    with SessionLocal() as db:
        if db.scalar(select(Moderator).where(Moderator.username == username)) is None:
            db.add(Moderator(username=username, password_hash=hash_password(password)))
            db.commit()
            print(f"Bootstrap moderator '{username}' created.")
