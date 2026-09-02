"""Churn model: labels from history, no leakage, reproducible metrics."""
from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.agents import churn, segmentation
from app.models.agent import ChurnScore
from app.models.base import utcnow
from app.models.core import Customer, Transaction, TransactionItem
from app.models.ml import ModelRun
from app.verticals.context import resolve_store_context
from tests.test_segmentation import _catalog, _store

PHONES = iter(range(5_000_000, 9_000_000))


def _customer(db, store, name: str):
    customer = Customer(
        store_id=store.id,
        name=name,
        phone=f"9{next(PHONES):09d}",
        created_at=utcnow() - timedelta(days=500),
    )
    db.add(customer)
    db.flush()
    return customer


def _buy(db, store, customer, product, days_ago: int, amount: str = "500") -> None:
    transaction = Transaction(
        store_id=store.id,
        customer_id=customer.id,
        invoice_no=f"INV-{store.id:02d}-{customer.id:05d}-{days_ago:04d}",
        subtotal=Decimal(amount),
        discount=Decimal("0.00"),
        gst_amount=Decimal("0.00"),
        total=Decimal(amount),
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
            unit_price=Decimal(amount),
            line_discount=Decimal("0.00"),
            line_total=Decimal(amount),
        )
    )


def _populate(db, store, product, *, loyal: int = 45, lapsed: int = 35, seed: int = 7) -> None:
    """Two cohorts that differ in behaviour, not in what they spend.

    Both buy roughly monthly for similar amounts; the only real difference is
    when they stopped. That keeps the model honest - it has to learn recency and
    rhythm rather than latch onto a price tag the fixture accidentally encoded.
    """
    rng = random.Random(seed)

    def visits(customer, stop_at: int) -> None:
        days_ago = rng.randrange(400, 430)
        while days_ago > stop_at:
            _buy(db, store, customer, product, days_ago, amount=str(rng.randrange(300, 800)))
            days_ago -= rng.randrange(24, 38)

    # Real cohorts overlap: roughly one in six behaves against type. Without that
    # noise the two groups separate perfectly, the fitted weights blow up, and
    # the probabilities saturate - which teaches the test nothing.
    for index in range(loyal):
        customer = _customer(db, store, f"Loyal {index}")
        visits(customer, rng.randrange(100, 160) if rng.random() < 0.15 else rng.randrange(5, 25))

    for index in range(lapsed):
        customer = _customer(db, store, f"Lapsed {index}")
        visits(customer, rng.randrange(120, 200))
        if rng.random() < 0.15:
            _buy(db, store, customer, product, rng.randrange(5, 60), amount="400")

    db.commit()


@pytest.fixture()
def trained_store(db):
    """A store where most customers kept coming and a cohort quietly stopped."""
    store = _store(db, "pharmacy", "Jeevan Medical")     # inactive_days 90
    product = _catalog(db, store)
    _populate(db, store, product)
    context = resolve_store_context(db, store.id)
    return store, context


# -- bands and features ------------------------------------------------------
def test_risk_bands_follow_the_thresholds() -> None:
    assert churn.risk_band(0.95) == "high"
    assert churn.risk_band(0.70) == "high"
    assert churn.risk_band(0.69) == "medium"
    assert churn.risk_band(0.40) == "medium"
    assert churn.risk_band(0.39) == "low"


def test_features_ignore_everything_after_the_cutoff(db) -> None:
    """Rule 8: no post-cutoff data may reach a feature."""
    store = _store(db, "pharmacy", "Jeevan Medical")
    product = _catalog(db, store)
    customer = _customer(db, store, "Leak Test")
    for days_ago in (300, 200, 120):        # before a 90-day cutoff
        _buy(db, store, customer, product, days_ago)
    for days_ago in (30, 10, 2):            # after it - must be invisible
        _buy(db, store, customer, product, days_ago, amount="9999")
    db.commit()

    context = resolve_store_context(db, store.id)
    features, labels, cutoff, ids = churn.build_training_set(db, context)
    index = ids.index(customer.id)
    values = dict(zip(churn.FEATURES, features[index]))

    assert values["total_spend"] == 1500.0, "post-cutoff spend leaked into the features"
    assert values["recency_days"] == 28.0
    assert labels[index] == 0, "this customer did come back, so they are not churned"


