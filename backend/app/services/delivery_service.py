"""Sending, with the guard rails that make it safe to point at a real phone.

Three rules, all of them deliberate:

1. Sending is an explicit act on an explicit list of reminder ids. Nothing here
   is reachable from the scheduler (rule 10).
2. A hard daily cap per store. A bug in a rule cannot turn into fifty thousand
   messages; the cap refuses and says so.
3. Consent is checked twice - the engine will not draft for an opted-out
   customer, and this refuses to send to one even if a row already existed.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, time as time_of_day
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.delivery.base import get_adapter
from app.models.agent import Reminder
from app.models.base import utcnow
from app.models.core import Customer
from app.services.errors import ConflictError, NotFoundError
from app.settings import settings
from app.verticals.context import StoreContext

logger = logging.getLogger(__name__)


@dataclass
class SendOutcome:
    sent: int
    failed: int
    skipped: int
    results: list[dict[str, Any]]
    cap_remaining: int


def sent_today(db: Session, store_id: int) -> int:
    start = datetime.combine(utcnow().date(), time_of_day.min)
    return int(
        db.scalar(
            select(func.count(Reminder.id)).where(
                Reminder.store_id == store_id,
                Reminder.status == "sent",
                Reminder.sent_at >= start,
            )
        )
        or 0
    )


def cap_remaining(db: Session, store_id: int) -> int:
    return max(settings.delivery_daily_cap - sent_today(db, store_id), 0)


def send_reminders(
    db: Session, context: StoreContext, reminder_ids: list[int]
) -> SendOutcome:
    """Send exactly these reminders, in order, until the cap stops us."""
    if not reminder_ids:
        raise NotFoundError("No reminders were selected to send")

    adapter = get_adapter()
    remaining = cap_remaining(db, context.store_id)
    if remaining <= 0:
        raise ConflictError(
            f"The daily send cap of {settings.delivery_daily_cap} messages for "
            f"{context.store_name} is already used up. Nothing was sent. The cap resets "
            "at midnight, or raise DELIVERY_DAILY_CAP if you meant to send more."
        )

    per_minute = max(int(settings.delivery_rate_limit_per_minute), 1)
    gap = 60.0 / per_minute
    results: list[dict[str, Any]] = []
    sent = failed = skipped = 0
    last_send = 0.0

    for reminder_id in reminder_ids:
        reminder = db.get(Reminder, reminder_id)
        if reminder is None or reminder.store_id != context.store_id:
            raise NotFoundError(
                f"Reminder {reminder_id} does not belong to {context.store_name}"
            )
        if reminder.status != "queued":
            skipped += 1
            results.append(
                {
                    "reminder_id": reminder_id,
                    "status": reminder.status,
                    "detail": f"already {reminder.status}, left alone",
                }
            )
            continue

        customer = db.get(Customer, reminder.customer_id)
        if customer is None or not customer.marketing_opt_in:
            reminder.status = "failed"
            reminder.provider_response = "customer has opted out of marketing messages"
            failed += 1
            results.append(
                {
                    "reminder_id": reminder_id,
                    "status": "failed",
                    "detail": reminder.provider_response,
                }
            )
            continue

        if sent >= remaining:
            skipped += 1
            results.append(
                {
                    "reminder_id": reminder_id,
                    "status": "queued",
                    "detail": (
                        f"daily cap of {settings.delivery_daily_cap} reached, "
                        "left in the queue for tomorrow"
                    ),
                }
            )
            continue

        if last_send and adapter.name != "console":
            elapsed = time.monotonic() - last_send
            if elapsed < gap:
                time.sleep(gap - elapsed)

        outcome = adapter.send(reminder, db)
        last_send = time.monotonic()

        reminder.status = outcome.status
        reminder.provider_response = outcome.detail
        if outcome.status == "sent":
            reminder.sent_at = utcnow()
            sent += 1
        else:
            failed += 1
        results.append(
            {
                "reminder_id": reminder_id,
                "status": outcome.status,
                "detail": outcome.detail,
            }
        )

    db.flush()
    logger.info(
        "Store %s: sent %s, failed %s, skipped %s via %s",
        context.store_id,
        sent,
        failed,
        skipped,
        adapter.name,
    )
    return SendOutcome(
        sent=sent,
        failed=failed,
        skipped=skipped,
        results=results,
        cap_remaining=cap_remaining(db, context.store_id),
    )
