"""Churn agent: predict who is about to stop coming, before they lapse.

Reads core tables, writes only to churn_scores and model_runs.

Labels are self-supervised from history (rule 8). A cutoff date is placed one
inactive window before the last transaction in the store, features are computed
using only data at or before that cutoff, and the label is whether the customer
bought again in the window after it. Nothing after the cutoff reaches a feature,
so there is no leakage.

Everything is seeded (rule 9): the same data trains to the same coefficients and
the same metrics, and every score row carries the model_version that produced it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import ChurnScore, Segment
from app.models.base import utcnow
from app.models.core import Customer, Product, Transaction, TransactionItem
from app.models.ml import ModelRun
from app.services.errors import ValidationError
from app.verticals.context import StoreContext

logger = logging.getLogger(__name__)

MODEL_NAME = "churn-logreg"
MODEL_VERSION = "1.0.0"
RANDOM_STATE = 42
MODEL_DIR = Path(__file__).resolve().parents[2] / "models"

FEATURES = [
    "recency_days",
    "frequency_90d",
    "frequency_365d",
    "avg_order_value",
    "total_spend",
    "tenure_days",
    "distinct_categories",
    "days_between_purchases_mean",
    "days_between_purchases_std",
]

HIGH_RISK = 0.7
MEDIUM_RISK = 0.4


def risk_band(probability: float) -> str:
    if probability >= HIGH_RISK:
        return "high"
    if probability >= MEDIUM_RISK:
        return "medium"
    return "low"


def model_path(store_id: int) -> Path:
    return MODEL_DIR / f"churn_{store_id}.joblib"


# --------------------------------------------------------------------------- #
# feature engineering
# --------------------------------------------------------------------------- #
@dataclass
class CustomerHistory:
    customer_id: int
    created_at: datetime
    purchase_dates: list[datetime]
    totals: list[float]
    categories: set[int]


def _histories(
    db: Session, store_id: int, until: datetime | None = None
) -> dict[int, CustomerHistory]:
    """Every completed purchase per customer, optionally only up to a cutoff."""
    statement = (
        select(
            Transaction.customer_id,
            Transaction.id,
            Transaction.created_at,
            Transaction.total,
        )
        .where(
            Transaction.store_id == store_id,
            Transaction.status == "completed",
            Transaction.customer_id.is_not(None),
        )
        .order_by(Transaction.created_at)
    )
    if until is not None:
        statement = statement.where(Transaction.created_at <= until)

    rows = db.execute(statement).all()

    category_statement = (
        select(Transaction.customer_id, Product.category_id)
        .join(TransactionItem, TransactionItem.transaction_id == Transaction.id)
        .join(Product, Product.id == TransactionItem.product_id)
        .where(
            Transaction.store_id == store_id,
            Transaction.status == "completed",
            Transaction.customer_id.is_not(None),
        )
        .distinct()
    )
    if until is not None:
        category_statement = category_statement.where(Transaction.created_at <= until)

    customers = db.execute(
        select(Customer.id, Customer.created_at).where(Customer.store_id == store_id)
    ).all()

    histories = {
        customer_id: CustomerHistory(customer_id, created_at, [], [], set())
        for customer_id, created_at in customers
    }
    for customer_id, _, created_at, total in rows:
        history = histories.get(customer_id)
        if history is None:
            continue
        history.purchase_dates.append(_as_dt(created_at))
        history.totals.append(float(total or 0))
    for customer_id, category_id in db.execute(category_statement).all():
        history = histories.get(customer_id)
        if history is not None and category_id is not None:
            history.categories.add(category_id)
    return histories


def _as_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _features_for(history: CustomerHistory, as_of: datetime) -> dict[str, float]:
    dates = history.purchase_dates
    totals = history.totals

    if dates:
        recency = (as_of - dates[-1]).days
        gaps = [
            (later - earlier).days for earlier, later in zip(dates, dates[1:])
        ]
    else:
        created = _as_dt(history.created_at) if history.created_at else as_of
        recency = (as_of - created).days
        gaps = []

    mean_gap = sum(gaps) / len(gaps) if gaps else 0.0
    if len(gaps) > 1:
        variance = sum((gap - mean_gap) ** 2 for gap in gaps) / (len(gaps) - 1)
        std_gap = variance**0.5
    else:
        std_gap = 0.0

    window_90 = as_of - timedelta(days=90)
    window_365 = as_of - timedelta(days=365)
    created = _as_dt(history.created_at) if history.created_at else as_of

    return {
        "recency_days": float(max(recency, 0)),
        "frequency_90d": float(sum(1 for stamp in dates if stamp >= window_90)),
        "frequency_365d": float(sum(1 for stamp in dates if stamp >= window_365)),
        "avg_order_value": float(sum(totals) / len(totals)) if totals else 0.0,
        "total_spend": float(sum(totals)),
        "tenure_days": float(max((as_of - created).days, 0)),
        "distinct_categories": float(len(history.categories)),
        "days_between_purchases_mean": float(mean_gap),
        "days_between_purchases_std": float(std_gap),
    }


def build_training_set(
    db: Session, context: StoreContext
) -> tuple[list[list[float]], list[int], datetime, list[int]]:
    """Features as of the cutoff, labels from the window after it."""
    inactive_days = context.cfg_int("inactive_days", 90)

    latest = db.scalar(
        select(func.max(Transaction.created_at)).where(
            Transaction.store_id == context.store_id, Transaction.status == "completed"
        )
    )
    if latest is None:
        raise ValidationError(
            f"{context.store_name} has no completed sales, so there is nothing to learn from"
        )
    latest = _as_dt(latest)
    cutoff = latest - timedelta(days=inactive_days)

    past = _histories(db, context.store_id, until=cutoff)

    # Purchases strictly after the cutoff: the observable outcome.
    after_rows = db.execute(
        select(Transaction.customer_id)
        .where(
            Transaction.store_id == context.store_id,
            Transaction.status == "completed",
            Transaction.created_at > cutoff,
            Transaction.created_at <= latest,
        )
        .distinct()
    ).all()
    returned = {row[0] for row in after_rows}

    features: list[list[float]] = []
    labels: list[int] = []
    customer_ids: list[int] = []
    for customer_id, history in past.items():
        if not history.purchase_dates:
            continue                      # nothing to learn from before the cutoff
        values = _features_for(history, cutoff)
        features.append([values[name] for name in FEATURES])
        labels.append(0 if customer_id in returned else 1)
        customer_ids.append(customer_id)

    return features, labels, cutoff, customer_ids


# --------------------------------------------------------------------------- #
# training
# --------------------------------------------------------------------------- #
def train_store(db: Session, context: StoreContext) -> dict[str, Any]:
    """Fit, evaluate, persist, and record the run. Returns the metrics."""
    import joblib  # noqa: PLC0415
    from sklearn.linear_model import LogisticRegression  # noqa: PLC0415
    from sklearn.metrics import (  # noqa: PLC0415
        accuracy_score,
        confusion_matrix,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    from sklearn.model_selection import (  # noqa: PLC0415
        StratifiedKFold,
        cross_val_score,
        train_test_split,
    )
    from sklearn.pipeline import Pipeline  # noqa: PLC0415
    from sklearn.preprocessing import StandardScaler  # noqa: PLC0415

    features, labels, cutoff, _ = build_training_set(db, context)
    if len(features) < 30:
        raise ValidationError(
            f"{context.store_name} has only {len(features)} customers with history before the "
            "cutoff; at least 30 are needed to train a model"
        )
    if len(set(labels)) < 2:
        raise ValidationError(
            f"Every customer of {context.store_name} has the same outcome, so there is nothing "
            "to separate. Widen the history or lower inactive_days."
        )

    x_train, x_test, y_train, y_test = train_test_split(
        features, labels, test_size=0.25, random_state=RANDOM_STATE, stratify=labels
    )

    pipeline = Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    random_state=RANDOM_STATE, max_iter=1000, class_weight="balanced"
                ),
            ),
        ]
    )
    pipeline.fit(x_train, y_train)

    predictions = pipeline.predict(x_test)
    probabilities = pipeline.predict_proba(x_test)[:, 1]
    matrix = confusion_matrix(y_test, predictions).tolist()

    # A 69-row holdout is a noisy estimate on this much data, so the run also
    # records a 5-fold cross-validated AUC and its spread. Both are reported.
    cv_scores = cross_val_score(
        pipeline,
        features,
        labels,
        cv=StratifiedKFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE),
        scoring="roc_auc",
    )

    coefficients = dict(
        zip(FEATURES, (float(value) for value in pipeline.named_steps["model"].coef_[0]))
    )
    metrics = {
        "accuracy": round(float(accuracy_score(y_test, predictions)), 4),
        "precision": round(float(precision_score(y_test, predictions, zero_division=0)), 4),
        "recall": round(float(recall_score(y_test, predictions, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_test, probabilities)), 4),
        "roc_auc_cv_mean": round(float(cv_scores.mean()), 4),
        "roc_auc_cv_std": round(float(cv_scores.std()), 4),
        "confusion_matrix": matrix,
        "confusion_matrix_labels": ["tn", "fp", "fn", "tp"],
        "coefficients": {name: round(value, 4) for name, value in coefficients.items()},
        "churn_rate_in_training_data": round(sum(labels) / len(labels), 4),
        "train_rows": len(x_train),
        "test_rows": len(x_test),
        "cutoff_date": cutoff.date().isoformat(),
        "label_window_days": context.cfg_int("inactive_days", 90),
        "roc_auc_note": (
            "holdout is a single 25% split; roc_auc_cv_mean is the 5-fold estimate "
            "and is the more reliable number on a few hundred rows"
        ),
    }

    # Features are computed at the cutoff but scored as of today, so every value
    # drifts by roughly the label window. A feature with little variance in
    # training (tenure, in a store whose customers all joined together) would
    # turn that drift into an enormous z-score and saturate the sigmoid. Storing
    # the training range and clipping to it at scoring time bounds that.
    ranges = {
        name: (
            min(row[index] for row in features),
            max(row[index] for row in features),
        )
        for index, name in enumerate(FEATURES)
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "pipeline": pipeline,
            "features": FEATURES,
            "version": MODEL_VERSION,
            "ranges": ranges,
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
                "estimator": "LogisticRegression",
                "class_weight": "balanced",
                "scaler": "StandardScaler",
                "random_state": RANDOM_STATE,
                "test_size": 0.25,
                "features": FEATURES,
            },
        )
    )
    db.flush()

    ranked = sorted(coefficients.items(), key=lambda item: abs(item[1]), reverse=True)
    logger.info(
        "Churn model for %s: ROC-AUC %.3f. Strongest signals: %s",
        context.store_name,
        metrics["roc_auc"],
        ", ".join(f"{name} {value:+.2f}" for name, value in ranked[:3]),
    )
    return metrics


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def score_store(db: Session, context: StoreContext) -> dict[str, Any]:
    """Score every customer with the store's trained model. Trains one if missing."""
    import joblib  # noqa: PLC0415

    path = model_path(context.store_id)
    if not path.exists():
        logger.info("No churn model for store %s yet, training one", context.store_id)
        train_store(db, context)

    artefact = joblib.load(path)
    pipeline = artefact["pipeline"]
    feature_names = artefact.get("features", FEATURES)

    now = utcnow()
    histories = _histories(db, context.store_id)
    rows = [
        (customer_id, _features_for(history, now))
        for customer_id, history in histories.items()
        if history.purchase_dates
    ]
    if not rows:
        return {"scored": 0, "model_version": artefact.get("version", MODEL_VERSION)}

    ranges = artefact.get("ranges") or {}
    matrix = [
        [_clip(values[name], ranges.get(name)) for name in feature_names]
        for _, values in rows
    ]
    probabilities = pipeline.predict_proba(matrix)[:, 1]

    existing = {
        score.customer_id: score
        for score in db.scalars(
            select(ChurnScore).where(ChurnScore.store_id == context.store_id)
        ).all()
    }
    bands = {"high": 0, "medium": 0, "low": 0}
    today = date.today()
    for (customer_id, _), probability in zip(rows, probabilities):
        band = risk_band(float(probability))
        bands[band] += 1
        score = existing.get(customer_id)
        if score is None:
            score = ChurnScore(store_id=context.store_id, customer_id=customer_id)
            db.add(score)
        score.probability = round(float(probability), 4)
        score.risk_level = band
        score.model_version = artefact.get("version", MODEL_VERSION)
        score.scored_at = today

    db.flush()
    return {"scored": len(rows), "model_version": MODEL_VERSION, "bands": bands}


