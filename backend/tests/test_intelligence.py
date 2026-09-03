"""The intelligence layer degrades instead of breaking.

Python computes every number; the model only writes sentences about numbers it
was handed. With no key at all, every screen still has content.
"""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.agents import campaigns as campaign_agent
from app.agents import insights as insight_agent
from app.llm import client as llm
from app.llm import prompts
from app.models.agent import Insight
from app.models.base import utcnow
from app.models.config import Store, Vertical
from app.models.core import (
    Customer,
    Product,
    ProductCategory,
    StockLevel,
    Transaction,
    TransactionItem,
)
from app.verticals.context import resolve_store_context


def _shop(db, code: str, name: str = "Demo Store") -> Store:
    vertical = db.scalar(select(Vertical).where(Vertical.code == code))
    store = Store(vertical_id=vertical.id, name=name, city="Indore", language="en")
    db.add(store)
    db.commit()
    return store


def _trading_history(db, store: Store) -> None:
    category = ProductCategory(store_id=store.id, name="Regulars")
    db.add(category)
    db.flush()

    products = []
    for index in range(3):
        product = Product(
            store_id=store.id,
            sku=f"SKU-{store.id}-{index}",
            name=f"Item {index}",
            category_id=category.id,
            cost_price=Decimal("40.00"),
            sell_price=Decimal("100.00"),
            gst_rate=Decimal("5"),
            attributes={},
        )
        db.add(product)
        db.flush()
        db.add(
            StockLevel(
                product_id=product.id,
                qty_on_hand=Decimal("2") if index == 0 else Decimal("60"),
                reorder_point=Decimal("10"),
                last_sold_at=utcnow() - timedelta(days=400 if index == 2 else 1),
            )
        )
        products.append(product)

    customer = Customer(store_id=store.id, name="Regular Ramesh", phone="9800000001")
    db.add(customer)
    db.flush()

    for day in (1, 2, 3, 9, 10):
        transaction = Transaction(
            store_id=store.id,
            customer_id=customer.id,
            invoice_no=f"INV-{store.id:02d}-{day:05d}",
            subtotal=Decimal("500.00"),
            discount=Decimal("0.00"),
            gst_amount=Decimal("25.00"),
            total=Decimal("525.00"),
            payment_mode="cash",
            status="completed",
            created_at=utcnow() - timedelta(days=day),
        )
        db.add(transaction)
        db.flush()
        db.add(
            TransactionItem(
                transaction_id=transaction.id,
                product_id=products[0].id,
                qty=Decimal("5"),
                unit_price=Decimal("100.00"),
                line_discount=Decimal("0.00"),
                line_total=Decimal("500.00"),
            )
        )
    db.commit()


# -- the client ---------------------------------------------------------------
def test_call_returns_none_when_no_provider_is_configured() -> None:
    assert llm.available() is False
    assert llm.call("say hello") is None


def test_call_survives_a_provider_that_raises(monkeypatch) -> None:
    monkeypatch.setattr(llm.settings, "groq_api_key", "test-key")
    monkeypatch.setattr(llm.settings, "llm_max_retries", 0)

    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(llm, "_call_groq", boom)
    assert llm.call("anything") is None      # no exception escapes into the request


# -- insights -----------------------------------------------------------------
def test_metrics_are_computed_in_python_not_guessed(db) -> None:
    store = _shop(db, "grocery")
    _trading_history(db, store)
    context = resolve_store_context(db, store.id)

    metrics = insight_agent.compute_metrics(db, context)
    assert metrics["week_sales"] == 1575.0          # three bills of 525 inside 7 days
    assert metrics["previous_week_sales"] == 1050.0  # two bills of 525
    assert metrics["week_over_week_change_pct"] == 50.0
    assert metrics["low_stock_count"] == 1
    assert metrics["dead_stock_count"] >= 1


def test_insights_fall_back_to_template_suggestions_without_a_key(db) -> None:
    store = _shop(db, "grocery")
    _trading_history(db, store)
    context = resolve_store_context(db, store.id)

    insight, source = insight_agent.generate(db, context)
    db.commit()

    assert source == "template"
    assert len(insight.suggestions_json) == 3
    for suggestion in insight.suggestions_json:
        assert suggestion["title"] and suggestion["detail"]
    joined = json.dumps(insight.suggestions_json)
    assert "1,575" in joined or "1575" in joined, "a suggestion must quote a real figure"


