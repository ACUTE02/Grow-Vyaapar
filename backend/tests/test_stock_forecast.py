"""Stock forecast model: features from history, no leakage, reproducible
metrics, and a moving-average fallback that never leaves a product without a
number."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.agents import churn, forecasting
from app.ml import stock_forecast_model
from app.models.base import utcnow
from app.models.core import Customer, Product, StockLevel, Transaction, TransactionItem
from app.models.ml import ModelRun
from app.services.errors import ValidationError
from app.verticals.context import resolve_store_context
from tests.test_segmentation import _store

PHONES = iter(range(2_000_000, 3_000_000))

# Enough weeks for a full 12-week trailing window plus a chronological
# train/validation/holdout split with none of the three empty. Forty weeks was
# enough for version 1, whose window was four weeks and whose split was random.
TRAINABLE_WEEKS = 60


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
    _weekly_sales(db, store, product, weeks=TRAINABLE_WEEKS, qty=5.0)
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
    _weekly_sales(db, store, product, weeks=TRAINABLE_WEEKS, qty=5.0)
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
    _weekly_sales(db, store, trained_on, weeks=TRAINABLE_WEEKS, qty=5.0)
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
    _weekly_sales(db, store, product, weeks=TRAINABLE_WEEKS, qty=5.0)
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
    _weekly_sales(db, store, trained_on, weeks=TRAINABLE_WEEKS, qty=5.0)
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
    _weekly_sales(db, store, product, weeks=TRAINABLE_WEEKS, qty=5.0)
    db.commit()

    response = client.post(f"/ml/stock_forecast/train?store_id={store.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_name"] == "stock_forecast"
    assert "r2" in body["metrics"]


def test_forecast_stock_endpoint_reports_the_source(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "API-2")
    _weekly_sales(db, store, product, weeks=TRAINABLE_WEEKS, qty=5.0)
    db.commit()
    client.post(f"/ml/stock_forecast/train?store_id={store.id}")

    rows = client.get(f"/ml/forecast/stock?store_id={store.id}&view=all").json()
    row = next(r for r in rows if r["sku"] == "API-2")
    assert row["source"] == "model"


def test_training_never_writes_into_the_app_model_directory(db) -> None:
    """A test run must not overwrite the artefacts the running app serves.

    Fixture stores reuse the real store ids, and an artefact is named by store
    id alone, so before ML_MODEL_DIR existed a `pytest` run replaced
    backend/models/stock_forecast_1.joblib - the grocery store's real model -
    with one trained on this file's fixture data, where every product sells
    exactly 5 a week at 100 rupees. The result was a model that predicted the
    constant 5.0 for every product, with every feature importance at zero.
    """
    app_model_dir = Path(stock_forecast_model.__file__).resolve().parents[2] / "models"

    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "ISO-1")
    _weekly_sales(db, store, product, weeks=TRAINABLE_WEEKS, qty=5.0)
    db.commit()
    context = resolve_store_context(db, store.id)

    stock_forecast_model.train_store(db, context)
    db.commit()

    written = stock_forecast_model.model_path(store.id)
    assert written.exists()
    assert app_model_dir not in written.parents, (
        f"training wrote {written}, inside the app's own model directory"
    )
    # The same isolation has to hold for churn, which names artefacts the same way.
    assert app_model_dir not in churn.model_path(store.id).parents


def test_training_records_how_the_model_compares_with_a_mean_baseline(db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    for index in range(3):
        product = _product(db, store, f"BASE-{index}")
        _weekly_sales(db, store, product, weeks=TRAINABLE_WEEKS, qty=5.0 + index)
    db.commit()
    context = resolve_store_context(db, store.id)

    metrics = stock_forecast_model.train_store(db, context)
    db.commit()

    assert "baseline_mae" in metrics
    assert isinstance(metrics["beats_baseline"], bool)
    assert metrics["beats_baseline"] == (metrics["mae"] < metrics["baseline_mae"])
    assert metrics["usable"] == (metrics["mae"] <= metrics["baseline_mae"] + 1e-9)


def test_a_model_that_loses_to_the_baseline_is_not_served(db) -> None:
    """The forecast then falls back to the moving average for every product,
    which is the honest outcome: a model no better than predicting the mean
    must not decide how much stock a shop buys."""
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "GATE-1")
    _weekly_sales(db, store, product, weeks=TRAINABLE_WEEKS, qty=5.0)
    db.commit()
    context = resolve_store_context(db, store.id)

    stock_forecast_model.train_store(db, context)
    db.commit()

    run = stock_forecast_model.latest_run(db, store.id)
    assert run is not None
    run.metrics = {**(run.metrics or {}), "usable": False}
    db.commit()

    assert stock_forecast_model.predict_weekly_units(db, context) == {}

    rows = forecasting.compute(db, context)
    assert rows, "the moving-average fallback must still produce a forecast"
    assert all(row.source == "estimate" for row in rows)


def test_status_endpoint_explains_why_the_model_is_not_used(client, db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "STAT-1")
    _weekly_sales(db, store, product, weeks=TRAINABLE_WEEKS, qty=5.0)
    db.commit()

    before = client.get(f"/ml/stock_forecast/status?store_id={store.id}")
    assert before.status_code == 200
    assert before.json()["trained"] is False
    assert before.json()["in_use"] is False

    client.post(f"/ml/stock_forecast/train?store_id={store.id}")

    run = stock_forecast_model.latest_run(db, store.id)
    run.metrics = {**(run.metrics or {}), "usable": False, "mae": 9.0, "baseline_mae": 4.0}
    db.commit()

    after = client.get(f"/ml/stock_forecast/status?store_id={store.id}").json()
    assert after["trained"] is True
    assert after["in_use"] is False
    assert "worse than simply predicting the mean" in after["explanation"]


# -- version 2: time-aware evaluation ----------------------------------------
def test_the_split_is_chronological_and_no_week_straddles_a_boundary(db) -> None:
    """A random split lets the model learn from a week and then be tested on
    the week before it, which is not something a forecast can do. Version 1
    used one, and its flattering numbers were partly that."""
    store = _store(db, "grocery", "Sharma Kirana")
    for index in range(3):
        product = _product(db, store, f"SPLIT-{index}")
        _weekly_sales(db, store, product, weeks=TRAINABLE_WEEKS, qty=4.0 + index)
    db.commit()
    context = resolve_store_context(db, store.id)

    _features, _labels, weeks, _edges = stock_forecast_model.build_training_set(db, context)
    train, validation, holdout = stock_forecast_model.chronological_split(weeks)

    train_weeks = {week for week, flag in zip(weeks, train) if flag}
    validation_weeks = {week for week, flag in zip(weeks, validation) if flag}
    holdout_weeks = {week for week, flag in zip(weeks, holdout) if flag}

    assert train_weeks and validation_weeks and holdout_weeks
    assert not train_weeks & validation_weeks, "a week is in both train and validation"
    assert not validation_weeks & holdout_weeks, "a week is in both validation and holdout"
    assert not train_weeks & holdout_weeks, "a week is in both train and holdout"
    # And they are in time order, which is the whole point.
    assert max(train_weeks) < min(validation_weeks) < max(validation_weeks) < min(holdout_weeks)


def test_a_features_row_cannot_see_the_future(db) -> None:
    """Built for the same week twice, once with later weeks present and once
    without, the row must be byte-for-byte identical. If any feature reached
    forward, adding a future week would change it."""
    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "LEAK-1")
    _weekly_sales(db, store, product, weeks=TRAINABLE_WEEKS, qty=5.0)
    db.commit()
    context = resolve_store_context(db, store.id)

    histories = stock_forecast_model._histories(db, store.id)
    history = histories[product.id]
    rhythm = stock_forecast_model._rhythm(histories)
    edges = stock_forecast_model._price_bands(histories)

    weeks = sorted(history.weekly)
    as_of = weeks[len(weeks) // 2]
    with_future = stock_forecast_model._features_at(history, as_of, edges, rhythm)

    # The same product and store, with every week after `as_of` deleted.
    truncated = stock_forecast_model.ProductHistory(
        history.product_id,
        history.category_id,
        history.sell_price,
        history.qty_on_hand,
        weekly={w: q for w, q in history.weekly.items() if w <= as_of},
        daily={d: q for d, q in history.daily.items() if stock_forecast_model._week_index(d) <= as_of},
    )
    truncated_rhythm = stock_forecast_model.StoreRhythm(
        weekly_units={w: q for w, q in rhythm.weekly_units.items() if w <= as_of},
        category_weekly={k: v for k, v in rhythm.category_weekly.items() if k[1] <= as_of},
    )
    without_future = stock_forecast_model._features_at(
        truncated, as_of, edges, truncated_rhythm
    )

    assert with_future == without_future, (
        "a feature changed when future weeks were removed, so something reaches forward"
    )


def test_the_calendar_features_describe_the_week_being_predicted(db) -> None:
    """The one thing read from ahead is which month week w+1 falls in, and a
    wall calendar supplies that. Asserted rather than assumed."""
    import math

    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "CAL-1")
    _weekly_sales(db, store, product, weeks=TRAINABLE_WEEKS, qty=5.0)
    db.commit()

    histories = stock_forecast_model._histories(db, store.id)
    history = histories[product.id]
    rhythm = stock_forecast_model._rhythm(histories)
    as_of = sorted(history.weekly)[10]

    values = stock_forecast_model._features_at(history, as_of, [0.0, 0.0], rhythm)
    target_month = stock_forecast_model._week_start(as_of + 1).month

    assert values["target_month_sin"] == pytest.approx(math.sin(2 * math.pi * target_month / 12))
    assert values["target_month_cos"] == pytest.approx(math.cos(2 * math.pi * target_month / 12))


def test_the_run_records_the_full_evaluation_not_just_a_score(db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    for index in range(3):
        product = _product(db, store, f"META-{index}")
        _weekly_sales(db, store, product, weeks=TRAINABLE_WEEKS, qty=4.0 + index)
    db.commit()
    context = resolve_store_context(db, store.id)

    metrics = stock_forecast_model.train_store(db, context)
    db.commit()

    assert metrics["chosen_model"] in stock_forecast_model._candidates()
    # Chosen on validation, and every candidate's validation score is kept, so
    # the choice can be re-checked rather than taken on trust.
    assert set(metrics["validation_mae"]) == set(stock_forecast_model._candidates())
    assert metrics["chosen_model"] == min(
        metrics["validation_mae"], key=metrics["validation_mae"].get
    )
    for key in ("mae", "rmse", "r2", "baseline_mae", "baseline_rmse", "usable"):
        assert key in metrics
    assert metrics["train_rows"] and metrics["validation_rows"] and metrics["holdout_rows"]
    assert metrics["train_weeks"][1] < metrics["validation_weeks"][0]
    assert metrics["validation_weeks"][1] < metrics["holdout_weeks"][0]
    assert metrics["features"] == stock_forecast_model.FEATURES


def test_a_prediction_comes_back_for_every_product_with_enough_history(db) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    products = []
    for index in range(3):
        product = _product(db, store, f"PRED-{index}")
        _weekly_sales(db, store, product, weeks=TRAINABLE_WEEKS, qty=4.0 + index)
        products.append(product)
    db.commit()
    context = resolve_store_context(db, store.id)

    stock_forecast_model.train_store(db, context)
    db.commit()

    predictions = stock_forecast_model.predict_weekly_units(db, context)
    assert set(predictions) == {product.id for product in products}
    assert all(value >= 0 for value in predictions.values()), "negative demand is not a thing"


def test_an_artefact_from_an_older_feature_set_is_refused_not_guessed(db) -> None:
    """A saved model whose feature list this version cannot build must send the
    caller to the moving average rather than be fed a column of guesses."""
    import joblib

    store = _store(db, "grocery", "Sharma Kirana")
    product = _product(db, store, "OLDART-1")
    _weekly_sales(db, store, product, weeks=TRAINABLE_WEEKS, qty=5.0)
    db.commit()
    context = resolve_store_context(db, store.id)

    stock_forecast_model.train_store(db, context)
    db.commit()

    path = stock_forecast_model.model_path(store.id)
    artefact = joblib.load(path)
    artefact["features"] = [*artefact["features"], "a_feature_from_a_future_version"]
    joblib.dump(artefact, path)

    assert stock_forecast_model.predict_weekly_units(db, context) == {}
