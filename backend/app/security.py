"""Authentication and authorisation.

bcrypt for hashes, JWT for sessions. Passwords are hashed at the boundary and
never stored, logged or echoed back - the only thing that leaves this module is
a token.

Roles, from most to least: owner does everything; manager does everything except
users and store settings; cashier bills, serves customers and reads the catalog.
Enforcement lives in the API (see app/middleware.py), not only in the UI - hiding
a button is a courtesy, refusing the request is the control.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.admin import ROLES, User
from app.settings import settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
BCRYPT_ROUNDS = 12

# Who may do what, by escalating level.
ROLE_LEVEL = {"cashier": 1, "manager": 2, "owner": 3}


# --------------------------------------------------------------------------- #
# passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("A password needs at least 8 characters")
    # bcrypt refuses anything past 72 bytes rather than silently truncating.
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], password_hash.encode())
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# tokens
# --------------------------------------------------------------------------- #
def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "store_id": user.store_id,
        "name": user.name,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expiry_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        logger.info("Rejected token: %s", exc)
        return None


def token_from_request(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(settings.jwt_cookie_name)


# --------------------------------------------------------------------------- #
# dependencies
# --------------------------------------------------------------------------- #
def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """The signed-in user, or None. Never raises - callers decide what to require."""
    token = token_from_request(request)
    if not token:
        return None
    claims = decode_token(token)
    if not claims:
        return None
    user = db.get(User, int(claims["sub"]))
    if user is None or not user.is_active:
        return None
    return user


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in first. Send the token as 'Authorization: Bearer <token>'.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(minimum: str):
    """Dependency factory: require at least this role."""
    if minimum not in ROLES:
        raise ValueError(f"Unknown role {minimum}")

    def _guard(user: User = Depends(require_user)) -> User:
        if ROLE_LEVEL[user.role] < ROLE_LEVEL[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This needs the {minimum} role. You are signed in as {user.role}."
                ),
            )
        return user

    return _guard


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
