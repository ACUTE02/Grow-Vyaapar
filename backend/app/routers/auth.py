"""Sign in, and manage who can sign in. Owner-only for the user list."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.db import get_db
from app.models.admin import ROLES, User
from app.security import (
    authenticate,
    create_token,
    hash_password,
    require_role,
    require_user,
)
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    user: "UserOut"


class UserIn(BaseModel):
    name: str = Field(min_length=2, max_length=96)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str = "cashier"
    store_id: int | None = None


class UserUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: str
    store_id: int | None = None
    is_active: bool
    created_at: datetime


TokenOut.model_rebuild()


def _as_out(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "store_id": user.store_id,
        "is_active": user.is_active,
        "created_at": user.created_at,
    }


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)) -> dict:
    """The password is checked and discarded. Only a token comes back."""
    user = authenticate(db, payload.email, payload.password)
    if user is None:
        # Deliberately vague: do not leak which half was wrong.
        raise NotFoundError("Email or password is not correct")

    token = create_token(user)
    response.set_cookie(
        settings.jwt_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        max_age=settings.jwt_expiry_minutes * 60,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in_minutes": settings.jwt_expiry_minutes,
        "user": _as_out(user),
    }


@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(settings.jwt_cookie_name)
    return {"detail": "Signed out"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(require_user)) -> dict:
    return _as_out(user)


@router.get("/users", response_model=list[UserOut])
def list_users(
    _: User = Depends(require_role("owner")), db: Session = Depends(get_db)
) -> list[dict]:
    return [_as_out(user) for user in db.scalars(select(User).order_by(User.id)).all()]


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserIn,
    actor: User = Depends(require_role("owner")),
    db: Session = Depends(get_db),
) -> dict:
    if payload.role not in ROLES:
        raise ValidationError(f"Role must be one of: {', '.join(ROLES)}")
    email = payload.email.strip().lower()
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise ConflictError(f"{email} already has an account")

    user = User(
        name=payload.name,
        email=email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        store_id=payload.store_id,
    )
    db.add(user)
    db.flush()
    audit.record(
        db,
        action="user.create",
        entity="user",
        entity_id=user.id,
        store_id=payload.store_id,
        after={"email": email, "role": payload.role, "store_id": payload.store_id},
        user_id=actor.id,
    )
    db.commit()
    db.refresh(user)
    return _as_out(user)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    actor: User = Depends(require_role("owner")),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError(f"No user with id {user_id}")

    before = {"name": user.name, "role": user.role, "is_active": user.is_active}
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)

    if "role" in data and data["role"] not in ROLES:
        raise ValidationError(f"Role must be one of: {', '.join(ROLES)}")
    for key, value in data.items():
        setattr(user, key, value)
    if password:
        user.password_hash = hash_password(password)

    after = {"name": user.name, "role": user.role, "is_active": user.is_active}
    changed_before, changed_after = audit.diff(before, after)
    if password:
        changed_after["password"] = "changed"
    audit.record(
        db,
        action="user.update",
        entity="user",
        entity_id=user.id,
        store_id=user.store_id,
        before=changed_before,
        after=changed_after,
        user_id=actor.id,
    )
    db.commit()
    db.refresh(user)
    return _as_out(user)
