import sys

from dotenv import load_dotenv

from erp.packages.core.db.models import User
from erp.packages.core.db.session import SessionLocal
from erp.packages.core.security import hash_password


def reset_password(username: str, new_password: str) -> bool:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return False
        user.password_hash = hash_password(new_password)
        db.commit()
        return True


if __name__ == "__main__":
    load_dotenv()
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python reset_pwd.py <username> <new-password>")
    if reset_password(sys.argv[1], sys.argv[2]):
        print(f"Password reset for {sys.argv[1]}")
    else:
        print(f"User {sys.argv[1]} not found")
