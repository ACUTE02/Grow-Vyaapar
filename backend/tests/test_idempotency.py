"""One logical checkout, one bill, however many times it is submitted.

A shop's till runs on a connection that drops. The client retries, and before
this the retry was a second bill with a second stock movement and a second
reminder queued. The guard is a unique constraint on
(store_id, idempotency_key), not a disabled button: a button stops a second
click and does nothing about a resent request.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select

from app.models.agent import Reminder
from app.models.core import Customer, Product, StockLevel, Transaction, TransactionItem
from tests.test_segmentation import _store


def _key() -> str:
    return uuid.uuid4().hex


def _product(db, store, sku: str, *, qty: str = "50", price: str = "40.00") -> Product:
    product = Product(
        store_id=store.id,
        sku=sku,
        name=f"Item {sku}",
        cost_price=Decimal("20.00"),
        sell_price=Decimal(price),
        gst_rate=Decimal("5"),
        attributes={},
    )
    db.add(product)
    db.flush()
    db.add(
        StockLevel(product_id=product.id, qty_on_hand=Decimal(qty), reorder_point=Decimal("5"))
    )
    db.flush()
    return product


def _sell(client, store_id: int, product_id: int, key: str, qty: str = "1", **extra):
    return client.post(
        "/billing/transactions",
        params={"store_id": store_id},
        json={"lines": [{"product_id": product_id, "qty": qty}], **extra},
        headers={"Idempotency-Key": key},
    )


def _stock(db, product_id: int) -> Decimal:
    db.expire_all()
    return db.scalar(select(StockLevel.qty_on_hand).where(StockLevel.product_id == product_id))


def _count(db, model, **filters) -> int:
    statement = select(func.count()).select_from(model)
    for column, value in filters.items():
        statement = statement.where(getattr(model, column) == value)
    return db.scalar(statement)


# -- the contract ------------------------------------------------------------
def test_the_key_is_required(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "REQ-1")
    db.commit()

    response = client.post(
        "/billing/transactions",
        params={"store_id": store.id},
        json={"lines": [{"product_id": product.id, "qty": "1"}]},
    )

    assert response.status_code == 422
    assert _count(db, Transaction, store_id=store.id) == 0


def test_a_first_request_creates_the_bill(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "FIRST-1")
    db.commit()

    response = _sell(client, store.id, product.id, _key(), qty="3")

    assert response.status_code == 201
    assert response.headers.get("Idempotency-Replayed") is None
    assert _stock(db, product.id) == Decimal("47")


def test_a_retry_returns_the_same_bill_and_moves_nothing(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "RETRY-1")
    db.commit()
    key = _key()

    first = _sell(client, store.id, product.id, key, qty="2")
    replay = _sell(client, store.id, product.id, key, qty="2")

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == first.json()

    assert _stock(db, product.id) == Decimal("48"), "stock moved twice"
    assert _count(db, Transaction, store_id=store.id) == 1
    assert _count(db, TransactionItem, transaction_id=first.json()["id"]) == 1


def test_five_retries_are_still_one_bill(client, db) -> None:
    """A client with an aggressive retry policy must not cost the shop five
    bills' worth of stock."""
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "MANY-1")
    db.commit()
    key = _key()

    codes = [_sell(client, store.id, product.id, key).status_code for _ in range(5)]

    assert codes == [201, 200, 200, 200, 200]
    assert _stock(db, product.id) == Decimal("49")
    assert _count(db, Transaction, store_id=store.id) == 1


def test_a_different_key_is_a_different_sale(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "DIFF-1")
    db.commit()

    first = _sell(client, store.id, product.id, _key())
    second = _sell(client, store.id, product.id, _key())

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["invoice_no"] != second.json()["invoice_no"]
    assert _stock(db, product.id) == Decimal("48")


def test_a_retry_does_not_queue_a_second_reminder(client, db, rules) -> None:
    """A completed sale is a signal the reminder agent listens for. A replay is
    not a completed sale, and must not reach it."""
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "REM-1")
    customer = Customer(
        store_id=store.id, name="Ronit Verma", phone="9800000041", marketing_opt_in=True
    )
    db.add(customer)
    db.commit()
    key = _key()

    _sell(client, store.id, product.id, key, customer_id=customer.id)
    after_first = _count(db, Reminder, store_id=store.id)
    _sell(client, store.id, product.id, key, customer_id=customer.id)

    assert _count(db, Reminder, store_id=store.id) == after_first


# -- multi-tenancy -----------------------------------------------------------
def test_two_stores_may_use_the_same_key_independently(client, db) -> None:
    store_a = _store(db, "grocery", "Store A")
    store_b = _store(db, "grocery", "Store B")
    product_a = _product(db, store_a, "SHARED-1")
    product_b = _product(db, store_b, "SHARED-1")
    db.commit()
    key = "the-same-key-in-both-shops"

    first = _sell(client, store_a.id, product_a.id, key, qty="2")
    second = _sell(client, store_b.id, product_b.id, key, qty="4")

    assert first.status_code == 201
    assert second.status_code == 201, "one shop's key blocked another shop's sale"
    assert first.json()["id"] != second.json()["id"]
    assert _stock(db, product_a.id) == Decimal("48")
    assert _stock(db, product_b.id) == Decimal("46")


