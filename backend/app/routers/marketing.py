"""Everything the marketing agent owns: segments, outbox, insights, campaigns."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import attribution as attribution_agent
from app.agents import campaigns as campaign_agent
from app.agents import insights as insight_agent
from app.agents import reminders as reminder_agent
from app.agents import segmentation as segmentation_agent
from app.db import get_db
from app.observability import MAX_LIMIT, set_pagination
from app.delivery.base import get_adapter
from app.llm import client as llm
from app.models.agent import Campaign, Reminder, Segment
from app.models.base import utcnow
from app.models.core import Customer
from app.schemas.marketing import (
    CampaignIn,
    CampaignOut,
    CampaignStatusIn,
    InsightOut,
    ReminderOut,
    ReminderRunOut,
    SegmentOut,
    SegmentRebuildOut,
    SendBatchIn,
    SendBatchOut,
    DeliveryStatusOut,
)
from app.services import delivery_service
from app.services.errors import ConflictError, NotFoundError
from app.settings import settings
from app.verticals.context import StoreContext, get_store_context_from_query

router = APIRouter(prefix="/marketing", tags=["marketing"])


# -- segments ----------------------------------------------------------------
@router.post("/segments/rebuild", response_model=SegmentRebuildOut)
def rebuild_segments(
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    distribution = segmentation_agent.rebuild(db, context)
    db.commit()
    return {"store_id": context.store_id, "distribution": distribution}


@router.get("/segments", response_model=list[SegmentOut])
def list_segments(
    segment: str | None = Query(default=None, description="New | Regular | VIP | Inactive"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    response: Response = None,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = (
        select(Segment, Customer)
        .join(Customer, Customer.id == Segment.customer_id)
        .where(Segment.store_id == context.store_id)
    )
    if segment:
        statement = statement.where(Segment.segment == segment)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    statement = statement.order_by(Segment.total_spend.desc()).limit(limit).offset(offset)

    rows = [
        {
            "id": row.id,
            "customer_id": row.customer_id,
            "customer_name": customer.name,
            "phone": customer.phone,
            "segment": row.segment,
            "recency_days": row.recency_days,
            "frequency_90d": row.frequency_90d,
            "total_spend": row.total_spend,
            "computed_at": row.computed_at,
        }
        for row, customer in db.execute(statement).all()
    ]
    set_pagination(response, total=total, limit=limit, offset=offset, returned=len(rows))
    return rows


@router.get("/segments/summary", response_model=dict)
def segment_summary(
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    return segmentation_agent.distribution(db, context.store_id)


# -- reminders ---------------------------------------------------------------
@router.post("/reminders/run", response_model=ReminderRunOut)
def run_reminders(
    max_per_kind: int = Query(default=25, ge=1, le=200),
    llm_budget: int = Query(default=4, ge=0, le=50),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    created = reminder_agent.run(
        db, context, max_per_kind=max_per_kind, llm_budget=llm_budget
    )
    db.commit()
    return {
        "store_id": context.store_id,
        "created": created,
        "total": sum(created.values()),
        "used_llm": llm.available() and llm_budget > 0,
    }


@router.get("/reminders", response_model=list[ReminderOut])
def list_reminders(
    status_filter: str | None = Query(
        default=None, alias="status", description="queued | sent | failed | dismissed"
    ),
    kind: str | None = None,
    limit: int = Query(default=100, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    response: Response = None,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = (
        select(Reminder, Customer)
        .join(Customer, Customer.id == Reminder.customer_id)
        .where(Reminder.store_id == context.store_id)
    )
    if status_filter:
        statement = statement.where(Reminder.status == status_filter)
    if kind:
        statement = statement.where(Reminder.kind == kind)
    total = db.scalar(
        select(func.count()).select_from(statement.subquery())
    )
    statement = statement.order_by(Reminder.created_at.desc()).limit(limit).offset(offset)

    rows = [
        {
            "id": reminder.id,
            "customer_id": reminder.customer_id,
            "customer_name": customer.name,
            "phone": customer.phone,
            "kind": reminder.kind,
            "channel": reminder.channel,
            "message": reminder.message,
            "status": reminder.status,
            "scheduled_for": reminder.scheduled_for,
            "sent_at": reminder.sent_at,
            "provider_response": reminder.provider_response,
            "created_at": reminder.created_at,
        }
        for reminder, customer in db.execute(statement).all()
    ]
    set_pagination(response, total=total, limit=limit, offset=offset, returned=len(rows))
    return rows


@router.post("/reminders/{reminder_id}/send", response_model=ReminderOut)
def send_reminder(
    reminder_id: int,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    reminder = db.get(Reminder, reminder_id)
    if reminder is None or reminder.store_id != context.store_id:
        raise NotFoundError(f"Reminder {reminder_id} does not belong to {context.store_name}")
    if reminder.status != "queued":
        raise ConflictError(
            f"Reminder {reminder_id} is already {reminder.status} and cannot be sent again"
        )

    outcome = delivery_service.send_reminders(db, context, [reminder_id])
    db.commit()
    db.refresh(reminder)
    if outcome.sent == 0 and outcome.failed == 0:
        raise ConflictError(outcome.results[0]["detail"])

    customer = db.get(Customer, reminder.customer_id)
    return {
        "id": reminder.id,
        "customer_id": reminder.customer_id,
        "customer_name": customer.name if customer else None,
        "phone": customer.phone if customer else None,
        "kind": reminder.kind,
        "channel": reminder.channel,
        "message": reminder.message,
        "status": reminder.status,
        "scheduled_for": reminder.scheduled_for,
        "sent_at": reminder.sent_at,
        "created_at": reminder.created_at,
    }


@router.post("/reminders/send", response_model=SendBatchOut)
def send_selected(
    payload: SendBatchIn,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    """Send an explicitly chosen set. Never called by the scheduler (rule 10)."""
    outcome = delivery_service.send_reminders(db, context, payload.reminder_ids)
    db.commit()
    return {
        "store_id": context.store_id,
        "adapter": get_adapter().name,
        "sent": outcome.sent,
        "failed": outcome.failed,
        "skipped": outcome.skipped,
        "cap_remaining": outcome.cap_remaining,
        "results": outcome.results,
    }


@router.get("/delivery/status", response_model=DeliveryStatusOut)
def delivery_status(
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    return {
        "store_id": context.store_id,
        "adapter": get_adapter().name,
        "daily_cap": settings.delivery_daily_cap,
        "sent_today": delivery_service.sent_today(db, context.store_id),
        "cap_remaining": delivery_service.cap_remaining(db, context.store_id),
        "rate_limit_per_minute": settings.delivery_rate_limit_per_minute,
    }


@router.post("/reminders/{reminder_id}/retry", response_model=ReminderOut)
def retry_reminder(
    reminder_id: int,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    """failed -> queued. Never sends - the normal Send action still performs
    the actual delivery attempt, through the same adapter as any other send."""
    reminder = delivery_service.retry_reminder(db, context, reminder_id)
    db.commit()
    db.refresh(reminder)
    customer = db.get(Customer, reminder.customer_id)
    return {
        "id": reminder.id,
        "customer_id": reminder.customer_id,
        "customer_name": customer.name if customer else None,
        "phone": customer.phone if customer else None,
        "kind": reminder.kind,
        "channel": reminder.channel,
        "message": reminder.message,
        "status": reminder.status,
        "scheduled_for": reminder.scheduled_for,
        "sent_at": reminder.sent_at,
        "provider_response": reminder.provider_response,
        "created_at": reminder.created_at,
    }


@router.post("/reminders/{reminder_id}/dismiss", response_model=ReminderOut)
def dismiss_reminder(
    reminder_id: int,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    reminder = db.get(Reminder, reminder_id)
    if reminder is None or reminder.store_id != context.store_id:
        raise NotFoundError(f"Reminder {reminder_id} does not belong to {context.store_name}")
    reminder.status = "dismissed"
    db.commit()
    db.refresh(reminder)
    customer = db.get(Customer, reminder.customer_id)
    return {
        "id": reminder.id,
        "customer_id": reminder.customer_id,
        "customer_name": customer.name if customer else None,
        "phone": customer.phone if customer else None,
        "kind": reminder.kind,
        "channel": reminder.channel,
        "message": reminder.message,
        "status": reminder.status,
        "scheduled_for": reminder.scheduled_for,
        "sent_at": reminder.sent_at,
        "created_at": reminder.created_at,
    }


# -- insights ----------------------------------------------------------------
@router.get("/insights", response_model=InsightOut)
def get_insights(
    force: bool = Query(default=False, description="ignore the 24h cache"),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    insight, source = insight_agent.generate(db, context, force=force)
    db.commit()
    db.refresh(insight)
    return {
        "store_id": insight.store_id,
        "period": insight.period,
        "generated_at": insight.generated_at,
        "metrics": insight.metrics_json,
        "suggestions": insight.suggestions_json,
        "source": source,
    }


# -- campaigns ---------------------------------------------------------------
@router.post("/campaigns", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
def create_campaign(
    payload: CampaignIn,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> Campaign:
    campaign, _ = campaign_agent.create(db, context, payload.occasion)
    db.commit()
    db.refresh(campaign)
    return campaign


@router.get("/campaigns", response_model=list[CampaignOut])
def list_campaigns(
    limit: int = Query(default=20, ge=1, le=100),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[Campaign]:
    return campaign_agent.list_campaigns(db, context.store_id, limit=limit)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
def set_campaign_status(
    campaign_id: int,
    payload: CampaignStatusIn,
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> Campaign:
    campaign = db.get(Campaign, campaign_id)
    if campaign is None or campaign.store_id != context.store_id:
        raise NotFoundError(f"Campaign {campaign_id} does not belong to {context.store_name}")
    campaign.status = payload.status
    db.commit()
    db.refresh(campaign)
    return campaign


# -- campaign attribution ----------------------------------------------------
@router.get("/campaigns/performance")
def campaign_performance(
    limit: int = Query(default=20, ge=1, le=100),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    """Last-touch attribution over a fixed window. Said plainly, on purpose."""
    return {
        "store_id": context.store_id,
        "window_days": attribution_agent.ATTRIBUTION_WINDOW_DAYS,
        "method": attribution_agent.METHOD,
        "campaigns": attribution_agent.performance(db, context, limit=limit),
    }


@router.post("/campaigns/attribution/run")
def run_attribution(
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    result = attribution_agent.run(db, context)
    db.commit()
    return result
