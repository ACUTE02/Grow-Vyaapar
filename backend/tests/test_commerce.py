"""Coupons, loyalty, referrals and attribution."""
from __future__ import annotations

import uuid

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.agents import attribution
from app.models.agent import Campaign, Reminder
from app.models.base import utcnow
from app.models.commerce import Coupon, CouponRedemption, LoyaltyAccount, LoyaltyLedger
from app.models.core import Customer, Product, StockLevel
from app.services import coupon_service, loyalty_service
from app.verticals.context import resolve_store_context
from tests.test_segmentation import _store


def _idempotency_key() -> dict[str, str]:
    """A fresh Idempotency-Key per checkout, which the sale endpoint requires."""
    return {"Idempotency-Key": uuid.uuid4().hex}


PHONES = iter(range(4_000_000, 5_000_000))


def _customer(db, store, name: str = "Anjali Rao") -> Customer:
    customer = Customer(store_id=store.id, name=name, phone=f"9{next(PHONES):09d}")
    db.add(customer)
    db.commit()
    return customer


def _product(db, store, price: str = "1000.00") -> Product:
    product = Product(
        store_id=store.id,
        sku=f"SKU-{store.id}-{price}",
        name="Test item",
        cost_price=Decimal("400.00"),
        sell_price=Decimal(price),
        gst_rate=Decimal("0"),
        attributes={},
    )
    db.add(product)
    db.flush()
    db.add(
        StockLevel(product_id=product.id, qty_on_hand=Decimal("500"), reorder_point=Decimal("5"))
    )
    db.commit()
    return product


def _sell(client, store, product, customer=None, **extra):
    body = {"lines": [{"product_id": product.id, "qty": 1}]}
    if customer is not None:
        body["customer_id"] = customer.id
    body.update(extra)
    return client.post(f"/billing/transactions?store_id={store.id}", json=body, headers=_idempotency_key())


# -- coupons -----------------------------------------------------------------
def test_a_coupon_code_is_generated_from_the_occasion() -> None:
    assert coupon_service.suggest_code("Diwali", Decimal("20"), "percent") == "DIWALI20"
    assert coupon_service.suggest_code("New Year", Decimal("100"), "flat") == "NEWYEARF100"


def test_a_percentage_coupon_reduces_the_bill_and_counts_a_redemption(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "1000.00")
    customer = _customer(db, store)
    coupon = client.post(
        f"/loyalty/coupons?store_id={store.id}",
        json={"code": "DIWALI20", "discount_type": "percent", "discount_value": 20},
    ).json()

    sale = _sell(client, store, product, customer, coupon_code="diwali20")
    assert sale.status_code == 201, sale.text
    body = sale.json()
    assert Decimal(body["subtotal"]) == Decimal("1000.00")
    assert Decimal(body["discount"]) == Decimal("200.00")
    assert Decimal(body["total"]) == Decimal("800.00")

    db.expire_all()
    assert db.get(Coupon, coupon["id"]).times_redeemed == 1
    assert db.scalar(select(func.count(CouponRedemption.id))) == 1


def test_a_flat_coupon_never_exceeds_the_bill(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "150.00")
    client.post(
        f"/loyalty/coupons?store_id={store.id}",
        json={"code": "FLAT500", "discount_type": "flat", "discount_value": 500},
    )
    body = _sell(client, store, product, coupon_code="FLAT500").json()
    assert Decimal(body["discount"]) == Decimal("150.00")
    assert Decimal(body["total"]) == Decimal("0.00")


def test_a_coupon_past_its_cap_is_refused(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store)
    client.post(
        f"/loyalty/coupons?store_id={store.id}",
        json={"code": "ONCE", "discount_type": "percent", "discount_value": 10,
              "max_redemptions": 1},
    )
    assert _sell(client, store, product, coupon_code="ONCE").status_code == 201
    second = _sell(client, store, product, coupon_code="ONCE")
    assert second.status_code == 409
    assert "limit of 1" in second.json()["detail"]


def test_a_coupon_outside_its_validity_window_is_refused(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store)
    client.post(
        f"/loyalty/coupons?store_id={store.id}",
        json={
            "code": "EXPIRED",
            "discount_type": "percent",
            "discount_value": 10,
            "valid_from": str(date.today() - timedelta(days=30)),
            "valid_to": str(date.today() - timedelta(days=1)),
        },
    )
    response = _sell(client, store, product, coupon_code="EXPIRED")
    assert response.status_code == 409
    assert "expired on" in response.json()["detail"]