def test_a_key_cannot_be_used_to_read_another_stores_bill(db, role_client) -> None:
    """The replay lookup is scoped by the authorised store context, never by
    anything the caller sent, so a guessed key finds nothing across the fence."""
    store_a = _store(db, "grocery", "Store A")
    store_b = _store(db, "grocery", "Store B")
    product_a = _product(db, store_a, "SECRET-1")
    product_b = _product(db, store_b, "OWN-1")
    db.commit()
    key = "a-key-store-a-used"

    owner = role_client("manager", store_id=store_a.id)
    victim_sale = _sell(owner, store_a.id, product_a.id, key, qty="5")
    assert victim_sale.status_code == 201

    # Store B's manager guesses the key and submits their own cart with it.
    attacker = role_client("manager", store_id=store_b.id)
    response = _sell(attacker, store_b.id, product_b.id, key, qty="1")

    assert response.status_code == 201, "the key leaked across stores"
    assert response.json()["id"] != victim_sale.json()["id"]
    assert response.json()["store_id"] == store_b.id
    # And nothing of store A's is visible in the answer.
    assert response.json()["total"] != victim_sale.json()["total"]


# -- failures must not burn the key ------------------------------------------
def test_an_oversell_leaves_the_key_free_to_use_again(client, db) -> None:
    """The first attempt fails on stock, writes nothing, and rolls back - so the
    key was never recorded, and the corrected cart may reuse it."""
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "SHORT-1", qty="3")
    db.commit()
    key = _key()

    refused = _sell(client, store.id, product.id, key, qty="99")
    assert refused.status_code == 409
    assert _count(db, Transaction, store_id=store.id) == 0

    accepted = _sell(client, store.id, product.id, key, qty="2")
    assert accepted.status_code == 201, "a failed attempt consumed the key"
    assert _stock(db, product.id) == Decimal("1")


def test_a_foreign_product_leaves_the_key_free_too(client, db) -> None:
    store_a = _store(db, "grocery", "Store A")
    store_b = _store(db, "grocery", "Store B")
    foreign = _product(db, store_b, "FOREIGN-1")
    own = _product(db, store_a, "OWN-2")
    db.commit()
    key = _key()

    refused = _sell(client, store_a.id, foreign.id, key)
    assert refused.status_code == 404

    accepted = _sell(client, store_a.id, own.id, key)
    assert accepted.status_code == 201


# -- the database is the final authority -------------------------------------
def test_the_constraint_refuses_a_duplicate_even_below_the_endpoint(db) -> None:
    """Two requests can both pass the lookup before either inserts. This is
    what stops the loser: the row itself is rejected, so the guarantee does not
    depend on the route remembering to check."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    store = _store(db, "grocery", "Sharma Kirana")
    db.commit()

    db.add(
        Transaction(
            store_id=store.id, invoice_no="INV-A", total=Decimal("10"), idempotency_key="dup"
        )
    )
    db.flush()
    db.add(
        Transaction(
            store_id=store.id, invoice_no="INV-B", total=Decimal("10"), idempotency_key="dup"
        )
    )

    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_a_race_that_reaches_the_insert_returns_the_winners_bill(client, db, monkeypatch) -> None:
    """Simulates the lost race directly: the replay lookup finds nothing, then
    the INSERT fails because another request got there first. The endpoint must
    return that request's bill rather than a 500."""
    from app.routers import billing

    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "RACE-1")
    db.commit()
    key = _key()

    winner = _sell(client, store.id, product.id, key, qty="2")
    assert winner.status_code == 201

    # Blind the endpoint's first lookup exactly once, so the next request walks
    # into the INSERT the way a concurrent one would.
    calls = {"n": 0}
    real = billing._replay

    def blind_once(db_session, store_id, replay_key):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return real(db_session, store_id, replay_key)

    monkeypatch.setattr(billing, "_replay", blind_once)

    loser = _sell(client, store.id, product.id, key, qty="2")

    assert loser.status_code == 200, loser.text
    assert loser.headers["Idempotency-Replayed"] == "true"
    assert loser.json()["id"] == winner.json()["id"]
    assert _stock(db, product.id) == Decimal("48"), "the losing request moved stock"
    assert _count(db, Transaction, store_id=store.id) == 1


def test_an_unrelated_integrity_error_is_not_dressed_up_as_a_replay(
    client, db, monkeypatch
) -> None:
    """Only a duplicate key becomes a replay. Any other constraint failure has
    to surface, or a real bug hides behind a 200."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    from app.routers import billing

    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "BOOM-1")
    db.commit()

    def explode(*args, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("some other constraint"))

    monkeypatch.setattr(billing.billing_service, "create_sale", explode)

    with pytest.raises(IntegrityError):
        _sell(client, store.id, product.id, _key())

    assert _count(db, Transaction, store_id=store.id) == 0
