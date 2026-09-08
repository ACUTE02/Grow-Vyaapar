"""Reminder engine.

Loads the enabled reminder_rules for the store's vertical and evaluates each
rule's signal. The engine has no idea what a prescription, a batch or an
alteration is - it only knows signals, gaps and thresholds. Adding a vertical
adds rows, not branches.

Reads core tables, writes only to reminders.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.llm import client as llm
from app.llm import prompts
from app.models.agent import Reminder, Segment
from app.models.base import utcnow
from app.models.config import MessageTemplate, ReminderRule
from app.models.core import (
    Customer,
    Job,
    Product,
    ProductCategory,
    Transaction,
    TransactionItem,
)
from app.settings import settings
from app.verticals.context import StoreContext

logger = logging.getLogger(__name__)

MAX_PER_KIND = 25
# Budget counts batched calls, not messages: 4 calls x 20 = 80 drafted messages.
DEFAULT_LLM_BUDGET = 4
REVIEW_DELAY_HOURS = 2


@dataclass
class Candidate:
    customer_id: int
    facts: dict[str, Any] = field(default_factory=dict)
    scheduled_for: datetime | None = None


class _SafeDict(dict):
    """Leave unknown placeholders alone instead of raising on format()."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


# --------------------------------------------------------------------------- #
# signal evaluators
# --------------------------------------------------------------------------- #
def _signal_last_purchase_in_category(
    db: Session, context: StoreContext, rule: ReminderRule
) -> list[Candidate]:
    """The customer's usual category has gone quiet for longer than the cycle."""
    gap_days = context.cfg_int("reorder_cycle_days", 30)
    cutoff = utcnow() - timedelta(days=gap_days)

    rows = db.execute(
        select(
            Transaction.customer_id,
            ProductCategory.name,
            func.count(TransactionItem.id).label("lines"),
            func.max(Transaction.created_at).label("last_at"),
        )
        .join(TransactionItem, TransactionItem.transaction_id == Transaction.id)
        .join(Product, Product.id == TransactionItem.product_id)
        .join(ProductCategory, ProductCategory.id == Product.category_id)
        .where(
            Transaction.store_id == context.store_id,
            Transaction.status == "completed",
            Transaction.customer_id.is_not(None),
        )
        .group_by(Transaction.customer_id, ProductCategory.name)
    ).all()

    best: dict[int, tuple[int, str, datetime]] = {}
    for customer_id, category, lines, last_at in rows:
        last_at = _as_datetime(last_at)
        current = best.get(customer_id)
        if current is None or lines > current[0]:
            best[customer_id] = (int(lines), category, last_at)

    candidates: list[Candidate] = []
    for customer_id, (_, category, last_at) in best.items():
        if last_at < cutoff:
            candidates.append(
                Candidate(
                    customer_id=customer_id,
                    facts={
                        "category": category,
                        "days": (utcnow() - last_at).days,
                        "cycle_days": gap_days,
                    },
                )
            )
    candidates.sort(key=lambda item: item.facts["days"], reverse=True)
    return candidates


def _signal_last_visit_any(
    db: Session, context: StoreContext, rule: ReminderRule
) -> list[Candidate]:
    gap_days = context.cfg_int("revisit_cycle_days", 90)
    cutoff = utcnow() - timedelta(days=gap_days)

    rows = db.execute(
        select(Transaction.customer_id, func.max(Transaction.created_at))
        .where(
            Transaction.store_id == context.store_id,
            Transaction.status == "completed",
            Transaction.customer_id.is_not(None),
        )
        .group_by(Transaction.customer_id)
    ).all()

    candidates = []
    for customer_id, last_at in rows:
        last_at = _as_datetime(last_at)
        if last_at < cutoff:
            candidates.append(
                Candidate(
                    customer_id=customer_id,
                    facts={"days": (utcnow() - last_at).days, "cycle_days": gap_days},
                )
            )
    candidates.sort(key=lambda item: item.facts["days"], reverse=True)
    return candidates


def _signal_job_status_ready(
    db: Session, context: StoreContext, rule: ReminderRule
) -> list[Candidate]:
    jobs = db.scalars(
        select(Job).where(Job.store_id == context.store_id, Job.status == "ready")
    ).all()
    return [
        Candidate(
            customer_id=job.customer_id,
            facts={"job_type": job.type, "promised_date": str(job.promised_date or "")},
        )
        for job in jobs
    ]