def test_insights_are_cached_for_a_day(db) -> None:
    store = _shop(db, "grocery")
    _trading_history(db, store)
    context = resolve_store_context(db, store.id)

    first, first_source = insight_agent.generate(db, context)
    db.commit()
    second, second_source = insight_agent.generate(db, context)
    db.commit()

    assert first_source == "template"
    assert second_source == "cache"
    assert first.id == second.id
    assert len(db.scalars(select(Insight)).all()) == 1


def test_a_model_reply_is_used_when_it_parses(db, monkeypatch) -> None:
    store = _shop(db, "grocery")
    _trading_history(db, store)
    context = resolve_store_context(db, store.id)

    reply = json.dumps(
        {
            "suggestions": [
                {
                    "title": f"Sales up {i}",
                    "detail": "Week sales are INR 1,575 against INR 1,050 last week.",
                    "figure": "INR 1,575",
                    "action": "customers",
                }
                for i in range(3)
            ]
        }
    )
    monkeypatch.setattr(insight_agent.llm, "available", lambda: True)
    monkeypatch.setattr(insight_agent.llm, "call", lambda *a, **k: f"```json\n{reply}\n```")

    insight, source = insight_agent.generate(db, context, force=True)
    db.commit()

    assert source == "llm"
    assert insight.suggestions_json[0]["figure"] == "INR 1,575"


def test_a_broken_model_reply_falls_back_without_raising(db, monkeypatch) -> None:
    store = _shop(db, "grocery")
    _trading_history(db, store)
    context = resolve_store_context(db, store.id)

    monkeypatch.setattr(insight_agent.llm, "available", lambda: True)
    monkeypatch.setattr(insight_agent.llm, "call", lambda *a, **k: "sorry, I cannot help")

    insight, source = insight_agent.generate(db, context, force=True)
    db.commit()
    assert source == "template_failed", "a key was configured, the call just didn't hold up"
    assert len(insight.suggestions_json) == 3


# -- prompts and campaigns ----------------------------------------------------
def test_every_prompt_carries_the_forbidden_list(db) -> None:
    store = _shop(db, "pharmacy", "Jeevan Medical")
    context = resolve_store_context(db, store.id)

    blocks = [
        prompts.profile_block(context),
        prompts.insights_prompt(context, {"week_sales": 1}),
        prompts.campaign_caption_prompt(
            context, occasion="Diwali", products=[], segment_counts={}
        ),
        prompts.campaign_image_prompt(context, occasion="Diwali", products=[]),
    ]
    for forbidden in context.prompt_profile["forbidden"]:
        for block in blocks:
            assert forbidden in block, f"'{forbidden}' missing from a prompt"


def test_campaign_drafts_without_a_key_and_never_claims_a_discount(db) -> None:
    store = _shop(db, "pharmacy", "Jeevan Medical")
    _trading_history(db, store)
    context = resolve_store_context(db, store.id)

    campaign, source = campaign_agent.create(db, context, "Diwali")
    db.commit()

    assert source == "template"
    assert campaign.status == "draft"
    assert campaign.caption and campaign.hashtags
    assert campaign.image_url.startswith("https://image.pollinations.ai/prompt/")
    lowered = campaign.caption.lower()
    for banned in ("discount", "% off", "buy one", "free"):
        assert banned not in lowered, f"pharmacy copy must not say '{banned}'"


def test_campaign_endpoint_and_dashboard_do_not_500_without_a_key(client, db) -> None:
    store = _shop(db, "apparel", "Rangoli Fashion")
    _trading_history(db, store)

    assert client.get(f"/analytics/summary?store_id={store.id}").status_code == 200
    assert client.get(f"/analytics/metrics?store_id={store.id}").status_code == 200

    insights = client.get(f"/marketing/insights?store_id={store.id}")
    assert insights.status_code == 200
    assert len(insights.json()["suggestions"]) == 3

    campaign = client.post(
        f"/marketing/campaigns?store_id={store.id}", json={"occasion": "Teej"}
    )
    assert campaign.status_code == 201
    assert campaign.json()["image_url"]
