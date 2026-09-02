"""Stock intelligence: velocity, stockout, and predicting death before it happens."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.agents import forecasting
from app.models.base import utcnow
from app.models.core import Customer, Product, StockLevel, Transaction, TransactionItem
from app.models.ml import StockForecast
from app.verticals.context import resolve_store_context
from tests.test_segmentation import _store

PHONES = iter(range(1_000_000, 4_000_000))


def _product(db, store, sku: str, qty: float, attributes: dict | None = None) -> Product:
    product = Product(
        store_id=store.id,
        sku=sku,
        name=f"Item {sku}",
        cost_price=Decimal("40.00"),
        sell_price=Decimal("100.00"),
        gst_rate=Decimal("5"),
        attributes=attributes or {},
    )
    db.add(product)
    db.flush()
    db.add(
        StockLevel(
            product_id=product.id,
            qty_on_hand=Decimal(str(qty)),
            reorder_point=Decimal("5"),
        )
    )
    db.flush()
    return product


def _sell(db, store, product, *, days_ago: int, qty: float = 1.0) -> None:
    customer = db.scalar(select(Customer).where(Customer.store_id == store.id))
    if customer is None:
        customer = Customer(
            store_id=store.id, name="Buyer", phone=f"9{next(PHONES):09d}"
        )
        db.add(customer)
        db.flush()
    stamp = utcnow() - timedelta(days=days_ago)
    transaction = Transaction(
        store_id=store.id,
        customer_id=customer.id,
        invoice_no=f"INV-{store.id:02d}-{product.id:04d}-{days_ago:04d}",
        subtotal=Decimal("100.00"),
        discount=Decimal("0.00"),
        gst_amount=Decimal("0.00"),
        total=Decimal("100.00"),
        payment_mode="cash",
        status="completed",
        created_at=stamp,
    )
    db.add(transaction)
    db.flush()
    db.add(
        TransactionItem(
            transaction_id=transaction.id,
            product_id=product.id,
            qty=Decimal(str(qty)),
            unit_price=Decimal("100.00"),
            line_discount=Decimal("0.00"),
            line_total=Decimal("100.00"),
        )
    )
    stock = db.scalar(select(StockLevel).where(StockLevel.product_id == product.id))
    if stock.last_sold_at is None or stock.last_sold_at < stamp:
        stock.last_sold_at = stamp


# -- the window scales with the vertical -------------------------------------
def test_the_lookback_window_comes_from_the_vertical(db) -> None:
    fast = resolve_store_context(db, _store(db, "bakery", "Sharma Bakery").id)
    slow = resolve_store_context(db, _store(db, "hardware", "Verma Hardware").id)
    assert forecasting.window_days(fast) < forecasting.window_days(slow)


def test_days_to_stockout_scales_with_the_trade(db) -> None:
    """A bakery counts days, a hardware shop counts months, from the same code.

    Same stock on the shelf, same query path; only the trade rhythm differs.
    """
    results = {}
    rhythm = {"bakery": (1, 30.0), "hardware": (7, 0.5)}   # (sell every N days, qty)
    for code, name in (("bakery", "Sharma Bakery"), ("hardware", "Verma Hardware")):
        store = _store(db, code, name)
        product = _product(db, store, f"{code[:3].upper()}-1", qty=90)
        context = resolve_store_context(db, store.id)
        every, quantity = rhythm[code]
        for days_ago in range(1, forecasting.window_days(context), every):
            _sell(db, store, product, days_ago=days_ago, qty=quantity)
        db.commit()
        results[code] = next(
            item for item in forecasting.compute(db, context) if item.product_id == product.id
        )

    bakery, hardware = results["bakery"], results["hardware"]
    assert bakery.days_to_stockout is not None and hardware.days_to_stockout is not None
    assert bakery.days_to_stockout < 10, "a bakery's shelf empties in days"
    assert hardware.days_to_stockout > 60, "a hardware shelf lasts months"
    assert bakery.predicted_daily_velocity > hardware.predicted_daily_velocity


# -- the honest handling of no sales -----------------------------------------
def test_a_product_with_no_sales_is_a_risk_not_an_infinity(db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    idle = _product(db, store, "IDLE-1", qty=40)
    db.commit()

    context = resolve_store_context(db, store.id)
    forecast = next(
        item for item in forecasting.compute(db, context) if item.product_id == idle.id
    )

    assert forecast.days_to_stockout is None, "no velocity means no stockout date, not infinity"
    assert forecast.predicted_daily_velocity == 0.0
    assert forecast.is_dead_stock_risk is True
    assert forecast.suggested_reorder_qty == 0.0
    assert "no sales" in forecast.reason


def test_already_dead_stock_is_not_reported_as_a_prediction(db) -> None:
    """Phase 1 already lists what died. This agent only flags what is about to."""
    store = _store(db, "grocery", "Sharma Kirana")       # dead_stock_days 45
    product = _product(db, store, "GONE-1", qty=30)
    stock = db.scalar(select(StockLevel).where(StockLevel.product_id == product.id))
    stock.last_sold_at = utcnow() - timedelta(days=120)
    db.commit()

    context = resolve_store_context(db, store.id)
    forecast = next(
        item for item in forecasting.compute(db, context) if item.product_id == product.id
    )
    assert forecast.is_dead_stock_risk is False


def test_a_fading_seller_is_flagged_before_the_window_closes(db) -> None:
    store = _store(db, "apparel", "Rangoli Fashion")     # dead_stock_days 90
    product = _product(db, store, "FADE-1", qty=50)
    context = resolve_store_context(db, store.id)
    window = forecasting.window_days(context)

    for days_ago in range(window - 5, window // 2, -3):   # busy early
        _sell(db, store, product, days_ago=days_ago, qty=2)
    _sell(db, store, product, days_ago=60)                # then almost nothing
    db.commit()

    forecast = next(
        item for item in forecasting.compute(db, context) if item.product_id == product.id
    )
    assert forecast.is_dead_stock_risk is True
    assert forecast.predicted_daily_velocity > 0
    assert "fading" in forecast.reason or "last sold" in forecast.reason


# -- reorder quantities ------------------------------------------------------
def test_reorder_quantity_covers_the_cycle_with_a_safety_margin(db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")       # reorder cycle 21 days
    product = _product(db, store, "FAST-1", qty=6)
    context = resolve_store_context(db, store.id)
    for days_ago in range(1, forecasting.window_days(context)):
        _sell(db, store, product, days_ago=days_ago, qty=2)
    db.commit()

    forecast = next(
        item for item in forecasting.compute(db, context) if item.product_id == product.id
    )
    cycle = context.cfg_int("reorder_cycle_days")
    expected = forecast.predicted_daily_velocity * cycle * forecasting.SAFETY_FACTOR - 6
    assert forecast.days_to_stockout is not None and forecast.days_to_stockout <= cycle
    assert forecast.suggested_reorder_qty >= expected - 5
    assert forecast.suggested_reorder_qty % 5 == 0, "rounded to a pack a supplier will ship"


def test_pack_size_from_product_attributes_is_respected() -> None:
    assert forecasting._pack_round(11.0, {"pack_size": "6 pc"}) == 12.0
    assert forecasting._pack_round(13.0, {"pack_size": "12"}) == 24.0
    assert forecasting._pack_round(0.0, {}) == 0.0


# -- persistence and the API -------------------------------------------------
def test_run_replaces_the_previous_forecast_rows(db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    _product(db, store, "A-1", qty=10)
    _product(db, store, "A-2", qty=10)
    db.commit()

    context = resolve_store_context(db, store.id)
    first = forecasting.run(db, context)
    db.commit()
    second = forecasting.run(db, context)
    db.commit()

    rows = db.scalars(select(StockForecast).where(StockForecast.store_id == store.id)).all()
    assert first["products"] == second["products"] == 2
    assert len(rows) == 2, "a second run must replace, not duplicate"


def test_forecast_endpoints(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    fast = _product(db, store, "FAST-1", qty=4)
    _product(db, store, "IDLE-1", qty=25)
    context = resolve_store_context(db, store.id)
    for days_ago in range(1, 20):
        _sell(db, store, fast, days_ago=days_ago, qty=2)
    db.commit()

    run = client.post(f"/ml/forecast/run?store_id={store.id}")
    assert run.status_code == 200, run.text
    assert run.json()["products"] == 2

    reorder = client.get(f"/ml/forecast/stock?store_id={store.id}&view=reorder").json()
    assert [row["sku"] for row in reorder] == ["FAST-1"]
    assert reorder[0]["suggested_reorder_qty"] > 0
    assert reorder[0]["unit_label"] == "kg"

    risk = client.get(f"/ml/forecast/stock?store_id={store.id}&view=dead_risk").json()
    assert [row["sku"] for row in risk] == ["IDLE-1"]
    assert risk[0]["days_to_stockout"] is None


def test_insights_carry_the_forward_looking_numbers(db) -> None:
    from app.agents import insights

    store = _store(db, "grocery", "Sharma Kirana")
    fast = _product(db, store, "FAST-1", qty=4)
    _product(db, store, "IDLE-1", qty=25)
    for days_ago in range(1, 20):
        _sell(db, store, fast, days_ago=days_ago, qty=2)
    db.commit()

    context = resolve_store_context(db, store.id)
    metrics = insights.compute_metrics(db, context)

    assert metrics["reorder_soon_count"] >= 1
    assert metrics["predicted_dead_stock_count"] >= 1
    assert metrics["forecast_window_days"] == forecasting.window_days(context)

    suggestions = insights.template_suggestions(metrics)
    assert len(suggestions) == 3