def test_a_customer_who_never_returned_is_labelled_churned(db) -> None:
    store = _store(db, "pharmacy", "Jeevan Medical")
    product = _catalog(db, store)
    stayed = _customer(db, store, "Stayed")
    left = _customer(db, store, "Left")
    for days_ago in (300, 200, 120):
        _buy(db, store, stayed, product, days_ago)
        _buy(db, store, left, product, days_ago)
    _buy(db, store, stayed, product, 5)      # only one of them came back
    db.commit()

    context = resolve_store_context(db, store.id)
    _, labels, _, ids = churn.build_training_set(db, context)
    assert labels[ids.index(left.id)] == 1
    assert labels[ids.index(stayed.id)] == 0


# -- training ----------------------------------------------------------------
def test_training_reports_every_metric_and_records_the_run(trained_store, db) -> None:
    store, context = trained_store
    metrics = churn.train_store(db, context)
    db.commit()

    for key in ("accuracy", "precision", "recall", "roc_auc", "confusion_matrix", "coefficients"):
        assert key in metrics, f"{key} missing from the reported metrics"
    assert len(metrics["confusion_matrix"]) == 2
    assert set(metrics["coefficients"]) == set(churn.FEATURES)
    assert metrics["roc_auc"] > 0.75

    run = db.scalar(select(ModelRun).where(ModelRun.store_id == store.id))
    assert run is not None
    assert run.model_version == churn.MODEL_VERSION
    assert run.params["random_state"] == churn.RANDOM_STATE
    assert run.rows_trained == 80
    assert churn.model_path(store.id).exists()


def test_retraining_the_same_data_gives_identical_metrics(trained_store, db) -> None:
    """Rule 9: fixed seed, reproducible result."""
    _, context = trained_store
    first = churn.train_store(db, context)
    second = churn.train_store(db, context)
    db.commit()
    assert first == second


def test_scoring_writes_bands_and_a_model_version(trained_store, db) -> None:
    store, context = trained_store
    churn.train_store(db, context)
    result = churn.score_store(db, context)
    db.commit()

    assert result["scored"] == 80
    scores = db.scalars(select(ChurnScore).where(ChurnScore.store_id == store.id)).all()
    assert len(scores) == 80
    for score in scores:
        assert 0.0 <= score.probability <= 1.0
        assert score.risk_level in {"high", "medium", "low"}
        assert score.model_version == churn.MODEL_VERSION
    assert any(score.risk_level == "high" for score in scores)


def test_scoring_without_a_trained_model_trains_one(trained_store, db) -> None:
    store, context = trained_store
    path = churn.model_path(store.id)
    if path.exists():
        path.unlink()
    result = churn.score_store(db, context)
    db.commit()
    assert result["scored"] > 0
    assert path.exists()


def test_a_store_with_no_history_fails_with_a_useful_message(db) -> None:
    from app.services.errors import ValidationError

    store = _store(db, "pharmacy", "Empty Shop")
    context = resolve_store_context(db, store.id)
    with pytest.raises(ValidationError) as excinfo:
        churn.train_store(db, context)
    assert "Empty Shop" in str(excinfo.value)


# -- the point of the model --------------------------------------------------
def test_at_risk_excludes_customers_who_have_already_lapsed(trained_store, db) -> None:
    store, context = trained_store
    churn.train_store(db, context)
    churn.score_store(db, context)
    segmentation.rebuild(db, context)
    db.commit()

    including = churn.at_risk_customers(db, store.id, exclude_inactive=False, limit=100)
    excluding = churn.at_risk_customers(db, store.id, exclude_inactive=True, limit=100)

    assert including, "the fixture should produce some at-risk customers"
    assert all(row["segment"] != "Inactive" for row in excluding)
    assert len(excluding) <= len(including)
    probabilities = [row["probability"] for row in excluding]
    assert probabilities == sorted(probabilities, reverse=True), "riskiest first"


