"""Jobs: the alteration, the lens fitting, the cake ordered for Saturday.

A small explicit state machine. Illegal moves are refused with a message that
names both states, because "invalid transition" tells a shopkeeper nothing.

Job types come from the vertical's config, never from a list in this file.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.core import Customer, Job
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.verticals.context import StoreContext

logger = logging.getLogger(__name__)

STATUSES = ("pending", "in_progress", "ready", "delivered", "cancelled")

# Forward only, one step at a time; cancelled is reachable from anything open.
ALLOWED: dict[str, set[str]] = {
    "pending": {"in_progress", "ready", "cancelled"},
    "in_progress": {"ready", "cancelled"},
    "ready": {"delivered", "cancelled"},
    "delivered": set(),
    "cancelled": set(),
}


def _require_flag(context: StoreContext) -> None:
    if not context.feature("jobs"):
        raise ValidationError(
            f"{context.store_name} does not take jobs. This vertical has the jobs "
            "feature flag switched off."
        )


def get_job(db: Session, context: StoreContext, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None or job.store_id != context.store_id:
        raise NotFoundError(f"Job {job_id} does not belong to {context.store_name}")
    return job


def create_job(db: Session, context: StoreContext, payload: dict[str, Any]) -> Job:
    _require_flag(context)

    customer = db.get(Customer, int(payload["customer_id"]))
    if customer is None or customer.store_id != context.store_id:
        raise NotFoundError(
            f"Customer {payload['customer_id']} is not a customer of {context.store_name}"
        )

    allowed_types = [str(item) for item in (context.cfg("job_types") or [])]
    job_type = str(payload.get("type") or "").strip()
    if allowed_types and job_type not in allowed_types:
        raise ValidationError(
            f"'{job_type}' is not a job this store takes. {context.store_name} does: "
            + ", ".join(allowed_types)
        )

    job = Job(
        store_id=context.store_id,
        customer_id=customer.id,
        transaction_id=payload.get("transaction_id"),
        type=job_type or "job",
        status="pending",
        promised_date=payload.get("promised_date"),
    )
    db.add(job)
    db.flush()
    return job


def change_status(
    db: Session, context: StoreContext, job_id: int, new_status: str
) -> tuple[Job, bool]:
    """Move a job along. Returns the job and whether it just became ready."""
    job = get_job(db, context, job_id)

    if new_status not in STATUSES:
        raise ValidationError(
            f"'{new_status}' is not a job status. Use one of: {', '.join(STATUSES)}"
        )
    if new_status == job.status:
        raise ConflictError(f"Job {job.id} is already {job.status}")
    if new_status not in ALLOWED[job.status]:
        allowed = ", ".join(sorted(ALLOWED[job.status])) or "nothing, it is finished"
        raise ConflictError(
            f"Job {job.id} is {job.status} and cannot become {new_status}. "
            f"From {job.status} it can only go to: {allowed}"
        )

    job.status = new_status
    became_ready = new_status == "ready"
    if became_ready:
        job.ready_at = utcnow()
    if new_status == "delivered":
        job.delivered_at = utcnow()
        if job.ready_at is None:
            job.ready_at = utcnow()

    db.flush()
    return job, became_ready


def list_jobs(
    db: Session,
    context: StoreContext,
    *,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    statement = (
        select(Job, Customer)
        .outerjoin(Customer, Customer.id == Job.customer_id)
        .where(Job.store_id == context.store_id)
    )
    if status:
        statement = statement.where(Job.status == status)
    statement = (
        statement.order_by(Job.promised_date.asc().nulls_last(), Job.id.asc())
        .limit(limit)
        .offset(offset)
    )

    today = date.today()
    rows = []
    for job, customer in db.execute(statement).all():
        overdue = bool(
            job.promised_date
            and job.promised_date < today
            and job.status in ("pending", "in_progress", "ready")
        )
        rows.append(
            {
                "id": job.id,
                "customer_id": job.customer_id,
                "customer_name": customer.name if customer else None,
                "phone": customer.phone if customer else None,
                "type": job.type,
                "status": job.status,
                "promised_date": job.promised_date,
                "ready_at": job.ready_at,
                "delivered_at": job.delivered_at,
                "is_overdue": overdue,
                "next_statuses": sorted(ALLOWED[job.status]),
            }
        )
    return rows


def board_counts(db: Session, context: StoreContext) -> dict[str, int]:
    rows = db.execute(
        select(Job.status, func.count(Job.id))
        .where(Job.store_id == context.store_id)
        .group_by(Job.status)
    ).all()
    counts = dict.fromkeys(STATUSES, 0)
    for status, count in rows:
        counts[status] = int(count)
    return counts
