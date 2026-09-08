"""Stock forecast model: a trained regressor for next-week demand per product,
replacing the moving average that `app/agents/forecasting.py` used alone.

Reads core tables, writes only to model_runs - forecasting.py stays the only
writer of stock_forecasts, and only for the same four columns it always wrote;
this module never touches that table.

Rule 8, restated for a regression target instead of a classification label: a
cutoff week is placed at least four weeks into a product's own history (so a
trailing window exists), features are built from that week and everything
before it, and the label is the units actually sold the week after - training
never sees the answer.

Every artefact is versioned and reproducible (rule 9): fixed random_state=42
throughout, one model per store (product mix and rhythm differ too much
across verticals to share one, the same reasoning as churn being per-store),
one model_runs row per run with metrics reported honestly.

One deliberate simplification, stated here rather than buried: qty_on_hand is
this store's CURRENT stock level, used as a static feature on every historical
training row for that product. The schema keeps no historical stock
snapshots, so a true point-in-time value isn't available; this is a known
trade-off, not an oversight.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import Product, StockLevel, Transaction, TransactionItem
from app.models.ml import ModelRun
from app.services.errors import ValidationError
from app.verticals.context import StoreContext

logger = logging.getLogger(__name__)

MODEL_NAME = "stock_forecast"
MODEL_VERSION = "1.0.0"
RANDOM_STATE = 42
MODEL_DIR = Path(__file__).resolve().parents[2] / "models"
EPOCH = date(2020, 1, 1)

# Fewer weeks of history than this for a given product and its prediction is
# not trusted - the caller falls back to the moving average for that product.
MIN_WEEKS_HISTORY = 8
MIN_TRAINING_ROWS = 30
MAX_TRAINING_WEEKS_BACK = 260  # cap the walk-forward window at ~5 years

_DOW_FEATURES = [
    "dow_mon_share", "dow_tue_share", "dow_wed_share", "dow_thu_share",
    "dow_fri_share", "dow_sat_share", "dow_sun_share",
]
FEATURES = [
    "last_week_units",
    "avg_4wk_units",
    "std_4wk_units",
    "weeks_since_last_sale",
    *_DOW_FEATURES,
    "qty_on_hand",
    "category_id",
    "price_band",
]


def model_path(store_id: int) -> Path:
    return MODEL_DIR / f"stock_forecast_{store_id}.joblib"


def _week_index(day: date) -> int:
    return (day - EPOCH).days // 7


@dataclass
class ProductHistory:
    product_id: int
    category_id: int | None
    sell_price: float
    qty_on_hand: float
    weekly: dict[int, float] = field(default_factory=dict)
    daily: dict[date, float] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# feature engineering
# --------------------------------------------------------------------------- #
def _histories(db: Session, store_id: int) -> dict[int, ProductHistory]:
    products = db.execute(
        select(Product.id, Product.category_id, Product.sell_price).where(
            Product.store_id == store_id, Product.is_active.is_(True)
        )
    ).all()
    if not products:
        return {}

    product_ids = [row.id for row in products]
    stock = {
        row.product_id: float(row.qty_on_hand)
        for row in db.execute(
            select(StockLevel.product_id, StockLevel.qty_on_hand).where(
                StockLevel.product_id.in_(product_ids)
            )
        ).all()
    }

    histories = {
        row.id: ProductHistory(row.id, row.category_id, float(row.sell_price), stock.get(row.id, 0.0))
        for row in products
    }

    rows = db.execute(
        select(TransactionItem.product_id, Transaction.created_at, TransactionItem.qty)
        .join(Transaction, Transaction.id == TransactionItem.transaction_id)
        .where(Transaction.store_id == store_id, Transaction.status == "completed")
    ).all()
    for product_id, created_at, qty in rows:
        history = histories.get(product_id)
        if history is None:
            continue
        day = created_at.date() if isinstance(created_at, datetime) else created_at
        quantity = float(qty or 0)
        history.daily[day] = history.daily.get(day, 0.0) + quantity
        week = _week_index(day)
        history.weekly[week] = history.weekly.get(week, 0.0) + quantity

    return histories


def _price_bands(histories: dict[int, ProductHistory]) -> list[float]:
    """Two cut points splitting this store's products into low/mid/high price
    terciles. A store with fewer than 3 distinct prices gets degenerate cut
    points and every product lands in the same band - correct, if
    uninteresting, rather than an error."""
    prices = sorted(history.sell_price for history in histories.values())
    if not prices:
        return [0.0, 0.0]
    return [prices[len(prices) // 3], prices[(2 * len(prices)) // 3]]


def _band(price: float, edges: list[float]) -> int:
    if price <= edges[0]:
        return 0
    if price <= edges[1]:
        return 1
    return 2


def _dow_shares(daily: dict[date, float], start: date, end: date) -> list[float]:
    """Fraction of the window's quantity sold on each weekday, Monday first."""
    totals = [0.0] * 7
    for day, quantity in daily.items():
        if start <= day <= end:
            totals[day.weekday()] += quantity
    total = sum(totals)
    if total <= 0:
        return [1 / 7] * 7
    return [value / total for value in totals]


