"""Campaign agent: an occasion plus overstocked SKUs becomes a caption and a poster.

Reads core tables, writes only to campaigns.
"""
from __future__ import annotations

import logging
import random
import re
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import forecasting, segmentation
from app.llm import client as llm
from app.llm import prompts
from app.models.agent import Campaign
from app.models.core import Product, StockLevel
from app.services import batch_service, stock_service
from app.services.poster import compose_poster
from app.services.errors import NotFoundError
from app.settings import settings
from app.verticals.context import StoreContext

logger = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 380
DESIGN_TIMEOUT_SECONDS = 45.0


def poster_url(visual_prompt: str, *, seed: int) -> str:
    """Pollinations takes the prompt in the path. No key, no auth, no SDK."""
    trimmed = visual_prompt.strip()[:MAX_PROMPT_CHARS]
    # safe="" so a slash inside the description ("black/white frames") is
    # escaped rather than becoming a path separator: quote() leaves "/" alone
    # by default, and the prompt is a path segment here, not a path.
    return (
        f"{settings.pollinations_base_url}/{quote(trimmed, safe='')}"
        f"?width=1024&height=1024&nologo=true&seed={seed}"
    )


# A new draft gets one of each at random, so two drafts for the same occasion
# start from different ideas even before the model adds its own variation.
# Worded for any kind of shop: nothing here may name a trade.
ANGLES = (
    "the family gathering the occasion brings - what the household needs that day",
    "last-minute preparation: the things people remember they forgot",
    "gifting - something to take when visiting relatives and neighbours",
    "honest value: getting the festival done without overspending",
    "tradition and memory - the way this occasion has always been celebrated",
    "the neighbourhood shop you trust, that knows its customers by name",
    "a small treat for yourself amid the festival rush",
    "doing it early and calmly, before the crowds",
)
VISUAL_STYLES = (
    "overhead flat-lay on a textured cloth, soft daylight",
    "close-up with shallow depth of field and warm evening light",
    "a lively shop counter scene, candid, natural light",
    "minimal studio shot on a bold single-colour background",
    "night scene with glowing lamps and rich bokeh",
    "early-morning sunlight through a window, fresh and airy",
    "festive table arrangement from a low angle, vibrant colours",
)

# Words in an offer that say nothing about which product it is for.
_OFFER_STOPWORDS = {
    "off", "flat", "upto", "buy", "get", "free", "offer", "sale", "all", "and",
    "the", "for", "with", "any", "every", "only", "today", "extra", "save",
    "discount", "price", "combo", "pack", "deal", "rupees", "per", "each",
}


def _offer_products(db: Session, context: StoreContext, offer_text: str | None) -> list[dict]:
    """Products the offer is about, by matching its words against this store's names.

    "20% off toothpaste" should put toothpaste on the poster, not whatever
    happens to be overstocked. Scoped to the store like every other query here.
    """
    if not offer_text:
        return []
    words = [
        word
        for word in re.findall(r"[a-zA-Z]{3,}", offer_text.lower())
        if word not in _OFFER_STOPWORDS
    ]
    matches: dict[int, dict] = {}
    for word in words[:4]:
        rows = db.execute(
            select(Product, StockLevel.qty_on_hand)
            .join(StockLevel, StockLevel.product_id == Product.id, isouter=True)
            .where(
                Product.store_id == context.store_id,
                Product.is_active.is_(True),
                func.lower(Product.name).contains(word),
            )
            .order_by(StockLevel.qty_on_hand.desc())
            .limit(3)
        ).all()
        for product, qty in rows:
            matches.setdefault(
                product.id,
                {
                    "sku": product.sku,
                    "name": product.name,
                    "qty_on_hand": float(qty or 0),
                    "days_since_sold": None,
                    "why": "named in the offer",
                },
            )
    return list(matches.values())[:3]


def _offer_subject(offer_text: str | None) -> str | None:
    """What an offer is about, in its own words: "20% on chocolate" -> "chocolate".

    Used when the catalog has nothing by that name, so the fallback can still
    talk about the thing on offer instead of reaching for unrelated stock.
    """
    if not offer_text:
        return None
    words = [
        word
        for word in re.findall(r"[a-zA-Z]{3,}", offer_text)
        if word.lower() not in _OFFER_STOPWORDS
    ]
    return " ".join(words[:4]) or None


