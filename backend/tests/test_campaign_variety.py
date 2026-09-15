"""Campaigns must not come out the same every time.

The shopkeeper-visible bug: three "Diwali" drafts, same picture, same caption,
and an offer of "20% on chocolate" that the copy never mentioned. Four causes,
one test group each - the offer never reached the model, both model calls were
cached, the image seed was a constant per store, and the fallback was a single
fixed sentence.
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.agents import campaigns
from app.models.core import Product, StockLevel
from app.verticals.context import resolve_store_context
from tests.test_segmentation import _store


@pytest.fixture(autouse=True)
def _no_network_poster(monkeypatch):
    """The composer fetches a real image; these tests only care what was asked."""
    calls: list[dict] = []

    def fake_compose(background_url, **kwargs):
        calls.append({"background_url": background_url, **kwargs})
        return background_url

    monkeypatch.setattr(campaigns, "compose_poster", fake_compose)
    return calls


def _product(db, store, sku: str, name: str, qty: str = "40") -> Product:
    product = Product(
        store_id=store.id,
        sku=sku,
        name=name,
        cost_price=Decimal("10.00"),
        sell_price=Decimal("20.00"),
        gst_rate=Decimal("5"),
        attributes={},
    )
    db.add(product)
    db.flush()
    db.add(StockLevel(product_id=product.id, qty_on_hand=Decimal(qty), reorder_point=Decimal("5")))
    db.flush()
    return product


def _fake_llm(monkeypatch, reply: dict | None = None):
    """Record every prompt and the options it was sent with."""
    seen: list[dict] = []

    def call(prompt, **kwargs):
        seen.append({"prompt": prompt, **kwargs})
        return json.dumps(reply) if reply is not None else None

    monkeypatch.setattr(campaigns.llm, "available", lambda: True)
    monkeypatch.setattr(campaigns.llm, "call", call)
    return seen


# -- the offer reaches the model -------------------------------------------
def test_the_offer_and_its_products_are_in_the_prompt(db, monkeypatch) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    _product(db, store, "SNK-1", "Masala Peanuts")
    _product(db, store, "PRC-1", "Mint Toothpaste")
    context = resolve_store_context(db, store.id)
    seen = _fake_llm(monkeypatch)

    campaigns.create(db, context, "Diwali", offer_text="20% off toothpaste")

    prompt = seen[0]["prompt"]
    assert "20% off toothpaste" in prompt, "the model was never told the offer"
    assert "Mint Toothpaste" in prompt, "the product the offer names must be offered to it"


def test_without_an_offer_the_model_is_told_not_to_invent_one(db, monkeypatch) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    _product(db, store, "SNK-1", "Masala Peanuts")
    context = resolve_store_context(db, store.id)
    seen = _fake_llm(monkeypatch)

    campaigns.create(db, context, "Diwali")

    assert "NO offer" in seen[0]["prompt"]


# -- nothing cached, and a warmer temperature -------------------------------
def test_the_design_call_skips_the_cache_and_runs_warm(db, monkeypatch) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    context = resolve_store_context(db, store.id)
    seen = _fake_llm(monkeypatch)

    campaigns.create(db, context, "Diwali")

    assert len(seen) == 1, "one design call, not a caption call plus an image call"
    assert seen[0]["use_cache"] is False, "a cached answer is a repeated campaign"
    assert seen[0]["temperature"] > 0.6


# -- the model sees what it wrote last time --------------------------------
def test_recent_campaigns_are_shown_so_they_are_not_repeated(db, monkeypatch) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    context = resolve_store_context(db, store.id)
    _fake_llm(
        monkeypatch,
        {"headline": "Roshni ka tyohaar", "caption": "Pehla Diwali post, bilkul alag.",
         "hashtags": ["#Diwali"], "visual": "diyas on a brass plate"},
    )
    campaigns.create(db, context, "Diwali")
    db.flush()

    seen = _fake_llm(monkeypatch)
    campaigns.create(db, context, "Diwali")

    prompt = seen[0]["prompt"]
    assert "Pehla Diwali post, bilkul alag." in prompt
    assert "diyas on a brass plate" in prompt


def test_two_drafts_get_different_angles_or_styles(db, monkeypatch) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    context = resolve_store_context(db, store.id)
    seen = _fake_llm(monkeypatch)

    for seed in range(12):
        campaigns.create(db, context, "Diwali", seed=seed)

    directions = {
        tuple(line for line in entry["prompt"].splitlines() if line.startswith(("CREATIVE", "PHOTO")))
        for entry in seen
    }
    assert len(directions) > 1, "every draft was given the same creative direction"


# -- the model's design is actually used ------------------------------------
def test_the_design_fills_caption_tags_picture_and_poster_headline(
    db, monkeypatch, _no_network_poster
) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    context = resolve_store_context(db, store.id)
    _fake_llm(
        monkeypatch,
        {
            "headline": "Meetha Diwali, Sasta Diwali",
            "caption": "Is Diwali chocolate par 20% ki bachat, sirf Sharma Kirana par.",
            "hashtags": ["#Diwali", "Indore Shopping"],
            "visual": "chocolate boxes beside glowing diyas on a red cloth",
        },
    )

    campaign, source = campaigns.create(db, context, "Diwali", offer_text="20% on chocolate")

    assert source == "llm"
    assert campaign.caption.startswith("Is Diwali chocolate")
    assert campaign.hashtags == ["#Diwali", "#IndoreShopping"]
    assert campaign.prompt == "chocolate boxes beside glowing diyas on a red cloth"
    assert _no_network_poster[-1]["headline"] == "Meetha Diwali, Sasta Diwali"


# -- the picture changes ------------------------------------------------------
def test_each_draft_gets_its_own_image_seed(db, monkeypatch, _no_network_poster) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    context = resolve_store_context(db, store.id)
    monkeypatch.setattr(campaigns.llm, "available", lambda: False)

    for _ in range(6):
        campaigns.create(db, context, "Diwali")

    urls = {call["background_url"] for call in _no_network_poster}
    assert len(urls) > 1, "the same seed and prompt draws the same picture every time"


# -- the fallback varies too, and stays honest -------------------------------
def test_the_template_fallback_is_not_one_fixed_sentence(db, monkeypatch) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    _product(db, store, "SNK-1", "Masala Peanuts")
    context = resolve_store_context(db, store.id)
    monkeypatch.setattr(campaigns.llm, "available", lambda: False)

    captions = {
        campaigns.create(db, context, "Diwali", seed=seed)[0].caption for seed in range(15)
    }
    assert len(captions) > 1


def test_no_fallback_template_mentions_money_on_its_own() -> None:
    """A pharmacy may not claim a discount; the templates must never do it unasked."""
    for template in campaigns._FALLBACK_CAPTIONS:
        lowered = template.lower()
        for banned in ("discount", "% off", "buy one", "free", "offer", "sale"):
            assert banned not in lowered, f"template says '{banned}': {template}"


def test_the_typed_offer_is_quoted_exactly_in_the_fallback(db, monkeypatch) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    context = resolve_store_context(db, store.id)
    monkeypatch.setattr(campaigns.llm, "available", lambda: False)

    campaign, source = campaigns.create(db, context, "Holi", offer_text="Buy 2 Get 1 on gulal")

    assert source == "template"
    assert "Buy 2 Get 1 on gulal" in campaign.caption


def test_offer_products_never_come_from_another_store(db, monkeypatch) -> None:
    mine = _store(db, "grocery", "Sharma Kirana")
    theirs = _store(db, "grocery", "Other Kirana")
    _product(db, theirs, "OTH-1", "Rival Chocolate")
    context = resolve_store_context(db, mine.id)
    seen = _fake_llm(monkeypatch)

    campaigns.create(db, context, "Diwali", offer_text="20% on chocolate")

    assert "Rival Chocolate" not in seen[0]["prompt"]


def test_an_offer_with_no_matching_product_never_features_unrelated_stock(
    db, monkeypatch
) -> None:
    """The live bug: "20% on chocolate - ... Floor Cleaner 6 is waiting for you"."""
    store = _store(db, "grocery", "Sharma Kirana")
    _product(db, store, "CLN-6", "Floor Cleaner 6", qty="400")
    context = resolve_store_context(db, store.id)
    monkeypatch.setattr(campaigns.llm, "available", lambda: False)

    for seed in range(8):
        campaign, _ = campaigns.create(
            db, context, "Diwali", offer_text="20% on chocolate", seed=seed
        )
        assert "Floor Cleaner" not in campaign.caption
        assert "Floor Cleaner" not in campaign.prompt
        assert "chocolate" in campaign.caption.lower()


def test_the_design_call_waits_long_enough_for_a_thinking_model(db, monkeypatch) -> None:
    store = _store(db, "grocery", "Sharma Kirana")
    context = resolve_store_context(db, store.id)
    seen = _fake_llm(monkeypatch)

    campaigns.create(db, context, "Diwali")

    assert seen[0]["timeout"] >= 30, "10s cut every design off mid-thought"
    assert seen[0]["retries"] <= 1, "three timed-out attempts cost 39s for a template"