def test_the_action_list_falls_back_to_the_medium_band_when_every_high_risk_customer_has_gone(
    trained_store, db
) -> None:
    """A model that separates cleanly can put every high-risk name in Inactive.

    The nightly run would then have nobody to contact, which is the opposite of
    the point, so the source falls back to the medium band.
    """
    store, context = trained_store
    churn.train_store(db, context)
    churn.score_store(db, context)
    segmentation.rebuild(db, context)
    db.commit()

    rows = churn.at_risk_customers(db, store.id, exclude_inactive=True, limit=100)
    assert rows, "the fallback must find somebody still worth contacting"
    assert all(row["probability"] >= churn.MEDIUM_RISK for row in rows)
    assert all(row["segment"] != "Inactive" for row in rows)


# -- the API -----------------------------------------------------------------
def test_train_and_read_scores_over_http(client, trained_store) -> None:
    store, _ = trained_store

    trained = client.post(f"/ml/churn/train?store_id={store.id}")
    assert trained.status_code == 200, trained.text
    body = trained.json()
    assert body["metrics"]["roc_auc"] > 0.75
    assert body["scored"] == 80
    assert sum(body["bands"].values()) == 80

    scores = client.get(f"/ml/churn/scores?store_id={store.id}&limit=10").json()
    assert len(scores) == 10
    probabilities = [row["probability"] for row in scores]
    assert probabilities == sorted(probabilities, reverse=True), "default sort is riskiest first"

    high = client.get(f"/ml/churn/scores?store_id={store.id}&risk=high&limit=100").json()
    assert all(row["risk_level"] == "high" for row in high)

    run = client.get(f"/ml/churn/latest-run?store_id={store.id}").json()
    assert run["model_name"] == churn.MODEL_NAME
    assert "coefficients" in run["metrics"]


def test_latest_run_before_training_is_404(client, db) -> None:
    store = _store(db, "pharmacy", "Untrained Shop")
    assert client.get(f"/ml/churn/latest-run?store_id={store.id}").status_code == 404


def test_high_risk_customers_who_have_not_lapsed_get_a_winback(client, rules) -> None:
    """The whole point: contact them before they are written off."""
    db = rules
    store = _store(db, "pharmacy", "Jeevan Medical")
    product = _catalog(db, store)

    _populate(db, store, product)
    # Still Regular by recency, but the gaps between visits keep stretching.
    fading = _customer(db, store, "Fading Regular")
    for days_ago in (400, 330, 250, 170, 100, 60):
        _buy(db, store, fading, product, days_ago, amount="450")
    db.commit()

    context = resolve_store_context(db, store.id)
    churn.train_store(db, context)
    churn.score_store(db, context)
    segmentation.rebuild(db, context)
    db.commit()

    at_risk = churn.at_risk_customers(db, store.id, exclude_inactive=True, limit=50)
    assert at_risk, "no pre-lapse customer was flagged, the wiring has nothing to act on"
    assert all(row["segment"] != "Inactive" for row in at_risk)

    queued = client.post(f"/ml/churn/queue-winback?store_id={store.id}").json()
    assert queued["queued"] > 0

    from app.models.agent import Reminder, Segment

    rows = db.execute(
        select(Reminder, Segment)
        .join(Segment, Segment.customer_id == Reminder.customer_id)
        .where(Reminder.store_id == store.id, Reminder.kind == "winback")
    ).all()
    assert any(
        segment.segment != "Inactive" for _, segment in rows
    ), "every win-back went to an already-lapsed customer; the model added nothing"
