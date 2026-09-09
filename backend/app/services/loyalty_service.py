"""Loyalty points and referrals.

The balance on loyalty_accounts is a cache of the ledger, never an independent
number: every change goes through `_post`, which writes a ledger row and then
recomputes the balance from it. A test asserts the two agree.
"""
from __future__ import annotations

import logging
import secrets
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.commerce import LoyaltyAccount, LoyaltyLedger, Referral
from app.models.core import Customer, Transaction
from app.services.errors import ConflictError, NotFoundError, ValidationError
from app.verticals.context import StoreContext

logger = logging.getLogger(__name__)

REFERRAL_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no look-alike characters


# --------------------------------------------------------------------------- #
# accounts and the ledger
# --------------------------------------------------------------------------- #
def account_for(db: Session, context: StoreContext, customer_id: int) -> LoyaltyAccount:
    """The customer's points account at this store, opened on first use.

    The customer is checked before the account is opened, because the lookup
    below only scopes the *query* by store: asked for a customer belonging to
    somebody else, it found nothing and cheerfully created an account linking
    this store to that customer, then answered with it. That made
    GET /loyalty/customers/{id} a cross-tenant read - and a cross-tenant write
    on a GET - for any customer id worth guessing.
    """
    customer = db.get(Customer, customer_id)
    if customer is None or customer.store_id != context.store_id:
        raise NotFoundError(f"Customer {customer_id} is not registered at {context.store_name}")

    account = db.scalar(
        select(LoyaltyAccount).where(
            LoyaltyAccount.store_id == context.store_id,
            LoyaltyAccount.customer_id == customer_id,
        )
    )
    if account is None:
        account = LoyaltyAccount(store_id=context.store_id, customer_id=customer_id)
        db.add(account)
        db.flush()
    return account


def ledger_balance(db: Session, account_id: int) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(LoyaltyLedger.points_delta), 0)).where(
                LoyaltyLedger.loyalty_account_id == account_id
            )
        )
        or 0
    )


def _post(
    db: Session,
    account: LoyaltyAccount,
    *,
    points: int,
    reason: str,
    transaction_id: int | None = None,
) -> LoyaltyLedger:
    entry = LoyaltyLedger(
        loyalty_account_id=account.id,
        transaction_id=transaction_id,
        points_delta=int(points),
        reason=reason,
    )
    db.add(entry)
    db.flush()

    account.points_balance = ledger_balance(db, account.id)
    if points > 0:
        account.lifetime_points += int(points)
    account.updated_at = utcnow()
    db.flush()
    return entry


