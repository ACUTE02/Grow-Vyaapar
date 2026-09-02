"""The audit trail: who changed what, before and after.

Two ways in. Services call `record` with the actual old and new values for the
entities where that matters - a price change, a role change. The middleware
calls `record_request` for everything else, so a mutating request always leaves
a trace even if nobody wrote a bespoke line for it.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admin import AuditLog

logger = logging.getLogger(__name__)

# Set by the auth dependency so services do not have to thread the user through
# every call signature.
current_actor: ContextVar[int | None] = ContextVar("current_actor", default=None)


def set_actor(user_id: int | None) -> None:
    current_actor.set(user_id)


def record(
    db: Session,
    *,
    action: str,
    entity: str,
    entity_id: Any = None,
    store_id: int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> AuditLog:
    """Write one audit row inside the caller's transaction."""
    entry = AuditLog(
        store_id=store_id,
        user_id=user_id if user_id is not None else current_actor.get(),
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=before,
        after=after,
    )
    db.add(entry)
    db.flush()
    return entry


def record_request(
    *,
    user_id: int | None,
    store_id: str | None,
    method: str,
    path: str,
    status_code: int,
) -> None:
    """Generic trail for a mutating request, on its own connection."""
    from app.db import SessionLocal  # noqa: PLC0415

    entity = path.strip("/").split("/")[0] or "root"
    with SessionLocal() as db:
        db.add(
            AuditLog(
                store_id=int(store_id) if store_id and store_id.isdigit() else None,
                user_id=user_id,
                action=f"{method} {path}",
                entity=entity,
                entity_id=None,
                before=None,
                after={"status_code": status_code},
            )
        )
        db.commit()


def diff(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict, dict]:
    """Only the fields that actually changed, so the row stays readable."""
    changed = {
        key
        for key in set(before) | set(after)
        if str(before.get(key)) != str(after.get(key))
    }
    return (
        {key: before.get(key) for key in sorted(changed)},
        {key: after.get(key) for key in sorted(changed)},
    )


def for_store(db: Session, store_id: int, limit: int = 100) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.store_id == store_id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
        ).all()
    )
