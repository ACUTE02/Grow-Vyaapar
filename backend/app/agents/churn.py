"""Churn scoring - phase 2.

The table exists and stays empty in this phase. The stub keeps the interface
the scheduler and the dashboard will call, so adding the model later is a
one-file change.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.verticals.context import StoreContext

logger = logging.getLogger(__name__)

MODEL_VERSION = "not-trained"


def score_store(db: Session, context: StoreContext) -> dict[str, int]:
    """Deliberately does nothing yet. Phase 2 fills churn_scores."""
    logger.info(
        "Churn scoring is not part of this phase; store %s left unscored", context.store_id
    )
    return {"scored": 0, "model_version": MODEL_VERSION}