# --------------------------------------------------------------------------- #
# earning and spending
# --------------------------------------------------------------------------- #
def points_for_spend(context: StoreContext, amount: Decimal) -> int:
    """The rate is a config row: a chemist on thin margins gives fewer points."""
    per_point = context.cfg_int("loyalty_rupees_per_point", 100)
    if per_point <= 0:
        return 0
    return int(Decimal(str(amount)) // Decimal(per_point))


def value_of_points(context: StoreContext, points: int) -> Decimal:
    return (Decimal(int(points)) * Decimal(str(context.cfg("loyalty_point_value", 1)))).quantize(
        Decimal("0.01")
    )


def quote_redemption(
    db: Session, context: StoreContext, customer_id: int | None, points: int
) -> Decimal:
    """What `points` are worth on this bill, refusing more than the balance holds."""
    if points <= 0:
        return Decimal("0.00")
    if customer_id is None:
        raise ValidationError("Points can only be spent by a named customer, not a walk-in")

    account = account_for(db, context, customer_id)
    if points > account.points_balance:
        raise ConflictError(
            f"That customer has {account.points_balance} points, {points} were requested"
        )
    return value_of_points(context, points)


def accrue_for_sale(
    db: Session, context: StoreContext, transaction: Transaction
) -> int:
    """Points on a completed sale. Returns how many were awarded."""
    if transaction.customer_id is None or transaction.status != "completed":
        return 0
    points = points_for_spend(context, transaction.total)
    if points <= 0:
        return 0
    account = account_for(db, context, transaction.customer_id)
    _post(db, account, points=points, reason="earned on sale", transaction_id=transaction.id)
    return points


def spend_for_sale(
    db: Session, context: StoreContext, transaction: Transaction, points: int
) -> None:
    if points <= 0 or transaction.customer_id is None:
        return
    account = account_for(db, context, transaction.customer_id)
    _post(
        db,
        account,
        points=-int(points),
        reason="redeemed on sale",
        transaction_id=transaction.id,
    )


def reverse_for_refund(db: Session, context: StoreContext, transaction: Transaction) -> None:
    """A refund undoes both the earning and the spending, as new ledger rows."""
    entries = db.scalars(
        select(LoyaltyLedger).where(LoyaltyLedger.transaction_id == transaction.id)
    ).all()
    for entry in entries:
        account = db.get(LoyaltyAccount, entry.loyalty_account_id)
        if account is None:
            continue
        _post(
            db,
            account,
            points=-entry.points_delta,
            reason=f"reversed: {entry.reason}",
            transaction_id=transaction.id,
        )


def history(db: Session, context: StoreContext, customer_id: int) -> dict[str, Any]:
    account = account_for(db, context, customer_id)
    entries = db.scalars(
        select(LoyaltyLedger)
        .where(LoyaltyLedger.loyalty_account_id == account.id)
        .order_by(LoyaltyLedger.created_at.desc(), LoyaltyLedger.id.desc())
        .limit(50)
    ).all()
    return {
        "customer_id": customer_id,
        "points_balance": account.points_balance,
        "lifetime_points": account.lifetime_points,
        "point_value": float(value_of_points(context, 1)),
        "rupees_per_point": context.cfg_int("loyalty_rupees_per_point", 100),
        "ledger": [
            {
                "id": entry.id,
                "points_delta": entry.points_delta,
                "reason": entry.reason,
                "transaction_id": entry.transaction_id,
                "created_at": entry.created_at,
            }
            for entry in entries
        ],
    }


# --------------------------------------------------------------------------- #
# referrals
# --------------------------------------------------------------------------- #
def _new_code(db: Session, store_id: int, name: str) -> str:
    prefix = "".join(character for character in name.upper() if character.isalpha())[:3] or "REF"
    for _ in range(20):
        code = prefix + "".join(secrets.choice(REFERRAL_ALPHABET) for _ in range(4))
        clash = db.scalar(
            select(Referral).where(Referral.store_id == store_id, Referral.code == code)
        )
        if clash is None:
            return code
    raise ConflictError("Could not allocate a referral code, try again")


def referral_code_for(db: Session, context: StoreContext, customer_id: int) -> Referral:
    """One open code per customer; it is reissued only once it has been used."""
    customer = db.get(Customer, customer_id)
    if customer is None or customer.store_id != context.store_id:
        raise NotFoundError(f"Customer {customer_id} is not registered at {context.store_name}")

    open_code = db.scalar(
        select(Referral).where(
            Referral.store_id == context.store_id,
            Referral.referrer_customer_id == customer_id,
            Referral.status == "issued",
        )
    )
    if open_code is not None:
        return open_code

    referral = Referral(
        store_id=context.store_id,
        referrer_customer_id=customer_id,
        code=_new_code(db, context.store_id, customer.name),
        status="issued",
    )
    db.add(referral)
    db.flush()
    return referral


def claim_referral(
    db: Session, context: StoreContext, code: str, new_customer_id: int
) -> Referral | None:
    """Attach a new customer to whoever referred them. Reward comes on first sale."""
    cleaned = (code or "").strip().upper()
    if not cleaned:
        return None
    referral = db.scalar(
        select(Referral).where(
            Referral.store_id == context.store_id,
            Referral.code == cleaned,
            Referral.status == "issued",
        )
    )
    if referral is None:
        raise NotFoundError(f"Referral code {cleaned} is not valid at {context.store_name}")
    if referral.referrer_customer_id == new_customer_id:
        raise ConflictError("A customer cannot refer themselves")

    referral.referred_customer_id = new_customer_id
    referral.status = "claimed"
    db.flush()
    return referral


def reward_if_first_sale(
    db: Session, context: StoreContext, transaction: Transaction
) -> Referral | None:
    """Called after a sale completes. Pays the referrer once, on the first purchase."""
    if transaction.customer_id is None:
        return None

    referral = db.scalar(
        select(Referral).where(
            Referral.store_id == context.store_id,
            Referral.referred_customer_id == transaction.customer_id,
            Referral.status == "claimed",
        )
    )
    if referral is None:
        return None

    earlier = db.scalar(
        select(func.count(Transaction.id)).where(
            Transaction.store_id == context.store_id,
            Transaction.customer_id == transaction.customer_id,
            Transaction.status == "completed",
            Transaction.id != transaction.id,
        )
    )
    if earlier:
        return None                      # not their first purchase, nothing owed

    points = context.cfg_int("referral_reward_points", 50)
    account = account_for(db, context, referral.referrer_customer_id)
    _post(
        db,
        account,
        points=points,
        reason=f"referral reward for customer {transaction.customer_id}",
        transaction_id=transaction.id,
    )
    referral.status = "rewarded"
    referral.rewarded_at = utcnow()
    db.flush()
    logger.info(
        "Referral %s rewarded %s points to customer %s",
        referral.code,
        points,
        referral.referrer_customer_id,
    )
    return referral


def list_referrals(db: Session, context: StoreContext, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Referral, Customer)
        .join(Customer, Customer.id == Referral.referrer_customer_id)
        .where(Referral.store_id == context.store_id)
        .order_by(Referral.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": referral.id,
            "code": referral.code,
            "referrer_customer_id": referral.referrer_customer_id,
            "referrer_name": customer.name,
            "referred_customer_id": referral.referred_customer_id,
            "status": referral.status,
            "rewarded_at": referral.rewarded_at,
            "created_at": referral.created_at,
        }
        for referral, customer in rows
    ]