def at_risk_customers(
    db: Session,
    store_id: int,
    *,
    exclude_inactive: bool = True,
    limit: int = 20,
    min_probability: float | None = None,
) -> list[dict[str, Any]]:
    """The riskiest customers who have NOT lapsed yet.

    That exclusion is the entire point of the model: an Inactive customer has
    already gone, and phase 1 could already find them with a date filter.

    The high band (0.7) is the headline number, but on a well separated model
    every customer above it may already have lapsed - which would leave the
    nightly run with nobody to contact and the model doing no work. So when the
    high band is empty of active customers, this falls back to the medium band.
    The list is always ordered riskiest first, so the fallback only ever adds
    people the model still considers at risk.
    """
    statement = (
        select(ChurnScore, Customer, Segment)
        .join(Customer, Customer.id == ChurnScore.customer_id)
        .outerjoin(
            Segment,
            (Segment.customer_id == ChurnScore.customer_id)
            & (Segment.store_id == ChurnScore.store_id),
        )
        .where(ChurnScore.store_id == store_id)
        .order_by(ChurnScore.probability.desc())
    )

    candidates: list[dict[str, Any]] = []
    for score, customer, segment in db.execute(statement).all():
        label = segment.segment if segment else None
        if exclude_inactive and label == "Inactive":
            continue
        candidates.append(
            {
                "customer_id": customer.id,
                "name": customer.name,
                "phone": customer.phone,
                "probability": float(score.probability),
                "risk_level": score.risk_level,
                "segment": label,
                "recency_days": segment.recency_days if segment else None,
                "total_spend": float(segment.total_spend) if segment else None,
                "model_version": score.model_version,
                "scored_at": score.scored_at,
            }
        )

    if min_probability is not None:
        return [row for row in candidates if row["probability"] >= min_probability][:limit]

    high = [row for row in candidates if row["probability"] >= HIGH_RISK]
    if high:
        return high[:limit]
    medium = [row for row in candidates if row["probability"] >= MEDIUM_RISK]
    if medium:
        logger.info(
            "Store %s: no active customer is above %.2f, falling back to the medium band",
            store_id,
            HIGH_RISK,
        )
    return medium[:limit]


def _clip(value: float, bounds: tuple[float, float] | None) -> float:
    """Keep a scoring feature inside the range the model was trained on."""
    if not bounds:
        return value
    low, high = bounds
    return max(float(low), min(float(high), float(value)))


def latest_run(db: Session, store_id: int) -> ModelRun | None:
    return db.scalar(
        select(ModelRun)
        .where(ModelRun.store_id == store_id, ModelRun.model_name == MODEL_NAME)
        .order_by(ModelRun.trained_at.desc())
        .limit(1)
    )