def _signal_transaction_completed(
    db: Session, context: StoreContext, rule: ReminderRule
) -> list[Candidate]:
    """Sales completed in the last day that have not been thanked yet."""
    since = utcnow() - timedelta(days=1)
    rows = db.execute(
        select(Transaction.customer_id, Transaction.invoice_no, Transaction.created_at)
        .where(
            Transaction.store_id == context.store_id,
            Transaction.status == "completed",
            Transaction.customer_id.is_not(None),
            Transaction.created_at >= since,
        )
        .order_by(Transaction.created_at.desc())
    ).all()
    return [
        Candidate(
            customer_id=customer_id,
            facts={"invoice_no": invoice_no},
            scheduled_for=_as_datetime(created_at) + timedelta(hours=REVIEW_DELAY_HOURS),
        )
        for customer_id, invoice_no, created_at in rows
    ]


def _signal_segment_inactive(
    db: Session, context: StoreContext, rule: ReminderRule
) -> list[Candidate]:
    """Two sources, one signal.

    First the customers the churn model says are about to go quiet but have not
    yet - contacting them is the whole point of having a model. Then the ones
    already filed Inactive, who are a rescue job rather than a save.
    """
    from app.agents import churn as churn_agent  # noqa: PLC0415  (avoids a cycle)

    inactive_days = context.cfg_int("inactive_days", 90)

    at_risk = churn_agent.at_risk_customers(
        db, context.store_id, exclude_inactive=True, limit=MAX_PER_KIND
    )
    predicted = [
        Candidate(
            customer_id=row["customer_id"],
            facts={
                "days": row.get("recency_days") or 0,
                "total_spend": row.get("total_spend") or 0.0,
                "churn_probability": round(row["probability"], 2),
                "reason": "predicted at risk, not yet lapsed",
            },
        )
        for row in at_risk
    ]

    rows = db.scalars(
        select(Segment).where(
            Segment.store_id == context.store_id, Segment.segment == "Inactive"
        )
    ).all()
    lapsed = [
        Candidate(
            customer_id=segment.customer_id,
            facts={
                "days": segment.recency_days or inactive_days,
                "total_spend": float(segment.total_spend or 0),
                "reason": "already inactive",
            },
        )
        for segment in rows
    ]
    lapsed.sort(key=lambda item: item.facts["days"], reverse=True)

    seen = {candidate.customer_id for candidate in predicted}
    return predicted + [item for item in lapsed if item.customer_id not in seen]


def _signal_customer_dob_or_anniversary(
    db: Session, context: StoreContext, rule: ReminderRule
) -> list[Candidate]:
    target = date.today() + timedelta(days=rule.offset_days or 0)
    customers = db.scalars(
        select(Customer).where(Customer.store_id == context.store_id)
    ).all()

    candidates = []
    for customer in customers:
        occasion = None
        if customer.dob and (customer.dob.month, customer.dob.day) == (target.month, target.day):
            occasion = "Birthday"
        elif customer.anniversary and (
            customer.anniversary.month,
            customer.anniversary.day,
        ) == (target.month, target.day):
            occasion = "Anniversary"
        if occasion:
            candidates.append(
                Candidate(customer_id=customer.id, facts={"occasion": occasion})
            )
    return candidates


SIGNALS: dict[str, Callable[[Session, StoreContext, ReminderRule], list[Candidate]]] = {
    "last_purchase_in_category": _signal_last_purchase_in_category,
    "last_visit_any": _signal_last_visit_any,
    "job_status_ready": _signal_job_status_ready,
    "transaction_completed": _signal_transaction_completed,
    "segment_inactive": _signal_segment_inactive,
    "customer_dob_or_anniversary": _signal_customer_dob_or_anniversary,
}

# Signals that should not be replayed for the same customer for a while.
COOLDOWN_DAYS = {"segment_inactive": 7, "last_purchase_in_category": 7, "last_visit_any": 14}


# --------------------------------------------------------------------------- #
# message drafting
# --------------------------------------------------------------------------- #
def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _template_for(db: Session, rule: ReminderRule, language: str) -> MessageTemplate | None:
    template = db.scalar(
        select(MessageTemplate).where(
            MessageTemplate.template_key == rule.template_key,
            MessageTemplate.language == language,
        )
    )
    if template is not None:
        return template
    return db.scalar(
        select(MessageTemplate).where(MessageTemplate.template_key == rule.template_key)
    )


