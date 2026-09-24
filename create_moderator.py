"""Run once per moderator:  python create_moderator.py"""
import getpass
import sys

from app.database import Base, SessionLocal, engine
from app.models import Moderator
from app.security import hash_password


def main() -> None:
    Base.metadata.create_all(bind=engine)
    username = input("Moderator username: ").strip()
    password = getpass.getpass("Password (min 8 characters): ")

    if not username:
        sys.exit("Username cannot be empty.")
    if len(password) < 8:
        sys.exit("Password must be at least 8 characters.")

    with SessionLocal() as db:
        if db.query(Moderator).filter_by(username=username).first():
            sys.exit("That username already exists.")
        db.add(Moderator(username=username, password_hash=hash_password(password)))
        db.commit()
    print(f"Moderator '{username}' created.")


if __name__ == "__main__":
    main()
