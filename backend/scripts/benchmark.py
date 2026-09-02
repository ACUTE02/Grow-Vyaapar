"""Time the queries the app actually runs, on the seeded database.

    python -m scripts.benchmark            # measure
    python -m scripts.benchmark --json     # machine readable

Run it before and after a migration that adds indexes and paste both tables into
the report. A number without a baseline is not a result.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from typing import Any, Callable

from sqlalchemy import func, inspect, select, text

from app.agents import insights as insight_agent
from app.agents import segmentation
from app.db import SessionLocal, engine
from app.models.agent import Reminder, Segment
from app.models.core import Product, StockLevel, Transaction
from app.services import customer_service, stock_service
from app.verticals.context import resolve_store_context

REPEATS = 5


def timed(label: str, call: Callable[[], Any], repeats: int = REPEATS) -> dict[str, Any]:
    call()                                   # warm the connection and the caches
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        result = call()
        samples.append((time.perf_counter() - start) * 1000)
    size = len(result) if hasattr(result, "__len__") else 1
    return {
        "query": label,
        "median_ms": round(statistics.median(samples), 2),
        "min_ms": round(min(samples), 2),
        "max_ms": round(max(samples), 2),
        "rows": size,
    }


def measurements(store_id: int = 1) -> list[dict[str, Any]]:
    results = []
    with SessionLocal() as db:
        context = resolve_store_context(db, store_id)

        results.append(
            timed(
                "customer list (50, with segment and spend)",
                lambda: customer_service.search_customers(db, context, limit=50),
            )
        )
        results.append(
            timed(
                "customer search by name fragment",
                lambda: customer_service.search_customers(db, context, query="Sharma", limit=50),
            )
        )
        results.append(
            timed(
                "outbox (100 queued reminders with customer)",
                lambda: db.execute(
                    select(Reminder)
                    .where(Reminder.store_id == store_id, Reminder.status == "queued")
                    .limit(100)
                ).all(),
            )
        )
        results.append(
            timed(
                "segment distribution",
                lambda: segmentation.distribution(db, store_id),
            )
        )
        results.append(
            timed(
                "dead stock list",
                lambda: stock_service.dead_stock(db, context, limit=50),
            )
        )
        results.append(
            timed(
                "sales in a 30 day window",
                lambda: db.execute(
                    select(func.count(Transaction.id), func.sum(Transaction.total)).where(
                        Transaction.store_id == store_id,
                        Transaction.status == "completed",
                        Transaction.created_at >= text("date('now', '-30 day')")
                        if engine.dialect.name == "sqlite"
                        else Transaction.created_at,
                    )
                ).first(),
            )
        )
        results.append(
            timed(
                "dashboard metrics (the whole insight input)",
                lambda: insight_agent.compute_metrics(db, context),
                repeats=3,
            )
        )
        results.append(
            timed(
                "stock join for the catalog page",
                lambda: db.execute(
                    select(Product, StockLevel)
                    .outerjoin(StockLevel, StockLevel.product_id == Product.id)
                    .where(Product.store_id == store_id)
                    .limit(100)
                ).all(),
            )
        )
    return results


def index_summary() -> list[str]:
    inspector = inspect(engine)
    names = []
    for table in sorted(inspector.get_table_names()):
        for index in inspector.get_indexes(table):
            names.append(f"{table}.{index['name']}")
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description="Time the app's real queries")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--store", type=int, default=1)
    args = parser.parse_args()

    rows = measurements(args.store)
    indexes = index_summary()

    if args.json:
        print(json.dumps({"queries": rows, "indexes": indexes}, indent=2))
        return

    print(f"{len(indexes)} indexes on the database\n")
    header = f"{'query':<48}{'median ms':>11}{'min':>9}{'max':>9}{'rows':>8}"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['query']:<48}{row['median_ms']:>11}{row['min_ms']:>9}"
            f"{row['max_ms']:>9}{row['rows']:>8}"
        )
    print(f"\ntotal median: {round(sum(row['median_ms'] for row in rows), 2)} ms")


if __name__ == "__main__":
    main()
