"""Bootstrap the first household user (auth-gated routes need one to exist).

Usage:
    python seed_user.py <email> <name> <password>
    python seed_user.py            # interactive prompts
"""
import getpass
import sys

from app.auth import get_password_hash
from app.database import SessionLocal, init_db
from app.models import User


def main():
    init_db()
    if len(sys.argv) == 4:
        email, name, password = sys.argv[1], sys.argv[2], sys.argv[3]
    else:
        email = input("Email: ").strip()
        name = input("Name: ").strip()
        password = getpass.getpass("Password: ")

    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email).first():
            print(f"User {email} already exists.")
            return
        db.add(
            User(email=email, name=name, hashed_password=get_password_hash(password))
        )
        db.commit()
        print(f"Created user {email}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
