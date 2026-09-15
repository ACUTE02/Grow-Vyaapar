"""Deterministic demo data: three stores, three verticals, 18 months of trading.

    python -m scripts.seed

Re-running wipes and rebuilds every row with the same fixed random seed, so two
runs produce byte-identical data. The edge cases the demo depends on - lapsed
customers, dead stock, big spenders - are seeded deliberately, per store, using
that store's own thresholds.
"""
from __future__ import annotations

import argparse
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.orm import Session

from app.db import SessionLocal, engine
from app.models.admin import AuditLog, PurchaseItem, PurchaseOrder, Supplier, User
from app.models.agent import Campaign, ChurnScore, Insight, Reminder, Segment
from app.models.commerce import (
    CampaignStat,
    Coupon,
    CouponRedemption,
    LoyaltyAccount,
    LoyaltyLedger,
    Referral,
)
from app.models.ml import LlmCache, ModelRun, StockForecast
from app.models.config import MessageTemplate, ReminderRule, Store, StoreConfig, Vertical
from app.models.core import (
    Batch,
    Customer,
    CustomerRecord,
    DailySalesSummary,
    Job,
    Product,
    ProductCategory,
    StockLevel,
    Transaction,
    TransactionItem,
)
from app.services.billing_service import LineInput, compute_totals, money
from app.services.finance_rollup import rebuild_daily_summary
from app.verticals.loader import load_verticals
from scripts.catalog_data import (
    BRANDS,
    CATALOG,
    COLOURS,
    COMPOSITIONS,
    FABRICS,
    FIRST_NAMES,
    GENERIC_TEMPLATES,
    LAST_NAMES,
    PACK_SIZES,
    REMINDER_RULES,
    RHYTHM,
    SEASONS,
    SIZES,
    STORES,
    TEMPLATE_OVERRIDES,
)

SEED = 42
MONTHS_OF_HISTORY = 18
CUSTOMERS_PER_STORE = 300
PRODUCTS_PER_STORE = 150
LAPSED_CUSTOMERS = 40
DEAD_SKUS = 12
SLOW_SKUS = 20
VIP_CUSTOMERS = 3
NEW_CUSTOMERS = 25

