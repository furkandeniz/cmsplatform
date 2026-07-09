import hashlib
import hmac
import os
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User

PBKDF2_ITERATIONS = 260_000
DEFAULT_USER_EMAIL = "furkan.deniz@etiya.com"
DEFAULT_USER_PASSWORD = "Abc12345."
DEFAULT_USER_FULL_NAME = "Furkan Deniz"


def get_initials(full_name: str) -> str:
    parts = full_name.split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, hash_hex = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def seed_default_user(db: Session) -> None:
    existing = db.scalar(select(User).limit(1))
    if existing is not None:
        return
    db.add(
        User(
            full_name=DEFAULT_USER_FULL_NAME,
            email=DEFAULT_USER_EMAIL,
            password_hash=hash_password(DEFAULT_USER_PASSWORD),
            role="admin",
        )
    )
    db.commit()


def get_current_user(db: Session, request: Request) -> Optional[User]:
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    return db.get(User, user_id)


def get_allowed_project_ids(db: Session, request: Request) -> Optional[set]:
    """None means unrestricted access (admin); otherwise the set of project ids
    the current user is allowed to see (possibly empty)."""
    if request.session.get("role") == "admin":
        return None
    user = get_current_user(db, request)
    if user is None:
        return set()
    return {project.id for project in user.projects}


def require_admin(request: Request) -> None:
    if request.session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Bu işlem için yönetici yetkisi gerekir")