def _weeks_since_last_sale(weekly: dict[int, float], as_of_week: int) -> float:
    sold_weeks = [week for week, units in weekly.items() if units > 0 and week <= as_of_week]
    if not sold_weeks:
        return float(MIN_WEEKS_HISTORY * 2)   # never sold as of this point - clearly stale
    return float(as_of_week - max(sold_weeks))


def weeks_of_history(history: ProductHistory, as_of_week: int) -> int:
    """Calendar weeks since this product's first sale, up to as_of_week."""
    sold_weeks = [week for week in history.weekly if history.weekly[week] > 0 and week <= as_of_week]
    if not sold_weeks:
        return 0
    return as_of_week - min(sold_weeks) + 1


def _features_at(history: ProductHistory, as_of_week: int, price_edges: list[float]) -> dict[str, float]:
    """Everything known at the end of as_of_week - never anything after it."""
    window = [history.weekly.get(as_of_week - offset, 0.0) for offset in range(4)]
    mean_4wk = sum(window) / 4
    variance = sum((value - mean_4wk) ** 2 for value in window) / 4

    window_start = EPOCH + timedelta(days=(as_of_week - 3) * 7)
    window_end = EPOCH + timedelta(days=(as_of_week + 1) * 7 - 1)
    dow = _dow_shares(history.daily, window_start, window_end)

    values: dict[str, float] = {
        "last_week_units": history.weekly.get(as_of_week, 0.0),
        "avg_4wk_units": mean_4wk,
        "std_4wk_units": variance**0.5,
        "weeks_since_last_sale": _weeks_since_last_sale(history.weekly, as_of_week),
        "qty_on_hand": history.qty_on_hand,
        "category_id": float(history.category_id or 0),
        "price_band": float(_band(history.sell_price, price_edges)),
    }
    values.update(zip(_DOW_FEATURES, dow))
    return values


def build_training_set(
    db: Session, context: StoreContext
) -> tuple[list[list[float]], list[float], list[float]]:
    """Walk-forward rows: features as of a week, label from the week after it."""
    histories = _histories(db, context.store_id)
    current_week = _week_index(date.today())
    price_edges = _price_bands(histories)

    features: list[list[float]] = []
    labels: list[float] = []
    for product_id in sorted(histories):
        history = histories[product_id]
        if not history.weekly:
            continue
        first_week = min(history.weekly)
        start_week = max(first_week, current_week - MAX_TRAINING_WEEKS_BACK)
        # week+1 must be a fully completed past week - never train on the
        # in-progress one - and week-3 must exist for the trailing window.
        for week in range(start_week, current_week - 1):
            if week - 3 < first_week:
                continue
            values = _features_at(history, week, price_edges)
            features.append([values[name] for name in FEATURES])
            labels.append(history.weekly.get(week + 1, 0.0))

    return features, labels, price_edges