def _recent(db: Session, store_id: int, limit: int = 5) -> list[dict[str, str]]:
    """This store's latest drafts, shown to the model so it does not echo them."""
    rows = db.scalars(
        select(Campaign)
        .where(Campaign.store_id == store_id, Campaign.caption.is_not(None))
        .order_by(Campaign.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {"caption": (row.caption or "")[:180], "visual": (row.prompt or "")[:120]}
        for row in rows
    ]


_FALLBACK_CAPTIONS = (
    "{occasion} at {store}. {featured} and more are on the shelf today. "
    "Visit us in {city} - we are open till 9 pm.",
    "Getting ready for {occasion}? {featured} is waiting for you at {store}, {city}. "
    "Drop in whenever it suits you.",
    "This {occasion}, let {store} take one thing off your list. Pick up {featured} "
    "and everything else you need, right here in {city}.",
    "{occasion} is better when the shopping is easy. {store} has {featured} in stock "
    "now - come by, {city}.",
    "From all of us at {store}: happy {occasion}! {featured} and your everyday "
    "favourites are ready for you in {city}.",
)


def _fallback_copy(
    context: StoreContext,
    occasion: str,
    products: list[dict],
    offer_text: str | None = None,
    rng: random.Random | None = None,
) -> tuple[str, list[str]]:
    """Template copy for when no model answers - still varied, still truthful.

    One of several shapes at random, so repeated drafts do not read identically.
    The offer is quoted exactly when the shopkeeper typed one, and nothing else
    about money is ever said: the vertical's forbidden list is respected by
    saying less.
    """
    rng = rng or random.Random()
    offered = [item for item in products if item.get("why") == "named in the offer"]
    if offer_text:
        # With an offer, feature what it is about - a product it names, or the
        # offer's own subject. Never the overstock: "20% on chocolate" beside
        # "Floor Cleaner 6 is waiting for you" is worse than saying less.
        featured = (
            offered[0]["name"] if offered else _offer_subject(offer_text) or "your favourites"
        )
    else:
        featured = products[0]["name"] if products else "your favourites"
    caption = rng.choice(_FALLBACK_CAPTIONS).format(
        occasion=occasion.strip(),
        store=context.store_name,
        city=context.city,
        featured=featured,
    )
    if offer_text:
        caption = f"{offer_text.strip()} - {caption}"
    city_tag = "".join(part.capitalize() for part in context.city.split())
    occasion_tag = "".join(part.capitalize() for part in occasion.split() if part.isalnum())
    store_tag = "".join(part for part in context.store_name.title().split() if part.isalnum())
    extras = [
        "#ShopLocal",
        "#SmallBusiness",
        "#FestiveSeason",
        f"#{city_tag}Shopping",
        f"#{store_tag}",
        "#VocalForLocal",
    ]
    rng.shuffle(extras)
    vertical_tag = "".join(
        part.capitalize() for part in context.vertical_name.split() if part.isalpha()
    )
    hashtags = [f"#{occasion_tag or 'Festival'}", f"#{city_tag}", f"#{vertical_tag}", *extras[:3]]
    return caption, hashtags


def _visual_fallback(
    context: StoreContext,
    occasion: str,
    products: list[dict],
    style: str | None = None,
    offer_text: str | None = None,
) -> str:
    offered = [item for item in products if item.get("why") == "named in the offer"]
    if offered:
        subject = offered[0]["name"]
    else:
        subject = _offer_subject(offer_text) or (
            products[0]["name"] if products else "the shop counter"
        )
    return f"{subject} for {occasion}, {style or VISUAL_STYLES[0]}, no text"


def create(
    db: Session,
    context: StoreContext,
    occasion: str,
    *,
    offer_text: str | None = None,
    seed: int | None = None,
    campaign: Campaign | None = None,
) -> tuple[Campaign, str]:
    """Draft one campaign. Returns the row and the source: llm or template.

    Pass `campaign` to redraw an existing row in place, which is what Regenerate
    does - a second attempt at the same occasion should replace the poster, not
    add a near-duplicate to the history the shopkeeper scrolls through.
    """
    if not occasion.strip():
        raise NotFoundError("An occasion is required to draft a campaign")

    rng = random.Random(seed) if seed is not None else random.Random()
    offer = (offer_text or "").strip() or None

    # What the shopkeeper's offer names comes first: a poster for "20% off
    # toothpaste" has to show toothpaste. Then stock close to expiry, where the
    # vertical tracks batches at all - the single best thing to push.
    offered = _offer_products(db, context, offer)
    products = [
        {
            "sku": row["sku"],
            "name": row["name"],
            "qty_on_hand": row["qty"],
            "days_since_sold": None,
            "why": f"expires in {row['days_left']} days",
        }
        for row in batch_service.near_expiry(db, context)[:3]
        if not row["is_expired"]
    ]

    # Otherwise, stock the forecaster says is about to go stale: better campaign
    # material than stock that already has, because it can still sell at price.
    products = products or [
        {
            "sku": row.sku,
            "name": row.name,
            "qty_on_hand": float(row.qty_on_hand),
            "days_since_sold": None,
            "why": row.reason,
        }
        for row in forecasting.dead_stock_risk(db, context, limit=3)
    ]
    if not products:
        products = [
            {
                "sku": row.sku,
                "name": row.name,
                "qty_on_hand": float(row.qty_on_hand),
                "days_since_sold": row.days_since_sold,
                "why": "already past the dead-stock window",
            }
            for row in stock_service.overstocked(db, context, limit=3)
        ]
    segments = segmentation.distribution(db, context.store_id)
    # Offer products lead; the rest of the pool follows without duplicates.
    seen = {item["sku"] for item in offered}
    products = (offered + [item for item in products if item["sku"] not in seen])[:5]

    angle = rng.choice(ANGLES)
    style = rng.choice(VISUAL_STYLES)
    caption, hashtags = _fallback_copy(context, occasion, products, offer, rng)
    visual = _visual_fallback(context, occasion, products, style, offer)
    headline: str | None = None
    source = "template"

    if llm.available():
        design = prompts.parse_json_block(
            llm.call(
                prompts.campaign_design_prompt(
                    context,
                    occasion=occasion,
                    offer_text=offer,
                    products=products,
                    segment_counts=segments,
                    recent=_recent(db, context.store_id),
                    angle=angle,
                    style=style,
                ),
                max_tokens=700,
                # Creative work: a warmer temperature, and never the cache - a
                # cached answer is exactly the repeated post this exists to avoid.
                temperature=1.0,
                use_cache=False,
                # A reasoning model thinks for a while before a whole design.
                # The default 10s timeout cut every one off, then retried twice
                # more to the same end: 39 seconds for a template. One patient
                # attempt and one retry is both faster and far likelier to land.
                timeout=DESIGN_TIMEOUT_SECONDS,
                retries=1,
                db=db,
            )
        )
        if isinstance(design, dict) and design.get("caption"):
            caption = str(design["caption"]).strip()[:600]
            tags = design.get("hashtags") or []
            if isinstance(tags, list) and tags:
                cleaned = [str(item).strip().replace(" ", "") for item in tags]
                hashtags = [
                    tag if tag.startswith("#") else f"#{tag}" for tag in cleaned if tag
                ][:7]
            if design.get("visual"):
                visual = str(design["visual"]).strip().strip('"')[:MAX_PROMPT_CHARS]
            if design.get("headline"):
                headline = str(design["headline"]).strip().strip('"')[:60] or None
            source = "llm"

    if campaign is None:
        campaign = Campaign(store_id=context.store_id, status="draft")
        db.add(campaign)

    campaign.occasion = occasion.strip()
    campaign.offer_text = offer
    campaign.prompt = visual
    campaign.caption = caption
    campaign.hashtags = hashtags
    # Flushed before composing so a new row has an id to key its poster file on.
    db.flush()

    # A fresh seed per draft. It used to be the store id times 101, so every
    # campaign a store drew from a similar prompt came back as the same picture.
    background = poster_url(visual, seed=seed if seed is not None else rng.randrange(1, 10**6))
    # The generator draws the picture; Pillow draws the words. Never raises -
    # on any failure this hands back the plain background unchanged.
    campaign.image_url = compose_poster(
        background,
        store_name=context.store_name,
        occasion=campaign.occasion,
        offer_text=campaign.offer_text,
        headline=headline,
        address=context.address,
        key=f"store{context.store_id}-campaign{campaign.id}",
    )
    db.flush()
    return campaign, source


def list_campaigns(db: Session, store_id: int, limit: int = 20) -> list[Campaign]:
    return list(
        db.scalars(
            select(Campaign)
            .where(Campaign.store_id == store_id)
            .order_by(Campaign.created_at.desc())
            .limit(limit)
        ).all()
    )