def _fill_template(
    db: Session,
    context: StoreContext,
    rule: ReminderRule,
    customer: Customer,
    facts: dict[str, Any],
) -> tuple[str, _SafeDict, MessageTemplate | None]:
    """The message every reminder is guaranteed to have, before any model runs."""
    template = _template_for(db, rule, context.language)
    values = _SafeDict(
        customer_name=customer.name.split()[0],
        store_name=context.store_name,
        city=context.city,
        review_url=context.google_review_url or "",
        unit=context.unit_label,
        **{key: value for key, value in facts.items()},
    )
    body = (
        template.body.format_map(values)
        if template
        else f"Hello {values['customer_name']}, a message from {context.store_name}."
    )
    return body, values, template


def _acceptable(text: str | None, fallback: str) -> str:
    """A model reply is only used if it is short, filled in and not empty."""
    if not text:
        return fallback
    cleaned = str(text).strip().strip('"')
    if not cleaned or len(cleaned) > 400 or "{" in cleaned:
        return fallback
    return cleaned


def draft_message(
    db: Session,
    context: StoreContext,
    rule: ReminderRule,
    customer: Customer,
    facts: dict[str, Any],
    *,
    use_llm: bool,
) -> str:
    """Template first, LLM as an upgrade. The template is always a valid message."""
    body, values, template = _fill_template(db, context, rule, customer, facts)

    if not use_llm or not llm.available():
        return body

    prompt = prompts.reminder_prompt(
        context,
        instruction=(template.llm_instruction if template else "Write a short shop message"),
        fallback_body=body,
        facts=values,
    )
    return _acceptable(llm.call(prompt, max_tokens=400, db=db), body)


def _batch_timeout(item_count: int) -> float:
    """A 20-item batch asks for 8000 tokens and a reasoning model needs real
    wall-clock time to write that much, thinking pass included - the default
    LLM_TIMEOUT_SECONDS is sized for one message, not twenty, and a batch call
    was timing out before any response came back regardless of token budget.
    Scale with the batch, capped so one HTTP call can't hang indefinitely.
    """
    return min(60.0, max(settings.llm_timeout_seconds, 3.0 * item_count))


def draft_batch(
    db: Session, context: StoreContext, pending: list[dict[str, Any]], *, budget: int
) -> None:
    """Upgrade as many pending messages as the budget allows, in batched calls.

    Each call drafts up to LLM_BATCH_SIZE messages. Any customer id the model
    omits, or answers badly, keeps the template message already on the entry.
    A batch never contains the same customer twice, because the reply is keyed
    by customer id.
    """
    if budget <= 0 or not llm.available() or not pending:
        return

    remaining = [entry for entry in pending if not entry.get("drafted")]
    batch_size = max(int(settings.llm_batch_size), 1)

    for _ in range(budget):
        if not remaining:
            return
        batch: list[dict[str, Any]] = []
        seen: set[int] = set()
        leftover: list[dict[str, Any]] = []
        for entry in remaining:
            if len(batch) < batch_size and entry["customer_id"] not in seen:
                seen.add(entry["customer_id"])
                batch.append(entry)
            else:
                leftover.append(entry)
        remaining = leftover

        items = [
            {
                "customer_id": entry["customer_id"],
                "customer_name": entry["customer_name"],
                "instruction": entry["instruction"],
                "facts": entry["facts"],
                "fallback": entry["message"],
            }
            for entry in batch
        ]
        parsed = prompts.parse_json_block(
            llm.call(
                prompts.batch_reminder_prompt(context, items),
                max_tokens=400 * len(items),
                timeout=_batch_timeout(len(items)),
                db=db,
            )
        )
        messages = (parsed or {}).get("messages") if isinstance(parsed, dict) else None
        if not isinstance(messages, dict):
            logger.info("Batch draft unusable, %s messages keep their templates", len(batch))
            for entry in batch:
                entry["drafted"] = True
            continue

        by_id = {str(key): value for key, value in messages.items()}
        for entry in batch:
            entry["message"] = _acceptable(
                by_id.get(str(entry["customer_id"])), entry["message"]
            )
            entry["drafted"] = True


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #
def _open_kinds(db: Session, store_id: int) -> set[tuple[int, str]]:
    rows = db.execute(
        select(Reminder.customer_id, Reminder.kind).where(
            Reminder.store_id == store_id, Reminder.status == "queued"
        )
    ).all()
    return {(customer_id, kind) for customer_id, kind in rows}