# --------------------------------------------------------------------------- #
# training
# --------------------------------------------------------------------------- #
def train_store(db: Session, context: StoreContext) -> dict[str, Any]:
    """Fit, evaluate, persist, and record the run. Returns the metrics."""
    import joblib  # noqa: PLC0415
    from sklearn.ensemble import RandomForestRegressor  # noqa: PLC0415
    from sklearn.metrics import mean_absolute_error, r2_score  # noqa: PLC0415
    from sklearn.model_selection import train_test_split  # noqa: PLC0415

    features, labels, price_edges = build_training_set(db, context)
    if len(features) < MIN_TRAINING_ROWS:
        raise ValidationError(
            f"{context.store_name} has only {len(features)} (product, week) rows with a full "
            f"trailing window; at least {MIN_TRAINING_ROWS} are needed to train a model"
        )

    x_train, x_test, y_train, y_test = train_test_split(
        features, labels, test_size=0.2, random_state=RANDOM_STATE
    )

    model = RandomForestRegressor(n_estimators=200, random_state=RANDOM_STATE, n_jobs=1)
    model.fit(x_train, y_train)

    predictions = model.predict(x_test)
    r2 = r2_score(y_test, predictions)
    mae = mean_absolute_error(y_test, predictions)
    importances = {
        name: round(float(value), 4)
        for name, value in zip(FEATURES, model.feature_importances_)
    }

    metrics = {
        "r2": round(float(r2), 4),
        "mae": round(float(mae), 4),
        "feature_importances": importances,
        "train_rows": len(x_train),
        "test_rows": len(x_test),
        "min_weeks_history_for_model_use": MIN_WEEKS_HISTORY,
        "limitation": (
            "qty_on_hand is the current stock level, held constant across every historical "
            "training row for a product - no historical stock snapshot exists in this schema. "
            "Trained on synthetic seed data, single store per model, no real seasonality."
        ),
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "features": FEATURES,
            "version": MODEL_VERSION,
            "price_edges": price_edges,
        },
        model_path(context.store_id),
    )

    db.add(
        ModelRun(
            store_id=context.store_id,
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
            rows_trained=len(features),
            metrics=metrics,
            params={
                "estimator": "RandomForestRegressor",
                "n_estimators": 200,
                "random_state": RANDOM_STATE,
                "test_size": 0.2,
                "features": FEATURES,
            },
        )
    )
    db.flush()

    logger.info(
        "Stock forecast model for %s: R^2 %.3f, MAE %.3f on %s rows",
        context.store_name,
        r2,
        mae,
        len(features),
    )
    return metrics


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def predict_weekly_units(db: Session, context: StoreContext) -> dict[int, float]:
    """Predicted next-week units for every product the model has enough of its
    own history to be trusted on. Empty dict - never an exception - if no
    model has been trained yet, so the caller's moving-average fallback is
    always safe to reach for."""
    import joblib  # noqa: PLC0415

    path = model_path(context.store_id)
    if not path.exists():
        return {}

    try:
        artefact = joblib.load(path)
    except Exception:
        logger.exception("Could not load stock forecast model for store %s", context.store_id)
        return {}

    model = artefact["model"]
    feature_names = artefact.get("features", FEATURES)
    price_edges = artefact.get("price_edges", [0.0, 0.0])

    histories = _histories(db, context.store_id)
    as_of_week = _week_index(date.today()) - 1  # the last fully completed week

    confident_ids: list[int] = []
    matrix: list[list[float]] = []
    for product_id, history in histories.items():
        if weeks_of_history(history, as_of_week) < MIN_WEEKS_HISTORY:
            continue
        values = _features_at(history, as_of_week, price_edges)
        matrix.append([values[name] for name in feature_names])
        confident_ids.append(product_id)

    if not matrix:
        return {}

    predictions = model.predict(matrix)
    return {
        product_id: max(float(prediction), 0.0)
        for product_id, prediction in zip(confident_ids, predictions)
    }


def latest_run(db: Session, store_id: int) -> ModelRun | None:
    return db.scalar(
        select(ModelRun)
        .where(ModelRun.store_id == store_id, ModelRun.model_name == MODEL_NAME)
        .order_by(ModelRun.trained_at.desc())
        .limit(1)
    )
