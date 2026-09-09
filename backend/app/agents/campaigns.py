"""Campaign agent: an occasion plus overstocked SKUs becomes a caption and a poster.

Reads core tables, writes only to campaigns.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import forecasting, segmentation
from app.llm import client as llm
from app.llm import prompts
from app.models.agent import Campaign
from app.services import batch_service, stock_service
from app.services.poster import compose_poster
from app.services.errors import NotFoundError
from app.settings import settings
from app.verticals.context import StoreContext

logger = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 380


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


def _fallback_copy(
    context: StoreContext, occasion: str, products: list[dict]
) -> tuple[str, list[str]]:
    """Template copy that respects the vertical's forbidden list by saying less."""
    headline = products[0]["name"] if products else "your favourites"
    caption = (
        f"{occasion} at {context.store_name}. {headline} and more are on the shelf today. "
        f"Visit us in {context.city} - we are open till 9 pm."
    )
    city_tag = "".join(part.capitalize() for part in context.city.split())
    occasion_tag = "".join(part.capitalize() for part in occasion.split() if part.isalnum())
    hashtags = [
        f"#{occasion_tag or 'Festival'}",
        f"#{city_tag}",
        f"#{''.join(part.capitalize() for part in context.vertical_name.split() if part.isalpha())}",
        "#ShopLocal",
        "#SmallBusiness",
    ]
    return caption, hashtags


def _visual_fallback(context: StoreContext, occasion: str, products: list[dict]) -> str:
    subject = products[0]["name"] if products else "the shop counter"
    return (
        f"{subject} arranged on a clean wooden counter for {occasion}, warm festive lighting, "
        f"marigold garland in the background, shallow depth of field, no text"
    )


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

    # Stock with an expiry date on the horizon is the single best thing to push,
    # so it comes first where the vertical tracks batches at all.
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

    caption, hashtags = _fallback_copy(context, occasion, products)
    visual = _visual_fallback(context, occasion, products)
    source = "template"

    if llm.available():
        parsed = prompts.parse_json_block(
            llm.call(
                prompts.campaign_caption_prompt(
                    context, occasion=occasion, products=products, segment_counts=segments
                ),
                max_tokens=320,
                db=db,
            )
        )
        if isinstance(parsed, dict) and parsed.get("caption"):
            caption = str(parsed["caption"]).strip()[:600]
            tags = parsed.get("hashtags") or []
            if isinstance(tags, list) and tags:
                hashtags = [
                    tag if str(tag).startswith("#") else f"#{tag}"
                    for tag in [str(item).strip() for item in tags][:7]
                ]
            source = "llm"

        described = llm.call(
            prompts.campaign_image_prompt(context, occasion=occasion, products=products),
            max_tokens=500,
            db=db,
        )
        if described:
            visual = described.strip().strip('"')[:MAX_PROMPT_CHARS]

    if campaign is None:
        campaign = Campaign(store_id=context.store_id, status="draft")
        db.add(campaign)

    campaign.occasion = occasion.strip()
    campaign.offer_text = (offer_text or "").strip() or None
    campaign.prompt = visual
    campaign.caption = caption
    campaign.hashtags = hashtags
    # Flushed before composing so a new row has an id to key its poster file on.
    db.flush()

    background = poster_url(
        visual, seed=seed if seed is not None else context.store_id * 101
    )
    # The generator draws the picture; Pillow draws the words. Never raises -
    # on any failure this hands back the plain background unchanged.
    campaign.image_url = compose_poster(
        background,
        store_name=context.store_name,
        occasion=campaign.occasion,
        offer_text=campaign.offer_text,
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