def test_an_unknown_coupon_is_404(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store)
    assert _sell(client, store, product, coupon_code="NOPE").status_code == 404


def test_a_refund_gives_the_coupon_use_back(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store)
    coupon = client.post(
        f"/loyalty/coupons?store_id={store.id}",
        json={"code": "BACK10", "discount_type": "percent", "discount_value": 10},
    ).json()
    sale = _sell(client, store, product, coupon_code="BACK10").json()
    client.post(f"/billing/transactions/{sale['id']}/refund?store_id={store.id}")

    db.expire_all()
    assert db.get(Coupon, coupon["id"]).times_redeemed == 0


# -- loyalty -----------------------------------------------------------------
def test_points_accrue_at_the_rate_the_vertical_sets(client, db) -> None:
    """A kirana gives a point per 100 rupees; a chemist per 200."""
    grocery = _store(db, "grocery", "Sharma Kirana")
    pharmacy = _store(db, "pharmacy", "Jeevan Medical")
    for store in (grocery, pharmacy):
        product = _product(db, store, "1000.00")
        customer = _customer(db, store)
        _sell(client, store, product, customer)
        balance = client.get(
            f"/loyalty/customers/{customer.id}?store_id={store.id}"
        ).json()
        expected = 10 if store is grocery else 5
        assert balance["points_balance"] == expected, store.name


def test_the_balance_always_equals_the_ledger(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "500.00")
    customer = _customer(db, store)

    for _ in range(3):
        _sell(client, store, product, customer)
    _sell(client, store, product, customer, redeem_points=5)

    db.expire_all()
    account = db.scalar(
        select(LoyaltyAccount).where(LoyaltyAccount.customer_id == customer.id)
    )
    ledger_total = db.scalar(
        select(func.coalesce(func.sum(LoyaltyLedger.points_delta), 0)).where(
            LoyaltyLedger.loyalty_account_id == account.id
        )
    )
    assert account.points_balance == ledger_total
    assert account.lifetime_points >= account.points_balance


def test_points_redeemed_come_off_the_bill(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "1000.00")
    customer = _customer(db, store)

    _sell(client, store, product, customer)               # earns 10 points
    body = _sell(client, store, product, customer, redeem_points=10).json()

    assert Decimal(body["discount"]) == Decimal("10.00")   # 10 points at 1 rupee
    assert Decimal(body["total"]) == Decimal("990.00")

    balance = client.get(f"/loyalty/customers/{customer.id}?store_id={store.id}").json()
    assert balance["points_balance"] == 9                  # 10 - 10 spent + 9 earned


def test_spending_more_points_than_the_balance_is_refused(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "1000.00")
    customer = _customer(db, store)
    response = _sell(client, store, product, customer, redeem_points=500)
    assert response.status_code == 409
    assert "0 points" in response.json()["detail"]


def test_a_walk_in_cannot_spend_points(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store)
    response = _sell(client, store, product, redeem_points=5)
    assert response.status_code == 422
    assert "walk-in" in response.json()["detail"]


def test_a_refund_reverses_the_points(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "1000.00")
    customer = _customer(db, store)
    sale = _sell(client, store, product, customer).json()

    before = client.get(f"/loyalty/customers/{customer.id}?store_id={store.id}").json()
    assert before["points_balance"] == 10

    client.post(f"/billing/transactions/{sale['id']}/refund?store_id={store.id}")
    after = client.get(f"/loyalty/customers/{customer.id}?store_id={store.id}").json()
    assert after["points_balance"] == 0
    assert any("reversed" in entry["reason"] for entry in after["ledger"])


# -- referrals ---------------------------------------------------------------
def test_a_referrer_is_rewarded_on_the_referred_customers_first_sale(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "500.00")
    referrer = _customer(db, store, "Referrer Ramesh")

    code = client.post(f"/loyalty/referrals/{referrer.id}?store_id={store.id}").json()["code"]

    referred = client.post(
        f"/customers?store_id={store.id}",
        json={"name": "New Neha", "phone": "9812345678", "referral_code": code},
    ).json()

    balance_before = client.get(
        f"/loyalty/customers/{referrer.id}?store_id={store.id}"
    ).json()["points_balance"]

    db.expire_all()
    referred_row = db.get(Customer, referred["id"])
    _sell(client, store, product, referred_row)

    balance_after = client.get(
        f"/loyalty/customers/{referrer.id}?store_id={store.id}"
    ).json()["points_balance"]
    assert balance_after == balance_before + 50

    referrals = client.get(f"/loyalty/referrals?store_id={store.id}").json()
    assert referrals[0]["status"] == "rewarded"


def test_the_referrer_is_only_rewarded_once(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "500.00")
    referrer = _customer(db, store, "Referrer Ramesh")
    code = client.post(f"/loyalty/referrals/{referrer.id}?store_id={store.id}").json()["code"]
    referred = client.post(
        f"/customers?store_id={store.id}",
        json={"name": "New Neha", "phone": "9812345678", "referral_code": code},
    ).json()

    db.expire_all()
    referred_row = db.get(Customer, referred["id"])
    _sell(client, store, product, referred_row)
    first = client.get(f"/loyalty/customers/{referrer.id}?store_id={store.id}").json()
    _sell(client, store, product, referred_row)
    second = client.get(f"/loyalty/customers/{referrer.id}?store_id={store.id}").json()

    assert first["points_balance"] == second["points_balance"]


def test_an_invalid_referral_code_is_rejected(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    response = client.post(
        f"/customers?store_id={store.id}",
        json={"name": "New Neha", "phone": "9812345678", "referral_code": "BOGUS"},
    )
    assert response.status_code == 404


# -- attribution -------------------------------------------------------------
def test_a_campaign_that_reached_customers_who_bought_shows_revenue(client, rules) -> None:
    db = rules
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "1000.00")
    customer = _customer(db, store)
    context = resolve_store_context(db, store.id)

    campaign = Campaign(
        store_id=store.id,
        occasion="Diwali",
        caption="Diwali at the shop",
        hashtags=["#Diwali"],
        status="published",
        created_at=utcnow() - timedelta(days=2),
    )
    db.add(campaign)
    db.flush()
    db.add(
        Reminder(
            store_id=store.id,
            customer_id=customer.id,
            kind="winback",
            channel="whatsapp",
            message="Come by for Diwali",
            status="sent",
            sent_at=utcnow() - timedelta(days=2),
            created_at=utcnow() - timedelta(days=2),
        )
    )
    db.commit()

    _sell(client, store, product, customer)          # the visit inside the window

    attribution.run(db, context)
    db.commit()

    performance = client.get(f"/marketing/campaigns/performance?store_id={store.id}").json()
    row = performance["campaigns"][0]
    assert row["customers_reached"] == 1
    assert row["visits_attributed"] == 1
    assert row["revenue_attributed"] == 1000.0
    assert row["conversion_rate"] == 1.0
    assert "not causation" in performance["method"]


def test_a_campaign_nobody_was_messaged_about_attributes_nothing(client, rules) -> None:
    db = rules
    store = _store(db, "grocery", "Sharma Kirana")
    context = resolve_store_context(db, store.id)
    db.add(Campaign(store_id=store.id, occasion="Quiet", status="draft"))
    db.commit()

    attribution.run(db, context)
    db.commit()

    row = client.get(f"/marketing/campaigns/performance?store_id={store.id}").json()["campaigns"][0]
    assert row["customers_reached"] == 0
    assert row["revenue_attributed"] == 0.0
    assert row["conversion_rate"] == 0.0


def test_coupon_redemptions_are_counted_against_their_campaign(client, rules) -> None:
    db = rules
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "1000.00")
    context = resolve_store_context(db, store.id)

    campaign = Campaign(store_id=store.id, occasion="Diwali", status="published")
    db.add(campaign)
    db.commit()

    client.post(
        f"/loyalty/coupons?store_id={store.id}",
        json={"campaign_id": campaign.id, "discount_type": "percent", "discount_value": 15},
    )
    _sell(client, store, product, coupon_code="DIWALI15")

    attribution.run(db, context)
    db.commit()

    row = client.get(f"/marketing/campaigns/performance?store_id={store.id}").json()["campaigns"][0]
    assert row["coupons_redeemed"] == 1