HOUR_WEIGHTS = {
    9: 0.6, 10: 1.0, 11: 1.1, 12: 1.0, 13: 0.7, 14: 0.6,
    15: 0.8, 16: 1.0, 17: 1.5, 18: 2.0, 19: 2.2, 20: 1.8, 21: 1.0,
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def wipe(db: Session) -> None:
    """Empty every table except verticals, which are upserted by the loader."""
    for model in (
        AuditLog, CouponRedemption, Coupon, CampaignStat,
        LoyaltyLedger, LoyaltyAccount, Referral,
        PurchaseItem, PurchaseOrder, Supplier, User,
        StockForecast, ModelRun, LlmCache,
        ChurnScore, Insight, Campaign, Reminder, Segment,
        DailySalesSummary, Job, TransactionItem, Transaction,
        Batch, StockLevel, Product, ProductCategory,
        CustomerRecord, Customer,
        MessageTemplate, ReminderRule, StoreConfig, Store,
    ):
        db.execute(delete(model))
    db.flush()
    if engine.dialect.name == "sqlite":
        # Reset any AUTOINCREMENT counters so ids are identical on every run.
        # The table only exists once SQLite has seen an AUTOINCREMENT column.
        exists = db.execute(
            text("SELECT count(*) FROM sqlite_master WHERE name = 'sqlite_sequence'")
        ).scalar()
        if exists:
            db.execute(text("DELETE FROM sqlite_sequence WHERE name != 'verticals'"))
    db.flush()


def phone_pool(rng: random.Random, count: int) -> list[str]:
    seen: set[str] = set()
    numbers: list[str] = []
    while len(numbers) < count:
        candidate = f"{rng.choice('6789')}{rng.randrange(10**8, 10**9):09d}"[:10]
        if candidate in seen:
            continue
        seen.add(candidate)
        numbers.append(candidate)
    return numbers


def pick_datetime(
    rng: random.Random, start: date, end: date, month_weights: dict[int, float]
) -> datetime:
    """A trading moment: weighted to festive months, weekends and evenings."""
    span = max((end - start).days, 1)
    best_weight = max(month_weights.values()) * 1.6
    for _ in range(40):
        day = start + timedelta(days=rng.randrange(span))
        weight = month_weights.get(day.month, 1.0) * (1.6 if day.weekday() >= 5 else 1.0)
        if rng.random() <= weight / best_weight:
            break
    hours = list(HOUR_WEIGHTS)
    hour = rng.choices(hours, weights=[HOUR_WEIGHTS[h] for h in hours], k=1)[0]
    return datetime.combine(day, time(hour, rng.randrange(60), rng.randrange(60)))


def product_attributes(rng: random.Random, vertical_code: str, name: str) -> dict:
    """Attributes that satisfy the vertical's product_schema."""
    if vertical_code == "grocery":
        return {
            "brand": rng.choice(BRANDS),
            "pack_size": rng.choice(PACK_SIZES),
            "unit": rng.choice(["kg", "g", "litre", "packet"]),
        }
    if vertical_code == "pharmacy":
        expiry = date.today() + timedelta(days=rng.randrange(90, 900))
        return {
            "composition": rng.choice(COMPOSITIONS),
            "batch_no": f"B{rng.randrange(10000, 99999)}",
            "expiry_date": expiry.isoformat(),
            "schedule_h": rng.random() < 0.2,
        }
    if vertical_code == "apparel":
        return {
            "size": rng.choice(SIZES),
            "colour": rng.choice(COLOURS),
            "fabric": rng.choice(FABRICS),
            "season": rng.choice(SEASONS),
        }
    return {}


# --------------------------------------------------------------------------- #
# configuration rows
# --------------------------------------------------------------------------- #
def seed_rules_and_templates(db: Session) -> None:
    verticals = {v.code: v for v in db.scalars(select(Vertical)).all()}

    rule_rows: list[dict] = []
    template_rows: list[dict] = []
    rule_id = 0
    template_id = 0
    seen_templates: set[str] = set()

    for rule in REMINDER_RULES:
        for code in rule["verticals"]:
            vertical = verticals.get(code)
            if vertical is None:
                continue
            template_key = f"{code}.{rule['kind']}"
            rule_id += 1
            rule_rows.append(
                {
                    "id": rule_id,
                    "vertical_id": vertical.id,
                    "kind": rule["kind"],
                    "signal": rule["signal"],
                    "offset_days": rule["offset_days"],
                    "template_key": template_key,
                    "channel": rule["channel"],
                    "enabled": True,
                }
            )
            if template_key in seen_templates:
                continue
            seen_templates.add(template_key)
            body, instruction = TEMPLATE_OVERRIDES.get(
                (code, rule["kind"]), GENERIC_TEMPLATES[rule["kind"]]
            )
            template_id += 1
            template_rows.append(
                {
                    "id": template_id,
                    "template_key": template_key,
                    "language": "en",
                    "body": body,
                    "llm_instruction": instruction,
                }
            )

    db.execute(insert(ReminderRule), rule_rows)
    db.execute(insert(MessageTemplate), template_rows)
    db.flush()
    print(f"  reminder_rules: {len(rule_rows)}   message_templates: {len(template_rows)}")


# --------------------------------------------------------------------------- #
# per-store data
# --------------------------------------------------------------------------- #
def seed_store(db: Session, rng: random.Random, store: Store, vertical: Vertical) -> dict:
    code = vertical.code
    config = vertical.default_config
    rhythm = RHYTHM[code]
    today = date.today()
    history_start = today - timedelta(days=MONTHS_OF_HISTORY * 30)
    inactive_days = int(config["inactive_days"])
    dead_stock_days = int(config["dead_stock_days"])
    lapse_end = today - timedelta(days=inactive_days + 15)

    # -- customers ----------------------------------------------------------
    base_id = (store.id - 1) * 100000
    phones = phone_pool(rng, CUSTOMERS_PER_STORE)
    customer_rows: list[dict] = []
    for index in range(CUSTOMERS_PER_STORE):
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        created = pick_datetime(rng, history_start, today, rhythm["month_weights"])
        customer_rows.append(
            {
                "id": base_id + index + 1,
                "store_id": store.id,
                "name": name,
                "phone": phones[index],
                "dob": date(
                    rng.randrange(1955, 2008), rng.randrange(1, 13), rng.randrange(1, 29)
                ),
                "anniversary": (
                    date(rng.randrange(1985, 2023), rng.randrange(1, 13), rng.randrange(1, 29))
                    if rng.random() < 0.45
                    else None
                ),
                "family_head_id": None,
                "notes": None,
                "created_at": created,
            }
        )
    db.execute(insert(Customer), customer_rows)

    # -- categories and products -------------------------------------------
    categories = CATALOG[code]
    category_rows: list[dict] = []
    for offset, category_name in enumerate(categories):
        category_rows.append(
            {
                "id": base_id + offset + 1,
                "store_id": store.id,
                "name": category_name,
                "parent_id": None,
            }
        )
    db.execute(insert(ProductCategory), category_rows)
    category_ids = {row["name"]: row["id"] for row in category_rows}

    product_rows: list[dict] = []
    stock_rows: list[dict] = []
    product_index = 0
    while len(product_rows) < PRODUCTS_PER_STORE:
        for category_name, spec in categories.items():
            if len(product_rows) >= PRODUCTS_PER_STORE:
                break
            item = spec["items"][product_index % len(spec["items"])]
            variant = product_index // len(spec["items"]) + 1
            product_index += 1
            low, high = spec["price"]
            sell = Decimal(str(round(rng.uniform(low, high), 2)))
            cost = money(sell * Decimal(str(round(rng.uniform(0.55, 0.8), 2))))
            pid = base_id + len(product_rows) + 1
            product_rows.append(
                {
                    "id": pid,
                    "store_id": store.id,
                    "sku": f"{spec['prefix']}-{len(product_rows) + 1001}",
                    "name": f"{item} {variant}" if variant > 1 else item,
                    "category_id": category_ids[category_name],
                    "hsn_code": str(1000 + (pid % 8000)),
                    "cost_price": cost,
                    "sell_price": money(sell),
                    "gst_rate": Decimal(str(spec["gst"])),
                    "attributes": product_attributes(rng, code, item),
                    "image_url": None,
                    "is_active": True,
                }
            )
    db.execute(insert(Product), product_rows)

    # The tail of the catalog never sells: DEAD_SKUS sit far past every window,
    # SLOW_SKUS sit at a spread of ages so each store's own window catches a
    # different number of them.
    sellable = product_rows[: -(DEAD_SKUS + SLOW_SKUS)]
    slow = product_rows[-(DEAD_SKUS + SLOW_SKUS) : -DEAD_SKUS]
    dead = product_rows[-DEAD_SKUS:]
    slow_age = {
        row["id"]: 35 + index * 6 for index, row in enumerate(slow)
    }
    price_of = {row["id"]: row["sell_price"] for row in product_rows}
    gst_of = {row["id"]: row["gst_rate"] for row in product_rows}
    products_by_category: dict[int, list[int]] = {}
    for row in sellable:
        products_by_category.setdefault(row["category_id"], []).append(row["id"])

    # -- transactions -------------------------------------------------------
    txn_rows: list[dict] = []
    item_rows: list[dict] = []
    last_sold: dict[int, datetime] = {}
    txn_id = base_id
    item_id = base_id
    basket_low, basket_high = rhythm["basket"]
    qty_low, qty_high = rhythm["line_qty"]

    for index, customer in enumerate(customer_rows):
        if index < LAPSED_CUSTOMERS:
            visits = rng.randrange(3, 10)
            window = (history_start, lapse_end)
            basket_boost = 1
        elif index < LAPSED_CUSTOMERS + VIP_CUSTOMERS:
            visits = rng.randrange(42, 60)
            window = (history_start, today)
            basket_boost = 2
        elif index >= CUSTOMERS_PER_STORE - NEW_CUSTOMERS:
            visits = 1
            window = (today - timedelta(days=25), today)
            basket_boost = 1
        else:
            visits = rng.randrange(8, 24)
            window = (history_start, today)
            basket_boost = 1

        home_categories = rng.sample(
            list(products_by_category), k=min(2, len(products_by_category))
        )

        for _ in range(visits):
            stamp = pick_datetime(rng, window[0], window[1], rhythm["month_weights"])
            size = rng.randrange(basket_low, basket_high + 1) * basket_boost
            chosen: list[int] = []
            for _ in range(size):
                if rng.random() < rhythm["category_loyalty"]:
                    pool = products_by_category[rng.choice(home_categories)]
                else:
                    pool = products_by_category[rng.choice(list(products_by_category))]
                chosen.append(rng.choice(pool))

            lines: list[LineInput] = []
            for product_id in dict.fromkeys(chosen):
                line_qty = Decimal(rng.randrange(qty_low, qty_high + 1))
                lines.append(
                    LineInput(
                        product_id=product_id,
                        qty=line_qty,
                        unit_price=Decimal(str(price_of[product_id])),
                        line_discount=Decimal("0.00"),
                        gst_rate=Decimal(str(gst_of[product_id])),
                    )
                )
            gross = sum(
                (Decimal(str(line.qty)) * Decimal(str(line.unit_price)) for line in lines),
                Decimal("0"),
            )
            discount = (
                money(gross * Decimal(str(round(rng.uniform(0.03, 0.15), 3))))
                if rng.random() < rhythm["discount_chance"]
                else Decimal("0.00")
            )
            totals = compute_totals(lines, discount)

            txn_id += 1
            txn_rows.append(
                {
                    "id": txn_id,
                    "store_id": store.id,
                    "customer_id": customer["id"],
                    "invoice_no": f"INV-{store.id:02d}-{txn_id - base_id:05d}",
                    "subtotal": totals.subtotal,
                    "discount": totals.discount,
                    "gst_amount": totals.gst_amount,
                    "total": totals.total,
                    "payment_mode": rng.choices(
                        ["cash", "upi", "card"], weights=[0.4, 0.5, 0.1], k=1
                    )[0],
                    "status": "completed",
                    "created_at": stamp,
                }
            )
            for line in totals.lines:
                item_id += 1
                item_rows.append(
                    {
                        "id": item_id,
                        "transaction_id": txn_id,
                        "product_id": line.product_id,
                        "qty": line.qty,
                        "unit_price": line.unit_price,
                        "line_discount": line.line_discount,
                        "line_total": line.line_total,
                    }
                )
                if line.product_id not in last_sold or last_sold[line.product_id] < stamp:
                    last_sold[line.product_id] = stamp

    # Invoice numbers must run in date order for a believable ledger.
    txn_rows.sort(key=lambda row: row["created_at"])
    for sequence, row in enumerate(txn_rows, start=1):
        row["invoice_no"] = f"INV-{store.id:02d}-{sequence:05d}"
    db.execute(insert(Transaction), txn_rows)
    for chunk_start in range(0, len(item_rows), 2000):
        db.execute(insert(TransactionItem), item_rows[chunk_start : chunk_start + 2000])

    # -- stock --------------------------------------------------------------
    dead_stamp = datetime.combine(today - timedelta(days=dead_stock_days + 20), time(11, 0))
    for position, row in enumerate(product_rows):
        pid = row["id"]
        is_dead = row in dead
        slow_days = slow_age.get(pid)
        reorder_point = Decimal(rng.randrange(4, 20))
        if position < 10:                      # a visible low-stock list on day one
            on_hand = Decimal(rng.randrange(0, int(reorder_point)))
        else:
            on_hand = Decimal(rng.randrange(int(reorder_point) + 2, 140))
        stock_rows.append(
            {
                "id": pid,
                "product_id": pid,
                "qty_on_hand": on_hand,
                "reorder_point": reorder_point,
                "last_received_at": datetime.combine(
                    today - timedelta(days=rng.randrange(1, 60)), time(10, 0)
                ),
                "last_sold_at": (
                    dead_stamp
                    if is_dead
                    else datetime.combine(today - timedelta(days=slow_days), time(12, 0))
                    if slow_days is not None
                    else last_sold.get(pid)
                ),
            }
        )
    db.execute(insert(StockLevel), stock_rows)

    # -- optional, feature-flagged extras ------------------------------------
    flags = vertical.feature_flags or {}
    if flags.get("expiry"):
        batch_rows = [
            {
                "id": base_id + i + 1,
                "product_id": row["id"],
                "batch_no": f"B{rng.randrange(10000, 99999)}",
                "expiry_date": today + timedelta(days=rng.randrange(20, 720)),
                "qty": Decimal(rng.randrange(5, 60)),
            }
            for i, row in enumerate(product_rows[:60])
        ]
        db.execute(insert(Batch), batch_rows)

    if flags.get("jobs"):
        job_rows = []
        for i in range(25):
            customer = customer_rows[rng.randrange(LAPSED_CUSTOMERS, CUSTOMERS_PER_STORE)]
            status = rng.choices(
                ["pending", "in_progress", "ready", "delivered"],
                weights=[0.2, 0.2, 0.35, 0.25],
                k=1,
            )[0]
            promised = today + timedelta(days=rng.randrange(-6, 7))
            job_rows.append(
                {
                    "id": base_id + i + 1,
                    "store_id": store.id,
                    "transaction_id": None,
                    "customer_id": customer["id"],
                    "type": "alteration",
                    "status": status,
                    "promised_date": promised,
                    "ready_at": (
                        datetime.combine(promised, time(17, 0))
                        if status in ("ready", "delivered")
                        else None
                    ),
                    "delivered_at": (
                        datetime.combine(promised, time(18, 30))
                        if status == "delivered"
                        else None
                    ),
                }
            )
        db.execute(insert(Job), job_rows)

    record_type = "prescription" if flags.get("expiry") else "measurement"
    record_rows = []
    for i in range(30):
        customer = customer_rows[rng.randrange(0, CUSTOMERS_PER_STORE)]
        record_rows.append(
            {
                "id": base_id + i + 1,
                "customer_id": customer["id"],
                "record_type": record_type,
                "data": {"note": "seeded demo record", "ref": f"R{rng.randrange(1000, 9999)}"},
                "recorded_on": today - timedelta(days=rng.randrange(5, 400)),
            }
        )
    db.execute(insert(CustomerRecord), record_rows)

    suppliers = seed_suppliers(db, rng, store)

    db.flush()
    rebuild_daily_summary(db, store.id, history_start, today)

    return {
        "suppliers": suppliers,
        "customers": len(customer_rows),
        "products": len(product_rows),
        "categories": len(category_rows),
        "transactions": len(txn_rows),
        "items": len(item_rows),
    }


# --------------------------------------------------------------------------- #
# people who can sign in
# --------------------------------------------------------------------------- #
DEMO_PASSWORD = "localai123"


def seed_users(db: Session) -> None:
    """One account per role per store, plus a platform owner across all of them.

    The password is the same for every demo account and is printed below - these
    are throwaway accounts on throwaway data, and the point is that a reviewer
    can sign in without hunting for credentials.
    """
    from app.security import hash_password

    hashed = hash_password(DEMO_PASSWORD)
    rows = [
        {
            "id": 1,
            "store_id": None,
            "name": "Platform Owner",
            "email": "owner@localai.demo",
            "password_hash": hashed,
            "role": "owner",
            "is_active": True,
            "created_at": datetime(2024, 1, 1, 9, 0, 0),
        }
    ]
    next_id = 2
    for store in db.scalars(select(Store).order_by(Store.id)).all():
        slug = store.name.split()[0].lower()
        for role in ("manager", "cashier"):
            rows.append(
                {
                    "id": next_id,
                    "store_id": store.id,
                    "name": f"{store.name} {role.title()}",
                    "email": f"{role}.{slug}@localai.demo",
                    "password_hash": hashed,
                    "role": role,
                    "is_active": True,
                    "created_at": datetime(2024, 1, 1, 9, 0, 0),
                }
            )
            next_id += 1

    db.execute(insert(User), rows)
    db.flush()
    print(f"  users: {len(rows)} (password for every demo account: {DEMO_PASSWORD})")


def seed_suppliers(db: Session, rng: random.Random, store: Store) -> int:
    names = [
        f"{city} Wholesale", f"{city} Distributors", f"{city} Trading Co"
    ] if (city := store.city) else ["Wholesale"]
    rows = [
        {
            "id": (store.id - 1) * 100 + index + 1,
            "store_id": store.id,
            "name": name,
            "phone": f"9{rng.randrange(10**8, 10**9):09d}"[:10],
            "gstin": None,
            "address": f"{rng.randrange(1, 200)}, Main Market, {store.city}",
            "rating": Decimal(str(round(rng.uniform(3.0, 5.0) * 2) / 2)),
            "notes": None,
        }
        for index, name in enumerate(names)
    ]
    db.execute(insert(Supplier), rows)
    db.flush()
    return len(rows)


# --------------------------------------------------------------------------- #
# proof
# --------------------------------------------------------------------------- #
def report(db: Session) -> None:
    print("\nEdge cases, checked against each store's own thresholds:")
    header = f"{'store':<24}{'vertical':<12}{'inactive>':<10}{'lapsed':>7}{'dead>':>7}{'dead':>6}{'VIP':>5}"
    print(header)
    print("-" * len(header))
    today = date.today()
    for store, vertical in db.execute(
        select(Store, Vertical).join(Vertical, Store.vertical_id == Vertical.id).order_by(Store.id)
    ).all():
        inactive_days = int(vertical.default_config["inactive_days"])
        dead_days = int(vertical.default_config["dead_stock_days"])
        multiplier = float(vertical.default_config["vip_spend_multiplier"])

        last_purchase = (
            select(
                Transaction.customer_id.label("cid"),
                func.max(Transaction.created_at).label("last_at"),
                func.sum(Transaction.total).label("spend"),
            )
            .where(Transaction.store_id == store.id, Transaction.status == "completed")
            .group_by(Transaction.customer_id)
            .subquery()
        )
        cutoff = datetime.combine(today - timedelta(days=inactive_days), time.min)
        lapsed = db.scalar(
            select(func.count()).select_from(last_purchase).where(last_purchase.c.last_at < cutoff)
        )
        average = db.scalar(select(func.avg(last_purchase.c.spend))) or 0
        vips = db.scalar(
            select(func.count())
            .select_from(last_purchase)
            .where(last_purchase.c.spend > float(average) * multiplier)
        )
        dead_cutoff = datetime.combine(today - timedelta(days=dead_days), time.min)
        dead_skus = db.scalar(
            select(func.count())
            .select_from(StockLevel)
            .join(Product, Product.id == StockLevel.product_id)
            .where(
                Product.store_id == store.id,
                StockLevel.qty_on_hand > 0,
                StockLevel.last_sold_at < dead_cutoff,
            )
        )
        print(
            f"{store.name:<24}{vertical.code:<12}{inactive_days:<10}{lapsed:>7}"
            f"{dead_days:>7}{dead_skus:>6}{vips:>5}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo data for Grow Vyaapar")
    parser.add_argument("--quiet", action="store_true", help="skip the summary tables")
    args = parser.parse_args()

    rng = random.Random(SEED)
    random.seed(SEED)

    with SessionLocal() as db:
        print("Wiping and reloading...")
        wipe(db)
        load_verticals(db)
        db.flush()
        seed_rules_and_templates(db)

        verticals = {v.code: v for v in db.scalars(select(Vertical)).all()}
        for index, spec in enumerate(STORES, start=1):
            vertical = verticals[spec["vertical"]]
            store = Store(
                id=index,
                vertical_id=vertical.id,
                name=spec["name"],
                city=spec["city"],
                gstin=spec["gstin"],
                google_review_url=f"https://g.page/r/localai-demo-{index}/review",
                whatsapp_number=spec["whatsapp_number"],
                language=spec["language"],
                created_at=datetime(2024, 1, 1, 9, 0, 0),
            )
            db.add(store)
            db.flush()
            stats = seed_store(db, rng, store, vertical)
            print(
                f"  {store.name} ({vertical.code}): "
                + ", ".join(f"{value} {key}" for key, value in stats.items())
            )

        seed_users(db)
        db.commit()
        if not args.quiet:
            report(db)
    print("\nSeed complete. Start the API with: uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
