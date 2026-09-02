"""Jobs board endpoints. Gated by the vertical's jobs feature flag."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import jobs_service
from app.verticals.context import StoreContext, get_store_context_from_query

router = APIRouter(prefix="/jobs", tags=["jobs"])


class JobIn(BaseModel):
    customer_id: int
    type: str = Field(min_length=2, max_length=48)
    promised_date: date | None = None
    transaction_id: int | None = None


class JobStatusIn(BaseModel):
    status: str = Field(description="pending | in_progress | ready | delivered | cancelled")


class JobOut(BaseModel):
    id: int
    customer_id: int
    customer_name: str | None = None
    phone: str | None = None
    type: str
    status: str
    promised_date: date | None = None
    ready_at: object | None = None
    delivered_at: object | None = None
    is_overdue: bool = False
    next_statuses: list[str] = []


class JobStatusOut(BaseModel):
    job: JobOut
    reminders_queued: int = 0


@router.get("", response_model=list[JobOut])
def list_jobs(
    status: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    return jobs_service.list_jobs(db, context, status=status, limit=limit, offset=offset)


@router.get("/board")
def board(
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    """Counts per column, plus the job types this vertical actually takes."""
    return {
        "store_id": context.store_id,
        "takes_jobs": context.feature("jobs"),
        "job_types": context.cfg("job_types") or [],
        "counts": jobs_service.board_counts(db, context),
        "statuses": list(jobs_service.STATUSES),
    }


@router.post("", response_model=JobOut, status_code=http_status.HTTP_201_CREATED)
def create_job(
    payload: JobIn,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    job = jobs_service.create_job(db, context, payload.model_dump())
    db.commit()
    return {
        "id": job.id,
        "customer_id": job.customer_id,
        "type": job.type,
        "status": job.status,
        "promised_date": job.promised_date,
        "ready_at": job.ready_at,
        "delivered_at": job.delivered_at,
        "is_overdue": False,
        "next_statuses": sorted(jobs_service.ALLOWED[job.status]),
    }


@router.post("/{job_id}/status", response_model=JobStatusOut)
def set_status(
    job_id: int,
    payload: JobStatusIn,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    """Marking a job ready fires the existing pickup_ready rule - no new trigger code."""
    job, became_ready = jobs_service.change_status(db, context, job_id, payload.status)
    db.commit()

    queued = 0
    if became_ready:
        from app.agents import reminders as reminder_agent  # noqa: PLC0415

        created = reminder_agent.run(
            db, context, kinds=["pickup_ready"], max_per_kind=50, llm_budget=1
        )
        db.commit()
        queued = int(created.get("pickup_ready", 0))

    rows = jobs_service.list_jobs(db, context, limit=500)
    row = next(item for item in rows if item["id"] == job.id)
    return {"job": row, "reminders_queued": queued}
