"""Nightly job, in process. No broker, no worker, no second deployable.

    python scheduler.py            # run the loop, fires at 02:00 Asia/Kolkata
    python scheduler.py --now      # run the whole nightly pass once and exit

It calls exactly the same functions the manual endpoints call, so nothing can
drift between the button and the cron.
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select

from app.agents import attribution as attribution_agent
from app.agents import forecasting as forecast_agent
from app.agents import insights as insight_agent
from app.agents import reminders as reminder_agent
from app.agents import churn as churn_agent
from app.agents import segmentation as segmentation_agent
from app.db import SessionLocal
from app.models.config import Store
from app.services import finance_rollup
from app.settings import settings
from app.verticals.context import resolve_store_context

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("scheduler")


def nightly_pass() -> dict[str, dict]:
    """One pass per store: roll up finance, resegment, rescore churn, forecast
    stock, run the reminder rules, attribute campaigns and refresh insights.

    It never sends anything. Delivery stays an explicit human action (rule 10).
    """
    report: dict[str, dict] = {}
    with SessionLocal() as db:
        store_ids = list(db.scalars(select(Store.id).order_by(Store.id)).all())

    for store_id in store_ids:
        with SessionLocal() as db:
            try:
                context = resolve_store_context(db, store_id)
                today = date.today()
                days = finance_rollup.rebuild_daily_summary(
                    db, store_id, today - timedelta(days=45), today
                )
                distribution = segmentation_agent.rebuild(db, context)
                created = reminder_agent.run(db, context)
                forecast = forecast_agent.run(db, context)
                churn_agent.score_store(db, context)
                attribution = attribution_agent.run(db, context)
                _, source = insight_agent.generate(db, context, force=True)
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Nightly pass failed for store %s", store_id)
                report[str(store_id)] = {"error": "see log"}
                continue

        report[str(store_id)] = {
            "store": context.store_name,
            "summary_days": len(days),
            "segments": distribution,
            "reminders": created,
            "forecasts": forecast["products"],
            "reorder_soon": forecast["reorder_soon"],
            "campaigns_attributed": attribution["campaigns"],
            "insights": source,
        }
        logger.info("Nightly pass done for %s: %s", context.store_name, report[str(store_id)])

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="LocalAI OS nightly scheduler")
    parser.add_argument("--now", action="store_true", help="run one pass and exit")
    args = parser.parse_args()

    if args.now:
        for store_id, result in nightly_pass().items():
            print(f"store {store_id}: {result}")
        return

    scheduler = BlockingScheduler(timezone=settings.timezone)
    scheduler.add_job(
        nightly_pass,
        "cron",
        hour=settings.scheduler_hour,
        minute=settings.scheduler_minute,
        id="nightly",
        misfire_grace_time=3600,
    )
    logger.info(
        "Scheduler started: nightly at %02d:%02d %s. Ctrl+C to stop.",
        settings.scheduler_hour,
        settings.scheduler_minute,
        settings.timezone,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
