"""Stock forecast model: features from history, no leakage, reproducible
metrics, and a moving-average fallback that never leaves a product without a
number."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.agents import forecasting
from app.ml import stock_forecast_model
from app.models.base import utcnow
from app.models.core import Customer, Product, StockLevel, Transaction, TransactionItem
from app.models.ml import ModelRun
from app.services.errors import ValidationError
from app.verticals.context import resolve_store_context
from tests.test_segmentation import _store

PHONES = iter(range(2_000_000, 3_000_000))


def _product(
    db, store, sku: str, qty_on_hand: float = 100.0, sell_price: str = "100.00"
) -> Product:
    product = Product(
        store_id=store.id,
        sku=sku,
        name=f"Item {sku}",
        cost_price=Decimal("40.00"),
        sell_price=Decimal(sell_price),
        gst_rate=Decimal("5"),
        attributes={},
    )
    db.add(product)
    db.flush()
    db.add(
        StockLevel(
            product_id=product.id,
            qty_on_hand=Decimal(str(qty_on_hand)),
            reorder_point=Decimal("5"),
        )
    )
    db.flush()
    return product


def _weekly_sales(db, store, product, weeks: int, qty: float = 5.0) -> None:
    """One sale a week for the last `weeks` weeks, ending last week - the
    current week is always in progress and must never be trained on."""
    customer = db.scalar(select(Customer).where(Customer.store_id == store.id))
    if customer is None:
        customer = Customer(store_id=store.id, name="Buyer", phone=f"9{next(PHONES):09d}")
        db.add(customer)
        db.flush()
    for week in range(1, weeks + 1):
        stamp = utcnow() - timedelta(weeks=week)
        transaction = Transaction(
            store_id=store.id,
            customer_id=customer.id,
            invoice_no=f"INV-{store.id:02d}-{product.id:04d}-{week:04d}",
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


# -- training ------------------------------------------------------------
def test_training_needs_a_minimum_number_of_rows(db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "SPARSE-1")
    _weekly_sales(db, store, product, weeks=3)  # nowhere near enough
    db.commit()
    context = resolve_store_context(db, store.id)
    with pytest.raises(ValidationError):
        stock_forecast_model.train_store(db, context)


def test_training_produces_a_model_run_and_a_saved_artefact(db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "REG-1")
    _weekly_sales(db, store, product, weeks=40, qty=5.0)
    db.commit()
    context = resolve_store_context(db, store.id)

    metrics = stock_forecast_model.train_store(db, context)
    db.commit()

    assert "r2" in metrics and "mae" in metrics
    assert metrics["feature_importances"]
    assert stock_forecast_model.model_path(store.id).exists()

    run = db.scalar(
        select(ModelRun).where(
            ModelRun.store_id == store.id, ModelRun.model_name == "stock_forecast"
        )
    )
    assert run is not None
    assert run.rows_trained >= 30


def test_retraining_is_deterministic(db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "DET-1")
    _weekly_sales(db, store, product, weeks=40, qty=5.0)
    db.commit()
    context = resolve_store_context(db, store.id)

    first = stock_forecast_model.train_store(db, context)
    db.commit()
    second = stock_forecast_model.train_store(db, context)
    db.commit()

    assert first["r2"] == second["r2"]
    assert first["mae"] == second["mae"]
    assert first["feature_importances"] == second["feature_importances"]


# -- the fallback is load-bearing -----------------------------------------
def test_a_product_with_too_little_history_is_not_scored_by_the_model(db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    trained_on = _product(db, store, "REG-2")
    _weekly_sales(db, store, trained_on, weeks=40, qty=5.0)
    new_product = _product(db, store, "NEW-1")
    _weekly_sales(db, store, new_product, weeks=2, qty=3.0)  # far under 8 weeks
    db.commit()
    context = resolve_store_context(db, store.id)
    stock_forecast_model.train_store(db, context)
    db.commit()

    predictions = stock_forecast_model.predict_weekly_units(db, context)
    assert trained_on.id in predictions
    assert new_product.id not in predictions


def test_forecast_falls_back_to_the_moving_average_without_a_trained_model(db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "NOMODEL-1")
    _weekly_sales(db, store, product, weeks=2, qty=3.0)
    db.commit()
    context = resolve_store_context(db, store.id)

    forecast = next(
        item for item in forecasting.compute(db, context) if item.product_id == product.id
    )
    assert forecast.source == "estimate"


def test_forecast_uses_the_model_once_trained_and_confident(db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "MODELLED-1")
    _weekly_sales(db, store, product, weeks=40, qty=5.0)
    db.commit()
    context = resolve_store_context(db, store.id)
    stock_forecast_model.train_store(db, context)
    db.commit()

    forecast = next(
        item for item in forecasting.compute(db, context) if item.product_id == product.id
    )
    assert forecast.source == "model"


def test_a_brand_new_product_falls_back_even_after_training(db) -> None:
    """Task 21 acceptance: a new product with no history is badged 'estimate',
    not silently scored by a model that has never seen it sell."""
    store = _store(db, "grocery", "Sharma Kirana")
    trained_on = _product(db, store, "REG-3")
    _weekly_sales(db, store, trained_on, weeks=40, qty=5.0)
    brand_new = _product(db, store, "BRANDNEW-1")  # zero sales ever
    db.commit()
    context = resolve_store_context(db, store.id)
    stock_forecast_model.train_store(db, context)
    db.commit()

    forecast = next(
        item for item in forecasting.compute(db, context) if item.product_id == brand_new.id
    )
    assert forecast.source == "estimate"


# -- the API ----------------------------------------------------------------
def test_the_endpoint_trains_and_reports_metrics(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "API-1")
    _weekly_sales(db, store, product, weeks=40, qty=5.0)
    db.commit()

    response = client.post(f"/ml/stock_forecast/train?store_id={store.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_name"] == "stock_forecast"
    assert "r2" in body["metrics"]


def test_forecast_stock_endpoint_reports_the_source(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "API-2")
    _weekly_sales(db, store, product, weeks=40, qty=5.0)
    db.commit()
    client.post(f"/ml/stock_forecast/train?store_id={store.id}")

    rows = client.get(f"/ml/forecast/stock?store_id={store.id}&view=all").json()
    row = next(r for r in rows if r["sku"] == "API-2")
    assert row["source"] == "model"
