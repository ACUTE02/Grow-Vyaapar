"""Correcting a count on purpose, and writing down why.

Every other stock movement is a side effect of something - a bill, a refund, a
received order - and traces back to that event. An adjustment has no event
behind it, so the audit row is the event, and these tests are mostly about
whether that row tells the truth.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.models.admin import AuditLog
from app.models.core import Product, StockLevel
from tests.test_segmentation import _store


def _product(db, store, sku: str = "ADJ-1", *, qty: str = "100") -> Product:
    product = Product(
        store_id=store.id,
        sku=sku,
        name=f"Item {sku}",
        cost_price=Decimal("10.00"),
        sell_price=Decimal("25.00"),
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


def _stock(db, product_id: int) -> Decimal:
    db.expire_all()
    return db.scalar(select(StockLevel.qty_on_hand).where(StockLevel.product_id == product_id))


def _adjust(client, store_id: int, product_id: int, **body):
    return client.post(
        f"/products/{product_id}/adjustments", params={"store_id": store_id}, json=body
    )


def _audit_rows(db, store_id: int) -> list[AuditLog]:
    return list(
        db.scalars(
            select(AuditLog).where(
                AuditLog.store_id == store_id, AuditLog.action == "stock.adjust"
            )
        ).all()
    )


# -- the two directions ------------------------------------------------------
def test_stock_can_be_added(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, qty="100")
    db.commit()

    response = _adjust(client, store.id, product.id, quantity_delta="12", reason="found")

    assert response.status_code == 201, response.text
    body = response.json()
    assert Decimal(str(body["qty_before"])) == Decimal("100")
    assert Decimal(str(body["quantity_delta"])) == Decimal("12")
    assert Decimal(str(body["qty_after"])) == Decimal("112")
    assert _stock(db, product.id) == Decimal("112")


def test_stock_can_be_removed(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, qty="100")
    db.commit()

    response = _adjust(client, store.id, product.id, quantity_delta="-6", reason="damaged")

    assert response.status_code == 201, response.text
    assert Decimal(str(response.json()["qty_after"])) == Decimal("94")
    assert _stock(db, product.id) == Decimal("94")


def test_a_fractional_adjustment_works_for_a_shop_that_sells_by_weight(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, qty="10.5")
    db.commit()

    response = _adjust(client, store.id, product.id, quantity_delta="-0.25", reason="damaged")

    assert response.status_code == 201, response.text
    assert _stock(db, product.id) == Decimal("10.250")


# -- refusals ----------------------------------------------------------------
def test_an_adjustment_of_zero_is_refused(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, qty="100")
    db.commit()

    response = _adjust(client, store.id, product.id, quantity_delta="0", reason="found")

    assert response.status_code == 422
    assert "changes nothing" in response.text
    assert _stock(db, product.id) == Decimal("100")
    assert _audit_rows(db, store.id) == []


def test_an_adjustment_below_zero_is_refused(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, qty="3")
    db.commit()

    response = _adjust(client, store.id, product.id, quantity_delta="-4", reason="lost")

    assert response.status_code == 422
    assert "below zero" in response.text
    assert _stock(db, product.id) == Decimal("3"), "a refused adjustment moved stock"
    assert _audit_rows(db, store.id) == [], "a refused adjustment left an audit row"


def test_taking_the_shelf_to_exactly_zero_is_allowed(client, db) -> None:
    """Zero is a real count. It is below zero that is impossible."""
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, qty="3")
    db.commit()

    response = _adjust(client, store.id, product.id, quantity_delta="-3", reason="expired")

    assert response.status_code == 201, response.text
    assert _stock(db, product.id) == Decimal("0")


def test_a_reason_outside_the_list_is_refused(client, db) -> None:
    """The UI does not get to invent reasons; the API decides what they can be."""
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, qty="100")
    db.commit()

    response = _adjust(
        client, store.id, product.id, quantity_delta="1", reason="the dog ate it"
    )

    assert response.status_code == 422
    assert _stock(db, product.id) == Decimal("100")


def test_a_missing_reason_is_refused(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, qty="100")
    db.commit()

    assert _adjust(client, store.id, product.id, quantity_delta="1").status_code == 422


def test_a_missing_quantity_is_refused(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, qty="100")
    db.commit()

    assert _adjust(client, store.id, product.id, reason="found").status_code == 422


def test_a_product_that_does_not_exist_is_404(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    db.commit()

    response = _adjust(client, store.id, 987654, quantity_delta="1", reason="found")
    assert response.status_code == 404


# -- what the audit row says -------------------------------------------------
def test_the_audit_row_carries_before_delta_after_reason_and_note(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, qty="80")
    db.commit()

    _adjust(
        client,
        store.id,
        product.id,
        quantity_delta="-6",
        reason="damaged",
        note="Crushed by the delivery crate on Tuesday",
    )

    rows = _audit_rows(db, store.id)
    assert len(rows) == 1
    entry = rows[0]
    assert entry.entity == "product"
    assert entry.entity_id == str(product.id)
    assert entry.store_id == store.id
    assert entry.user_id is not None, "an adjustment with no actor is not an audit trail"
    assert entry.before["qty_on_hand"] == "80.000"
    assert entry.after["qty_on_hand"] == "74.000"
    assert entry.after["quantity_delta"] == "-6"
    assert entry.after["reason"] == "damaged"
    assert entry.after["note"] == "Crushed by the delivery crate on Tuesday"


def test_a_note_is_optional(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, qty="80")
    db.commit()

    response = _adjust(client, store.id, product.id, quantity_delta="2", reason="stock_count")

    assert response.status_code == 201
    assert response.json()["note"] is None
    assert _audit_rows(db, store.id)[0].after["note"] is None


def test_the_history_reads_back_newest_first(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, qty="100")
    db.commit()

    _adjust(client, store.id, product.id, quantity_delta="-5", reason="damaged")
    _adjust(client, store.id, product.id, quantity_delta="+3", reason="found")

    history = client.get(
        f"/products/{product.id}/adjustments", params={"store_id": store.id}
    )
    assert history.status_code == 200
    rows = history.json()
    assert len(rows) == 2
    assert [row["reason"] for row in rows] == ["found", "damaged"]
    assert Decimal(str(rows[0]["qty_after"])) == Decimal("98")


# -- security ----------------------------------------------------------------
def test_another_stores_product_cannot_be_adjusted(db, role_client) -> None:
    store_a = _store(db, "grocery", "Store A")
    store_b = _store(db, "grocery", "Store B")
    victim = _product(db, store_b, "VICTIM-1", qty="50")
    db.commit()

    client = role_client("manager", store_id=store_a.id)
    response = _adjust(client, store_a.id, victim.id, quantity_delta="-50", reason="lost")

    assert response.status_code == 404, response.text
    assert _stock(db, victim.id) == Decimal("50"), "another store's shelf moved"
    assert _audit_rows(db, store_b.id) == []


def test_an_anonymous_request_cannot_adjust_stock(db, anon_client) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, qty="50")
    db.commit()

    response = _adjust(anon_client, store.id, product.id, quantity_delta="-50", reason="lost")

    assert response.status_code == 401
    assert _stock(db, product.id) == Decimal("50")


def test_a_cashier_cannot_adjust_stock(db, role_client) -> None:
    """Writing off stock is a manager action, enforced by the API rather than
    by hiding a button."""
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, qty="50")
    db.commit()

    client = role_client("cashier", store_id=store.id)
    response = _adjust(client, store.id, product.id, quantity_delta="-50", reason="lost")

    assert response.status_code == 403, response.text
    assert _stock(db, product.id) == Decimal("50")


def test_ownership_fields_cannot_be_set_from_the_body(client, db) -> None:
    """store_id, product_id and the audit fields are not adjustment inputs. A
    payload naming one is refused rather than quietly ignored."""
    store = _store(db, "grocery", "Sharma Kirana")
    other = _store(db, "grocery", "Store B")
    product = _product(db, store, qty="100")
    db.commit()

    for extra in (
        {"store_id": other.id},
        {"product_id": 999},
        {"adjusted_by": 1},
        {"adjusted_at": "2020-01-01T00:00:00"},
        {"qty_after": "1000"},
    ):
        # Posted directly rather than through the helper, so the extra key
        # lands in the body and not in the helper's own arguments.
        response = client.post(
            f"/products/{product.id}/adjustments",
            params={"store_id": store.id},
            json={"quantity_delta": "1", "reason": "found", **extra},
        )
        assert response.status_code == 422, f"{extra} was not refused"

    assert _stock(db, product.id) == Decimal("100")


def test_another_stores_adjustment_history_is_not_readable(db, role_client) -> None:
    store_a = _store(db, "grocery", "Store A")
    store_b = _store(db, "grocery", "Store B")
    victim = _product(db, store_b, "VICTIM-2", qty="50")
    db.commit()

    client = role_client("manager", store_id=store_a.id)
    response = client.get(
        f"/products/{victim.id}/adjustments", params={"store_id": store_a.id}
    )
    assert response.status_code == 404


# -- atomicity ---------------------------------------------------------------
def test_a_failure_writes_neither_the_stock_nor_the_audit_row(client, db, monkeypatch) -> None:
    """The count and the reason for it are one fact. Half of it is worse than
    neither: a shelf that moved with nothing saying why."""
    from app.services import product_service

    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, qty="100")
    db.commit()

    def explode(*args, **kwargs):
        raise RuntimeError("the audit write failed")

    monkeypatch.setattr(product_service.audit, "record", explode)

    try:
        _adjust(client, store.id, product.id, quantity_delta="-10", reason="damaged")
    except RuntimeError:
        pass

    assert _stock(db, product.id) == Decimal("100"), "stock moved without an audit row"
    assert _audit_rows(db, store.id) == []
