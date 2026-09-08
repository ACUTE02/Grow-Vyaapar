"""Model endpoints: train, inspect and act on churn scores."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import churn as churn_agent
from app.agents import forecasting as forecast_agent
from app.db import get_db
from app.models.agent import ChurnScore, Segment
from app.models.core import Customer
from app.schemas.ml import (
    ChurnScoreOut,
    ChurnTrainOut,
    ForecastRunOut,
    ModelRunOut,
    QueueWinbackOut,
    StockForecastOut,
    StockForecastTrainOut,
)
from app.services.errors import NotFoundError
from app.verticals.context import StoreContext, get_store_context_from_query

router = APIRouter(prefix="/ml", tags=["ml"])


@router.post("/churn/train", response_model=ChurnTrainOut)
def train_churn(
    score_after: bool = Query(default=True, description="score every customer after training"),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    metrics = churn_agent.train_store(db, context)
    scored = churn_agent.score_store(db, context) if score_after else {"scored": 0}
    db.commit()
    return {
        "store_id": context.store_id,
        "model_name": churn_agent.MODEL_NAME,
        "model_version": churn_agent.MODEL_VERSION,
        "metrics": metrics,
        "scored": int(scored.get("scored", 0)),
        "bands": scored.get("bands", {}),
    }


@router.post("/churn/score", response_model=ChurnTrainOut)
def score_churn(
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    """Score with the stored model. Trains one first if the store has none."""
    scored = churn_agent.score_store(db, context)
    db.commit()
    run = churn_agent.latest_run(db, context.store_id)
    return {
        "store_id": context.store_id,
        "model_name": churn_agent.MODEL_NAME,
        "model_version": scored.get("model_version", churn_agent.MODEL_VERSION),
        "metrics": run.metrics if run else {},
        "scored": int(scored.get("scored", 0)),
        "bands": scored.get("bands", {}),
    }


@router.get("/churn/scores", response_model=list[ChurnScoreOut])
def churn_scores(
    risk: str | None = Query(default=None, description="high | medium | low"),
    exclude_inactive: bool = Query(
        default=False, description="hide customers already written off as Inactive"
    ),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="probability", pattern="^(probability|recency|name)$"),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = (
        select(ChurnScore, Customer, Segment)
        .join(Customer, Customer.id == ChurnScore.customer_id)
        .outerjoin(
            Segment,
            (Segment.customer_id == ChurnScore.customer_id)
            & (Segment.store_id == ChurnScore.store_id),
        )
        .where(ChurnScore.store_id == context.store_id)
    )
    if risk:
        statement = statement.where(ChurnScore.risk_level == risk)
    if exclude_inactive:
        statement = statement.where(
            (Segment.segment.is_(None)) | (Segment.segment != "Inactive")
        )
    order = {
        "probability": ChurnScore.probability.desc(),
        "recency": Segment.recency_days.desc(),
        "name": Customer.name.asc(),
    }[sort]
    statement = statement.order_by(order).limit(limit).offset(offset)

    return [
        {
            "customer_id": customer.id,
            "name": customer.name,
            "phone": customer.phone,
            "probability": float(score.probability),
            "risk_level": score.risk_level,
            "segment": segment.segment if segment else None,
            "recency_days": segment.recency_days if segment else None,
            "total_spend": float(segment.total_spend) if segment else None,
            "model_version": score.model_version,
            "scored_at": score.scored_at,
        }
        for score, customer, segment in db.execute(statement).all()
    ]


@router.get("/churn/at-risk", response_model=list[ChurnScoreOut])
def at_risk(
    limit: int = Query(default=20, ge=1, le=200),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    """High risk but not yet Inactive - the customers still worth contacting."""
    return churn_agent.at_risk_customers(db, context.store_id, limit=limit)


@router.post("/churn/queue-winback", response_model=QueueWinbackOut)
def queue_winback(
    limit: int = Query(default=20, ge=1, le=200),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    """Draft win-back messages for at-risk customers through the normal rule path."""
    from app.agents import reminders as reminder_agent  # noqa: PLC0415

    created = reminder_agent.run(
        db, context, kinds=["winback"], max_per_kind=limit, llm_budget=1
    )
    db.commit()
    return {
        "store_id": context.store_id,
        "queued": int(created.get("winback", 0)),
    }


@router.get("/runs", response_model=list[ModelRunOut])
def model_runs(
    limit: int = Query(default=10, ge=1, le=100),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    from app.models.ml import ModelRun  # noqa: PLC0415

    rows = db.scalars(
        select(ModelRun)
        .where(ModelRun.store_id == context.store_id)
        .order_by(ModelRun.trained_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": run.id,
            "model_name": run.model_name,
            "model_version": run.model_version,
            "trained_at": run.trained_at,
            "rows_trained": run.rows_trained,
            "metrics": run.metrics,
            "params": run.params,
        }
        for run in rows
    ]


@router.get("/churn/latest-run", response_model=ModelRunOut)
def latest_run(
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    run = churn_agent.latest_run(db, context.store_id)
    if run is None:
        raise NotFoundError(
            f"No churn model has been trained for {context.store_name} yet. "
            "Train one from the dashboard or POST /ml/churn/train."
        )
    return {
        "id": run.id,
        "model_name": run.model_name,
        "model_version": run.model_version,
        "trained_at": run.trained_at,
        "rows_trained": run.rows_trained,
        "metrics": run.metrics,
        "params": run.params,
    }


# -- stock intelligence ------------------------------------------------------
@router.get("/forecast/stock", response_model=list[StockForecastOut])
def forecast_stock(
    view: str = Query(
        default="all", pattern="^(all|reorder|dead_risk)$",
        description="all | reorder (runs out inside the cycle) | dead_risk",
    ),
    limit: int = Query(default=50, ge=1, le=500),
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Velocity, days to stockout and a reorder quantity, per product."""
    if view == "reorder":
        rows = forecast_agent.reorder_list(db, context, limit=limit)
    elif view == "dead_risk":
        rows = forecast_agent.dead_stock_risk(db, context, limit=limit)
    else:
        rows = forecast_agent.compute(db, context)[:limit]
    return [asdict(row) for row in rows]


@router.post("/forecast/run", response_model=ForecastRunOut)
def forecast_run(
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    result = forecast_agent.run(db, context)
    db.commit()
    return result


@router.post("/stock_forecast/train", response_model=StockForecastTrainOut)
def train_stock_forecast(
    context: StoreContext = Depends(get_store_context_from_query),
    db: Session = Depends(get_db),
) -> dict:
    from app.ml import stock_forecast_model  # noqa: PLC0415

    metrics = stock_forecast_model.train_store(db, context)
    db.commit()
    return {
        "store_id": context.store_id,
        "model_name": stock_forecast_model.MODEL_NAME,
        "model_version": stock_forecast_model.MODEL_VERSION,
        "metrics": metrics,
    }
