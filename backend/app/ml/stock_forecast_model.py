"""Stock forecast model: a trained regressor for next-week demand per product,
sitting behind the moving average that `app/agents/forecasting.py` falls back to.

Reads core tables, writes only to model_runs - forecasting.py stays the only
writer of stock_forecasts, and only for the same four columns it always wrote;
this module never touches that table.

Two things decide whether this is honest, and both are here rather than in a
comment somewhere:

**The split is chronological.** Weeks are ordered, the earliest 70% train, the
next 15% validate, the last 15% are held out and touched once. A random split
would let the model learn from a week and then be tested on the week before
it, which is not a thing a forecast can do. Version 1 used a random split, and
its flattering numbers were partly that.

**The holdout chooses nothing.** Candidate models are fitted on train, one is
chosen by validation error, and only then is the holdout scored. The baseline -
predict the training mean for every product and week - is scored on the same
holdout, and `predict_weekly_units` refuses to serve a model that does not beat
it. On the seeded data that refusal fires for at least one store, which is the
point of having it.

Rule 8, restated for a regression target: features for week *w* are built from
week *w* and earlier, and the label is what actually sold in week *w+1*. The
one thing read from the future is the CALENDAR position of week w+1 - which
month and week of the year it falls in - because a shopkeeper knows that today
from a wall calendar. It is the strongest honest signal in the data: the seed
weights demand by month, and a store's monthly share of the year's units
ranges from 3.3% to 14.8%.

Every artefact is versioned and reproducible (rule 9): fixed random_state=42
throughout, one model per store (product mix and rhythm differ too much across
verticals to share one, the same reasoning as churn being per-store), one
model_runs row per run with metrics reported honestly.

One deliberate simplification, stated here rather than buried: qty_on_hand is
this store's CURRENT stock level, used as a static feature on every historical
training row for that product. The schema keeps no historical stock snapshots,
so a true point-in-time value isn't available; this is a known trade-off, not
an oversight.
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import Product, StockLevel, Transaction, TransactionItem
from app.models.ml import ModelRun
from app.services.errors import ValidationError
from app.settings import settings
from app.verticals.context import StoreContext

logger = logging.getLogger(__name__)

MODEL_NAME = "stock_forecast"
MODEL_VERSION = "2.0.0"
RANDOM_STATE = 42
MODEL_DIR = (
    Path(settings.ml_model_dir)
    if settings.ml_model_dir
    else Path(__file__).resolve().parents[2] / "models"
)
EPOCH = date(2020, 1, 1)

# The longest trailing window a feature needs. A product with less history than
# this has no row in the training set and no prediction at serving time - the
# caller falls back to the moving average for it.
TRAILING_WEEKS = 12
MIN_WEEKS_HISTORY = TRAILING_WEEKS
MIN_TRAINING_ROWS = 30
MAX_TRAINING_WEEKS_BACK = 260  # cap the walk-forward window at ~5 years

# Chronological split, on the week rather than the row, so no week is ever on
# both sides of a boundary.
TRAIN_FRACTION = 0.70
VALIDATION_FRACTION = 0.15

FEATURES = [
    # -- the product's own recent demand ------------------------------------
    "lag_1w",                 # units sold in the feature week itself
    "lag_2w",                 # and the week before that
    "lag_4w",                 # and four weeks back, for a month-ago echo
    "rolling_mean_4",         # short-run rate: fast to react, noisy
    "rolling_mean_8",
    "rolling_mean_12",        # long-run rate: the best estimate of the product's own level
    "rolling_std_4",          # how erratic this product has been lately
    "weeks_since_last_sale",  # staleness; large for a product that has stopped
    "trend_4_over_12",        # short rate over long rate: rising or fading
    # -- the shop around it --------------------------------------------------
    # A single product's week is mostly noise; the store's week is not. These
    # two carry the seasonal multiplier empirically, without the model having
    # to learn the calendar from scratch.
    "store_units_last_week",
    "store_ratio_recent",     # store's last week over its own 8-week mean
    "category_rate",          # mean units per product in this category, that week
    # -- where in the year the week being predicted falls ---------------------
    # Cyclical, so December and January are neighbours rather than 11 apart.
    "target_month_sin",
    "target_month_cos",
    "target_woy_sin",
    "target_woy_cos",
    # -- slow-moving product attributes --------------------------------------
    "qty_on_hand",
    "price_band",
]


def model_path(store_id: int) -> Path:
    return MODEL_DIR / f"stock_forecast_{store_id}.joblib"


def _week_index(day: date) -> int:
    return (day - EPOCH).days // 7


def _week_start(week: int) -> date:
    return EPOCH + timedelta(days=week * 7)


@dataclass
class ProductHistory:
    product_id: int
    category_id: int | None
    sell_price: float
    qty_on_hand: float
    weekly: dict[int, float] = field(default_factory=dict)
    daily: dict[date, float] = field(default_factory=dict)


@dataclass
class StoreRhythm:
    """What the shop as a whole was doing, week by week.

    Built once per training or scoring run and shared by every product, because
    the seasonal multiplier belongs to the store rather than to any one item.
    """

    weekly_units: dict[int, float]
    category_weekly: dict[tuple[int, int], float]


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


def _rhythm(histories: dict[int, ProductHistory]) -> StoreRhythm:
    """Store and category totals per week, from the same history."""
    weekly: dict[int, float] = defaultdict(float)
    per_category: dict[tuple[int, int], list[float]] = defaultdict(list)
    for history in histories.values():
        category = history.category_id or 0
        for week, units in history.weekly.items():
            weekly[week] += units
            per_category[(category, week)].append(units)
    category_weekly = {
        key: sum(values) / len(values) for key, values in per_category.items() if values
    }
    return StoreRhythm(weekly_units=dict(weekly), category_weekly=category_weekly)


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


def _features_at(
    history: ProductHistory,
    as_of_week: int,
    price_edges: list[float],
    rhythm: StoreRhythm,
) -> dict[str, float]:
    """Everything known at the end of as_of_week, plus the calendar position of
    the week after it - which is knowledge a wall calendar provides, not
    knowledge of the future."""
    window4 = [history.weekly.get(as_of_week - offset, 0.0) for offset in range(4)]
    window8 = [history.weekly.get(as_of_week - offset, 0.0) for offset in range(8)]
    window12 = [history.weekly.get(as_of_week - offset, 0.0) for offset in range(12)]
    mean4 = sum(window4) / 4
    mean8 = sum(window8) / 8
    mean12 = sum(window12) / 12
    variance4 = sum((value - mean4) ** 2 for value in window4) / 4

    store_last = rhythm.weekly_units.get(as_of_week, 0.0)
    store_mean8 = sum(rhythm.weekly_units.get(as_of_week - o, 0.0) for o in range(8)) / 8
    # 1.0 means "an ordinary week for this shop"; above means busier than usual.
    store_ratio = (store_last / store_mean8) if store_mean8 > 0 else 1.0

    target_week = _week_start(as_of_week + 1)
    month = target_week.month
    week_of_year = target_week.isocalendar().week

    return {
        "lag_1w": history.weekly.get(as_of_week, 0.0),
        "lag_2w": history.weekly.get(as_of_week - 1, 0.0),
        "lag_4w": history.weekly.get(as_of_week - 3, 0.0),
        "rolling_mean_4": mean4,
        "rolling_mean_8": mean8,
        "rolling_mean_12": mean12,
        "rolling_std_4": variance4**0.5,
        "weeks_since_last_sale": _weeks_since_last_sale(history.weekly, as_of_week),
        "trend_4_over_12": (mean4 / mean12) if mean12 > 0 else 1.0,
        "store_units_last_week": store_last,
        "store_ratio_recent": store_ratio,
        "category_rate": rhythm.category_weekly.get(
            (history.category_id or 0, as_of_week), 0.0
        ),
        "target_month_sin": math.sin(2 * math.pi * month / 12),
        "target_month_cos": math.cos(2 * math.pi * month / 12),
        "target_woy_sin": math.sin(2 * math.pi * week_of_year / 52),
        "target_woy_cos": math.cos(2 * math.pi * week_of_year / 52),
        "qty_on_hand": history.qty_on_hand,
        "price_band": float(_band(history.sell_price, price_edges)),
    }


def build_training_set(
    db: Session, context: StoreContext
) -> tuple[list[list[float]], list[float], list[int], list[float]]:
    """Walk-forward rows: features as of a week, label from the week after it.

    Returns the feature matrix, the labels, the feature week of each row (which
    is what the chronological split is made on) and the price band cut points.
    """
    histories = _histories(db, context.store_id)
    rhythm = _rhythm(histories)
    current_week = _week_index(date.today())
    price_edges = _price_bands(histories)

    features: list[list[float]] = []
    labels: list[float] = []
    weeks: list[int] = []
    for product_id in sorted(histories):
        history = histories[product_id]
        if not history.weekly:
            continue
        first_week = min(history.weekly)
        start_week = max(first_week, current_week - MAX_TRAINING_WEEKS_BACK)
        # week+1 must be a fully completed past week - never train on the
        # in-progress one - and the whole trailing window must exist.
        for week in range(start_week, current_week - 1):
            if week - (TRAILING_WEEKS - 1) < first_week:
                continue
            values = _features_at(history, week, price_edges, rhythm)
            features.append([values[name] for name in FEATURES])
            labels.append(history.weekly.get(week + 1, 0.0))
            weeks.append(week)

    return features, labels, weeks, price_edges


def chronological_split(weeks: list[int]) -> tuple[list[bool], list[bool], list[bool]]:
    """Earliest weeks train, middle validate, latest hold out.

    The split is made on the ordered set of weeks and then applied to rows, so
    every row of a given week lands on the same side of every boundary. A row
    from week 340 can never be used to predict week 300.
    """
    ordered = sorted(set(weeks))
    if len(ordered) < 3:
        raise ValidationError(
            f"Only {len(ordered)} distinct weeks of history; a chronological "
            "train/validation/holdout split needs at least 3"
        )
    train_end = ordered[int(len(ordered) * TRAIN_FRACTION)]
    validation_end = ordered[int(len(ordered) * (TRAIN_FRACTION + VALIDATION_FRACTION))]

    train = [week <= train_end for week in weeks]
    validation = [train_end < week <= validation_end for week in weeks]
    holdout = [week > validation_end for week in weeks]
    return train, validation, holdout


def _candidates() -> dict[str, Any]:
    """Models worth trying on a few thousand rows of weekly retail counts.

    No deep learning: with 7,000 rows, 18 features and a target whose variance
    is mostly Poisson noise, it would be a slower way to reach the same place.
    Each of these is small enough to ship and quick enough to retrain on a
    laptop during a demo.
    """
    from sklearn.ensemble import (  # noqa: PLC0415
        HistGradientBoostingRegressor,
        RandomForestRegressor,
    )
    from sklearn.linear_model import Ridge  # noqa: PLC0415

    return {
        "ridge": Ridge(alpha=1.0),
        "random_forest_leaf50": RandomForestRegressor(
            n_estimators=200, min_samples_leaf=50, random_state=RANDOM_STATE, n_jobs=1
        ),
        "random_forest_leaf150": RandomForestRegressor(
            n_estimators=150, min_samples_leaf=150, random_state=RANDOM_STATE, n_jobs=1
        ),
        "hist_gradient_boosting": HistGradientBoostingRegressor(
            max_iter=300,
            learning_rate=0.05,
            max_leaf_nodes=15,
            min_samples_leaf=40,
            l2_regularization=1.0,
            random_state=RANDOM_STATE,
        ),
    }


# --------------------------------------------------------------------------- #
# training
# --------------------------------------------------------------------------- #
def train_store(db: Session, context: StoreContext) -> dict[str, Any]:
    """Fit the candidates, choose one on validation, score it once on the
    holdout, persist it, and record the run. Returns the metrics."""
    import joblib  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    from sklearn.metrics import mean_absolute_error, r2_score  # noqa: PLC0415

    features, labels, weeks, price_edges = build_training_set(db, context)
    if len(features) < MIN_TRAINING_ROWS:
        raise ValidationError(
            f"{context.store_name} has only {len(features)} (product, week) rows with a full "
            f"{TRAILING_WEEKS}-week trailing window; at least {MIN_TRAINING_ROWS} are needed "
            "to train a model"
        )

    x = np.array(features, dtype=float)
    y = np.array(labels, dtype=float)
    train_mask, validation_mask, holdout_mask = (
        np.array(part) for part in chronological_split(weeks)
    )
    if not (train_mask.any() and validation_mask.any() and holdout_mask.any()):
        raise ValidationError(
            f"{context.store_name} does not have enough weeks of history to hold out a "
            "validation and a test period without one of them being empty"
        )

    x_train, y_train = x[train_mask], y[train_mask]
    x_validation, y_validation = x[validation_mask], y[validation_mask]
    x_holdout, y_holdout = x[holdout_mask], y[holdout_mask]

    # Fit every candidate on the training weeks only, and choose between them
    # on the validation weeks. The holdout is not consulted here.
    validation_scores: dict[str, float] = {}
    fitted: dict[str, Any] = {}
    for name, model in _candidates().items():
        model.fit(x_train, y_train)
        fitted[name] = model
        validation_scores[name] = float(
            mean_absolute_error(y_validation, model.predict(x_validation))
        )
    chosen_name = min(validation_scores, key=validation_scores.get)
    model = fitted[chosen_name]

    # One look at the holdout, for the model that was already chosen.
    predictions = model.predict(x_holdout)
    mae = float(mean_absolute_error(y_holdout, predictions))
    rmse = float(np.sqrt(((y_holdout - predictions) ** 2).mean()))
    r2 = float(r2_score(y_holdout, predictions))

    # What a model with no features at all scores on the same holdout: predict
    # the training mean, every time. A regressor that cannot beat this has
    # learned nothing, and saying so in the metrics is the only way the serving
    # path can refuse to use it (see `model_is_usable`).
    baseline = np.full_like(y_holdout, y_train.mean())
    baseline_mae = float(mean_absolute_error(y_holdout, baseline))
    baseline_rmse = float(np.sqrt(((y_holdout - baseline) ** 2).mean()))
    beats_baseline = bool(mae < baseline_mae)
    usable = bool(mae <= baseline_mae + 1e-9)

    metrics = {
        "chosen_model": chosen_name,
        "validation_mae": {name: round(score, 4) for name, score in validation_scores.items()},
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": round(r2, 4),
        "baseline_mae": round(baseline_mae, 4),
        "baseline_rmse": round(baseline_rmse, 4),
        "baseline_description": "predict the training mean for every product and week",
        "beats_baseline": beats_baseline,
        "usable": usable,
        "improvement_vs_baseline_pct": round((baseline_mae - mae) / baseline_mae * 100, 2)
        if baseline_mae
        else 0.0,
        "train_rows": int(train_mask.sum()),
        "validation_rows": int(validation_mask.sum()),
        "holdout_rows": int(holdout_mask.sum()),
        "train_weeks": [int(min(weeks)), int(max(np.array(weeks)[train_mask]))],
        "validation_weeks": [
            int(min(np.array(weeks)[validation_mask])),
            int(max(np.array(weeks)[validation_mask])),
        ],
        "holdout_weeks": [
            int(min(np.array(weeks)[holdout_mask])),
            int(max(np.array(weeks)[holdout_mask])),
        ],
        "split": "chronological 70/15/15 on the week, holdout scored once",
        "features": list(FEATURES),
        "min_weeks_history_for_model_use": MIN_WEEKS_HISTORY,
        "limitation": (
            "qty_on_hand is the current stock level, held constant across every historical "
            "training row for a product - no historical stock snapshot exists in this schema. "
            "Trained on synthetic seed data whose per-product demand is close to Poisson noise "
            "around a shared rate, so most of what is learnable is store-level seasonality."
        ),
    }

    importances = _explain(model, chosen_name)
    if importances:
        metrics["feature_importances"] = importances

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": model,
            "features": FEATURES,
            "version": MODEL_VERSION,
            "price_edges": price_edges,
            "chosen_model": chosen_name,
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
                "estimator": chosen_name,
                "candidates": sorted(_candidates()),
                "random_state": RANDOM_STATE,
                "train_fraction": TRAIN_FRACTION,
                "validation_fraction": VALIDATION_FRACTION,
                "trailing_weeks": TRAILING_WEEKS,
                "features": FEATURES,
            },
        )
    )
    db.flush()

    logger.info(
        "Stock forecast for %s: %s, holdout MAE %.4f against baseline %.4f (%s)",
        context.store_name,
        chosen_name,
        mae,
        baseline_mae,
        "served" if usable else "refused, falling back to the moving average",
    )
    return metrics


def _explain(model: Any, name: str) -> dict[str, float]:
    """Feature importances where the estimator offers them, coefficients where
    it offers those instead, and nothing rather than a guess otherwise."""
    if hasattr(model, "feature_importances_"):
        return {
            feature: round(float(value), 4)
            for feature, value in zip(FEATURES, model.feature_importances_)
        }
    if hasattr(model, "coef_"):
        return {
            feature: round(float(value), 4)
            for feature, value in zip(FEATURES, model.coef_)
        }
    logger.info("No feature explanation available for %s", name)
    return {}


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def predict_weekly_units(db: Session, context: StoreContext) -> dict[int, float]:
    """Predicted next-week units for every product the model has enough of its
    own history to be trusted on. Empty dict - never an exception - if no model
    has been trained or if the trained one lost to the baseline, so the
    caller's moving-average fallback is always safe to reach for."""
    import joblib  # noqa: PLC0415

    path = model_path(context.store_id)
    if not path.exists():
        return {}

    # A model that lost to "predict the mean" on its own holdout must not drive
    # a shopkeeper's reorder quantities. Refusing here rather than in the UI
    # means the caller's moving-average fallback takes over for every product,
    # and the forecast row honestly reads "estimate" instead of "model".
    if not model_is_usable(db, context.store_id):
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
    rhythm = _rhythm(histories)
    as_of_week = _week_index(date.today()) - 1  # the last fully completed week

    confident_ids: list[int] = []
    matrix: list[list[float]] = []
    for product_id, history in histories.items():
        if weeks_of_history(history, as_of_week) < MIN_WEEKS_HISTORY:
            continue
        values = _features_at(history, as_of_week, price_edges, rhythm)
        try:
            matrix.append([values[name] for name in feature_names])
        except KeyError:
            # An artefact trained by an older version, whose feature list this
            # code can no longer build. Refusing beats guessing a column.
            logger.warning(
                "Stock forecast artefact for store %s expects features this version does not "
                "produce; retrain it. Falling back to the moving average.",
                context.store_id,
            )
            return {}
        confident_ids.append(product_id)

    if not matrix:
        return {}

    predictions = model.predict(matrix)
    return {
        product_id: max(float(prediction), 0.0)
        for product_id, prediction in zip(confident_ids, predictions)
    }


def model_is_usable(db: Session, store_id: int) -> bool:
    """Did the last training run beat the no-feature baseline?

    "Usable" is the weak test - no worse than predicting the mean - not the
    strong one. A model that ties the baseline still gets served; one that
    loses to it does not.

    A missing verdict means the run predates this comparison; those are treated
    as usable so an older artefact is not silently switched off. The next
    training run records a verdict either way.
    """
    run = latest_run(db, store_id)
    if run is None:
        return False
    return bool((run.metrics or {}).get("usable", True))


def latest_run(db: Session, store_id: int) -> ModelRun | None:
    return db.scalar(
        select(ModelRun)
        .where(ModelRun.store_id == store_id, ModelRun.model_name == MODEL_NAME)
        .order_by(ModelRun.trained_at.desc())
        .limit(1)
    )
