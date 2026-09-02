"""Batches and expiry: FEFO picking, alert windows, and the flag that gates both."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models.core import Batch, Product, StockLevel, TransactionItem
from app.services import batch_service
from app.verticals.context import resolve_store_context
from tests.test_segmentation import _store


def _product(db, store, sku: str = "MED-1", qty: str = "50") -> Product:
    product = Product(
        store_id=store.id,
        sku=sku,
        name=f"Item {sku}",
        cost_price=Decimal("40.00"),
        sell_price=Decimal("100.00"),
        gst_rate=Decimal("12"),
        attributes={},
    )
    db.add(product)
    db.flush()
    db.add(
        StockLevel(product_id=product.id, qty_on_hand=Decimal(qty), reorder_point=Decimal("5"))
    )
    db.flush()
    return product


def _batch(db, product, batch_no: str, qty: str, days_to_expiry: int | None) -> Batch:
    batch = Batch(
        product_id=product.id,
        batch_no=batch_no,
        qty=Decimal(qty),
        expiry_date=(
            date.today() + timedelta(days=days_to_expiry) if days_to_expiry is not None else None
        ),
    )
    db.add(batch)
    db.flush()
    return batch


# -- FEFO --------------------------------------------------------------------
def test_fefo_takes_the_earliest_expiry_first_and_spills_into_the_next(client, db) -> None:
    """The acceptance case: 3 sold, batch A has 2 (sooner), batch B has 5."""
    store = _store(db, "pharmacy", "Jeevan Medical")
    product = _product(db, store)
    batch_a = _batch(db, product, "A", "2", days_to_expiry=20)
    batch_b = _batch(db, product, "B", "5", days_to_expiry=200)
    db.commit()

    response = client.post(
        f"/billing/transactions?store_id={store.id}",
        json={"lines": [{"product_id": product.id, "qty": 3}]},
    )
    assert response.status_code == 201, response.text

    db.expire_all()
    assert Decimal(str(db.get(Batch, batch_a.id).qty)) == Decimal("0.000")
    assert Decimal(str(db.get(Batch, batch_b.id).qty)) == Decimal("4.000")

    item = db.scalar(select(TransactionItem))
    allocation = {line["batch_no"]: line["qty"] for line in item.batch_allocation}
    assert allocation == {"A": 2.0, "B": 1.0}


def test_undated_batches_are_used_last(db) -> None:
    store = _store(db, "pharmacy", "Jeevan Medical")
    product = _product(db, store)
    _batch(db, product, "NO-DATE", "10", days_to_expiry=None)
    _batch(db, product, "DATED", "2", days_to_expiry=90)
    db.commit()

    allocation = batch_service.allocate_fefo(db, product.id, Decimal("3"))
    assert [line["batch_no"] for line in allocation] == ["DATED", "NO-DATE"]
    assert allocation[0]["qty"] == 2.0 and allocation[1]["qty"] == 1.0


def test_a_sale_beyond_the_batches_on_record_still_goes_through(db) -> None:
    """Batches are advisory; stock_levels decides whether a sale is possible."""
    store = _store(db, "pharmacy", "Jeevan Medical")
    product = _product(db, store)
    _batch(db, product, "ONLY", "1", days_to_expiry=30)
    db.commit()

    allocation = batch_service.allocate_fefo(db, product.id, Decimal("4"))
    assert allocation[-1]["batch_id"] is None
    assert allocation[-1]["qty"] == 3.0


def test_a_refund_puts_the_stock_back_in_its_batches(client, db) -> None:
    store = _store(db, "pharmacy", "Jeevan Medical")
    product = _product(db, store)
    batch_a = _batch(db, product, "A", "2", days_to_expiry=20)
    batch_b = _batch(db, product, "B", "5", days_to_expiry=200)
    db.commit()

    sale = client.post(
        f"/billing/transactions?store_id={store.id}",
        json={"lines": [{"product_id": product.id, "qty": 3}]},
    ).json()
    refunded = client.post(f"/billing/transactions/{sale['id']}/refund?store_id={store.id}")
    assert refunded.status_code == 200

    db.expire_all()
    assert Decimal(str(db.get(Batch, batch_a.id).qty)) == Decimal("2.000")
    assert Decimal(str(db.get(Batch, batch_b.id).qty)) == Decimal("5.000")


def test_a_vertical_without_the_expiry_flag_records_no_allocation(client, db) -> None:
    store = _store(db, "apparel", "Rangoli Fashion")     # expiry flag off
    product = _product(db, store, sku="SHT-1")
    _batch(db, product, "IGNORED", "5", days_to_expiry=10)
    db.commit()

    client.post(
        f"/billing/transactions?store_id={store.id}",
        json={"lines": [{"product_id": product.id, "qty": 2}]},
    )
    db.expire_all()
    item = db.scalar(select(TransactionItem))
    assert item.batch_allocation is None
    assert Decimal(str(db.scalar(select(Batch)).qty)) == Decimal("5.000")


# -- the alert window --------------------------------------------------------
def test_the_alert_window_comes_from_the_vertical(db) -> None:
    chemist = resolve_store_context(db, _store(db, "pharmacy", "Jeevan Medical").id)
    baker = resolve_store_context(db, _store(db, "bakery", "Sharma Bakery").id)
    hardware = resolve_store_context(db, _store(db, "hardware", "Verma Hardware").id)

    assert chemist.cfg("near_expiry_days") == 30
    assert baker.cfg("near_expiry_days") == 3
    assert hardware.cfg("near_expiry_days") is None
    assert hardware.feature("expiry") is False


def test_near_expiry_lists_only_what_is_inside_the_window(client, db) -> None:
    store = _store(db, "pharmacy", "Jeevan Medical")     # 30-day window
    product = _product(db, store)
    _batch(db, product, "SOON", "5", days_to_expiry=10)
    _batch(db, product, "LATER", "5", days_to_expiry=200)
    db.commit()

    body = client.get(f"/products/expiring?store_id={store.id}").json()
    assert body["tracks_expiry"] is True
    assert body["near_expiry_days"] == 30
    assert [row["batch_no"] for row in body["batches"]] == ["SOON"]
    assert body["alert_count"] == 1


def test_a_store_without_the_flag_reports_nothing(client, db) -> None:
    store = _store(db, "hardware", "Verma Hardware")
    body = client.get(f"/products/expiring?store_id={store.id}").json()
    assert body["tracks_expiry"] is False
    assert body["batches"] == []


def test_expired_batches_are_marked(client, db) -> None:
    store = _store(db, "pharmacy", "Jeevan Medical")
    product = _product(db, store)
    _batch(db, product, "GONE", "3", days_to_expiry=-5)
    db.commit()

    body = client.get(f"/products/expiring?store_id={store.id}").json()
    assert body["expired_count"] == 1
    assert body["batches"][0]["days_left"] < 0


def test_campaigns_reach_for_near_expiry_stock_first(db) -> None:
    from app.agents import campaigns

    store = _store(db, "pharmacy", "Jeevan Medical")
    product = _product(db, store, sku="SOON-1")
    _batch(db, product, "SOON", "20", days_to_expiry=7)
    db.commit()

    context = resolve_store_context(db, store.id)
    campaign, _ = campaigns.create(db, context, "Monsoon stock clearance")
    db.commit()
    assert "Item SOON-1" in (campaign.caption or "") or "SOON-1" in (campaign.prompt or "")