def _recent_kinds(db: Session, store_id: int, kind: str, days: int) -> set[int]:
    since = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(Reminder.customer_id).where(
            Reminder.store_id == store_id,
            Reminder.kind == kind,
            Reminder.created_at >= since,
        )
    ).all()
    return {row[0] for row in rows}


def run(
    db: Session,
    context: StoreContext,
    *,
    max_per_kind: int = MAX_PER_KIND,
    llm_budget: int = DEFAULT_LLM_BUDGET,
    kinds: list[str] | None = None,
) -> dict[str, int]:
    """Evaluate every enabled rule for this store. Returns counts per kind."""
    rules = db.scalars(
        select(ReminderRule)
        .where(ReminderRule.vertical_id == context.vertical_id, ReminderRule.enabled.is_(True))
        .order_by(ReminderRule.kind)
    ).all()

    open_pairs = _open_kinds(db, context.store_id)
    created: dict[str, int] = {}
    pending: list[dict[str, Any]] = []

    for rule in rules:
        if kinds and rule.kind not in kinds:
            continue
        evaluator = SIGNALS.get(rule.signal)
        if evaluator is None:
            logger.warning("No evaluator for signal '%s', rule %s skipped", rule.signal, rule.id)
            continue

        cooldown = COOLDOWN_DAYS.get(rule.signal)
        recent = (
            _recent_kinds(db, context.store_id, rule.kind, cooldown) if cooldown else set()
        )

        made = 0
        for candidate in evaluator(db, context, rule):
            if made >= max_per_kind:
                break
            if (candidate.customer_id, rule.kind) in open_pairs:
                continue
            if candidate.customer_id in recent:
                continue
            customer = db.get(Customer, candidate.customer_id)
            if customer is None or customer.store_id != context.store_id:
                continue
            if not customer.marketing_opt_in:
                continue          # consent is checked before a message is drafted

            body, _, template = _fill_template(db, context, rule, customer, candidate.facts)
            pending.append(
                {
                    "customer_id": customer.id,
                    "customer_name": customer.name.split()[0],
                    "rule": rule,
                    "kind": rule.kind,
                    "channel": rule.channel,
                    "facts": candidate.facts,
                    "instruction": (
                        template.llm_instruction if template else "Write a short shop message"
                    ),
                    "message": body,
                    "scheduled_for": candidate.scheduled_for or utcnow(),
                }
            )
            open_pairs.add((customer.id, rule.kind))
            made += 1

        if made:
            created[rule.kind] = created.get(rule.kind, 0) + made

    # One network round trip per batch, not one per customer.
    draft_batch(db, context, pending, budget=llm_budget)

    for entry in pending:
        db.add(
            Reminder(
                store_id=context.store_id,
                customer_id=entry["customer_id"],
                rule_id=entry["rule"].id,
                kind=entry["kind"],
                channel=entry["channel"],
                message=entry["message"],
                status="queued",
                scheduled_for=entry["scheduled_for"],
            )
        )

    db.flush()
    return created


def on_transaction_completed(
    db: Session, context: StoreContext, transaction_id: int
) -> Reminder | None:
    """Post-sale hook. Nobody asks for this: a completed sale is itself the trigger."""
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.customer_id is None:
        return None
    if transaction.status != "completed":
        return None

    rule = db.scalar(
        select(ReminderRule).where(
            ReminderRule.vertical_id == context.vertical_id,
            ReminderRule.signal == "transaction_completed",
            ReminderRule.enabled.is_(True),
        )
    )
    if rule is None:
        return None

    already = db.scalar(
        select(Reminder).where(
            Reminder.store_id == context.store_id,
            Reminder.customer_id == transaction.customer_id,
            Reminder.kind == rule.kind,
            Reminder.status == "queued",
        )
    )
    if already is not None:
        return already

    customer = db.get(Customer, transaction.customer_id)
    if customer is None or not customer.marketing_opt_in:
        return None

    message = draft_message(
        db,
        context,
        rule,
        customer,
        {"invoice_no": transaction.invoice_no, "total": float(transaction.total)},
        use_llm=True,
    )
    reminder = Reminder(
        store_id=context.store_id,
        customer_id=customer.id,
        rule_id=rule.id,
        kind=rule.kind,
        channel=rule.channel,
        message=message,
        status="queued",
        scheduled_for=transaction.created_at + timedelta(hours=REVIEW_DELAY_HOURS),
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder
