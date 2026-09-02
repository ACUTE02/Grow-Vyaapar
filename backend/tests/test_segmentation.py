"""Segmentation and the reminder engine, driven only by thresholds and rules."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.agents import reminders as reminder_agent
from app.agents import segmentation
from app.models.agent import Reminder, Segment
from app.models.base import utcnow
from app.models.config import Store, Vertical
from app.models.core import (
    Customer,
    Product,
    ProductCategory,
    StockLevel,
    Transaction,
    TransactionItem,
)
from app.verticals.context import resolve_store_context


# -- the classifier ----------------------------------------------------------
def _classify(**overrides) -> str:
    kwargs = {
        "recency_days": 10,
        "visits": 6,
        "total_spend": Decimal("1000"),
        "average_spend": Decimal("1000"),
        "inactive_days": 90,
        "vip_multiplier": 2.0,
        "new_customer_max_visits": 1,
    }
    kwargs.update(overrides)
    return segmentation.classify(**kwargs)


def test_classifier_covers_all_four_segments() -> None:
    assert _classify(recency_days=200) == "Inactive"
    assert _classify(recency_days=None) == "Inactive"
    assert _classify(total_spend=Decimal("2500")) == "VIP"
    assert _classify(visits=1) == "New"
    assert _classify() == "Regular"


def test_the_same_recency_lands_differently_under_different_thresholds() -> None:
    assert _classify(recency_days=100, inactive_days=90) == "Inactive"
    assert _classify(recency_days=100, inactive_days=180) == "Regular"


# -- fixtures for the engine -------------------------------------------------
def _store(db, code: str, name: str) -> Store:
    vertical = db.scalar(select(Vertical).where(Vertical.code == code))
    store = Store(
        vertical_id=vertical.id,
        name=name,
        city="Indore",
        language="en",
        google_review_url="https://g.page/demo/review",
    )
    db.add(store)
    db.commit()
    return store


def _catalog(db, store: Store) -> Product:
    category = ProductCategory(store_id=store.id, name="Regulars")
    db.add(category)
    db.flush()
    product = Product(
        store_id=store.id,
        sku=f"SKU-{store.id}",
        name="Usual item",
        category_id=category.id,
        cost_price=Decimal("40.00"),
        sell_price=Decimal("100.00"),
        gst_rate=Decimal("5"),
        attributes={},
    )
    db.add(product)
    db.flush()
    db.add(
        StockLevel(product_id=product.id, qty_on_hand=Decimal("500"), reorder_point=Decimal("5"))
    )
    db.commit()
    return product


_PHONE_COUNTER = iter(range(1, 10_000_000))


def _history(db, store: Store, product: Product, *, count: int, days_ago: int, spend: str):
    """count customers whose only purchase was days_ago."""
    made = []
    for index in range(count):
        serial = next(_PHONE_COUNTER)
        customer = Customer(
            store_id=store.id,
            name=f"Customer {store.id}-{index}",
            phone=f"9{serial:09d}",
            created_at=utcnow() - timedelta(days=days_ago + 30),
        )
        db.add(customer)
        db.flush()
        transaction = Transaction(
            store_id=store.id,
            customer_id=customer.id,
            invoice_no=f"INV-{store.id:02d}-{customer.id:05d}",
            subtotal=Decimal(spend),
            discount=Decimal("0.00"),
            gst_amount=Decimal("0.00"),
            total=Decimal(spend),
            payment_mode="cash",
            status="completed",
            created_at=utcnow() - timedelta(days=days_ago),
        )
        db.add(transaction)
        db.flush()
        db.add(
            TransactionItem(
                transaction_id=transaction.id,
                product_id=product.id,
                qty=Decimal("1"),
                unit_price=Decimal(spend),
                line_discount=Decimal("0.00"),
                line_total=Decimal(spend),
            )
        )
        made.append(customer)
    db.commit()
    return made


# -- segmentation over real rows --------------------------------------------
def test_rebuild_writes_every_segment_and_only_to_its_own_table(db) -> None:
    store = _store(db, "pharmacy", "Jeevan Medical")
    product = _catalog(db, store)
    _history(db, store, product, count=5, days_ago=10, spend="500")     # Regular-ish
    _history(db, store, product, count=3, days_ago=200, spend="500")    # Inactive
    _history(db, store, product, count=2, days_ago=5, spend="9000")     # VIP

    context = resolve_store_context(db, store.id)
    distribution = segmentation.rebuild(db, context)
    db.commit()

    assert distribution["Inactive"] == 3
    assert distribution["VIP"] == 2
    assert sum(distribution.values()) == 10
    assert db.scalar(select(Transaction).limit(1)) is not None
    assert len(db.scalars(select(Segment)).all()) == 10


def test_two_verticals_get_different_distributions_from_identical_history(db) -> None:
    """Same 100-day gap, different inactive_days, different answer. No code branch."""
    slow = _store(db, "apparel", "Rangoli Fashion")      # inactive_days 180
    fast = _store(db, "grocery", "Sharma Kirana")        # inactive_days 60

    for store in (slow, fast):
        product = _catalog(db, store)
        _history(db, store, product, count=6, days_ago=100, spend="800")

    slow_distribution = segmentation.rebuild(db, resolve_store_context(db, slow.id))
    fast_distribution = segmentation.rebuild(db, resolve_store_context(db, fast.id))
    db.commit()

    assert slow_distribution["Inactive"] == 0
    assert fast_distribution["Inactive"] == 6


# -- the reminder engine -----------------------------------------------------
def test_reminder_kinds_differ_by_vertical(rules) -> None:
    db = rules
    pharmacy = _store(db, "pharmacy", "Jeevan Medical")      # reorder_cycle 30
    apparel = _store(db, "apparel", "Rangoli Fashion")       # revisit_cycle 150

    for store, days in ((pharmacy, 70), (apparel, 260)):
        product = _catalog(db, store)
        _history(db, store, product, count=4, days_ago=days, spend="700")

    for store in (pharmacy, apparel):
        context = resolve_store_context(db, store.id)
        segmentation.rebuild(db, context)
        reminder_agent.run(db, context, llm_budget=0)
    db.commit()

    def kinds(store_id: int) -> set[str]:
        return {
            reminder.kind
            for reminder in db.scalars(
                select(Reminder).where(Reminder.store_id == store_id)
            ).all()
        }

    pharmacy_kinds = kinds(pharmacy.id)
    apparel_kinds = kinds(apparel.id)

    assert "reorder_due" in pharmacy_kinds
    assert "reorder_due" not in apparel_kinds
    assert "revisit_due" in apparel_kinds
    assert "revisit_due" not in pharmacy_kinds


def test_messages_fall_back_to_templates_with_no_llm(rules) -> None:
    db = rules
    store = _store(db, "grocery", "Sharma Kirana")
    product = _catalog(db, store)
    _history(db, store, product, count=2, days_ago=120, spend="600")

    context = resolve_store_context(db, store.id)
    segmentation.rebuild(db, context)
    created = reminder_agent.run(db, context, llm_budget=0)
    db.commit()

    assert created, "the engine should have found lapsed customers"
    reminders = db.scalars(select(Reminder).where(Reminder.store_id == store.id)).all()
    assert reminders
    for reminder in reminders:
        assert reminder.status == "queued"
        assert "{" not in reminder.message, "every placeholder must be filled"
        assert store.name in reminder.message or "Sharma" in reminder.message


def test_a_second_run_does_not_duplicate_open_reminders(rules) -> None:
    db = rules
    store = _store(db, "grocery", "Sharma Kirana")
    product = _catalog(db, store)
    _history(db, store, product, count=3, days_ago=120, spend="600")

    context = resolve_store_context(db, store.id)
    segmentation.rebuild(db, context)
    first = reminder_agent.run(db, context, llm_budget=0)
    db.commit()
    second = reminder_agent.run(db, context, llm_budget=0)
    db.commit()

    assert sum(first.values()) > 0
    assert sum(second.values()) == 0


def test_completing_a_sale_creates_a_review_request_with_no_manual_action(
    client, rules
) -> None:
    db = rules
    store = _store(db, "grocery", "Sharma Kirana")
    product = _catalog(db, store)
    customer = _history(db, store, product, count=1, days_ago=3, spend="200")[0]

    before = len(db.scalars(select(Reminder).where(Reminder.store_id == store.id)).all())
    response = client.post(
        f"/billing/transactions?store_id={store.id}",
        json={"customer_id": customer.id, "lines": [{"product_id": product.id, "qty": 1}]},
    )
    assert response.status_code == 201, response.text

    db.expire_all()
    reminders = db.scalars(
        select(Reminder).where(
            Reminder.store_id == store.id, Reminder.kind == "review_request"
        )
    ).all()
    assert len(reminders) == before + 1
    reminder = reminders[0]
    assert reminder.status == "queued"
    assert reminder.scheduled_for > reminder.created_at   # the +2 hour delay
    assert "g.page" in reminder.message
