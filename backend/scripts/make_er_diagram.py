"""Draw docs/er-diagram.png straight from the SQLAlchemy metadata.

    python -m scripts.make_er_diagram

Reading the models means the picture cannot drift from the schema. Any table not
listed in a column below is drawn anyway, in an "unplaced" column, so forgetting
to update this file shows up in the diagram instead of hiding.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.models import Base

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "er-diagram.png"

# One entry per drawn column: (group, heading, tables).
COLUMNS = [
    ("Configuration", "Configuration",
     ["verticals", "stores", "store_config", "reminder_rules", "message_templates"]),
    ("Core", "Core: customers and catalog",
     ["customers", "customer_records", "product_categories", "products", "stock_levels",
      "batches"]),
    ("Core", "Core: trade",
     ["transactions", "transaction_items", "jobs", "daily_sales_summary"]),
    ("Agent", "Agent-owned",
     ["segments", "reminders", "campaigns", "insights", "churn_scores"]),
    ("Agent", "Agent-owned (models)",
     ["stock_forecasts", "campaign_stats", "model_runs", "llm_cache"]),
    ("Commerce", "Loyalty and offers",
     ["coupons", "coupon_redemptions", "loyalty_accounts", "loyalty_ledger", "referrals"]),
    ("Admin", "People and buying",
     ["users", "suppliers", "purchase_orders", "purchase_items", "audit_logs"]),
]

COLOURS = {
    "Configuration": (219, 234, 254),
    "Core": (220, 252, 231),
    "Agent": (254, 226, 226),
    "Commerce": (254, 243, 199),
    "Admin": (237, 233, 254),
    "Unplaced": (243, 244, 246),
}
BORDER = {
    "Configuration": (37, 99, 235),
    "Core": (22, 163, 74),
    "Agent": (220, 38, 38),
    "Commerce": (217, 119, 6),
    "Admin": (109, 40, 217),
    "Unplaced": (107, 114, 128),
}

WIDTH, HEIGHT = 3400, 1400
BOX_WIDTH = 400
LINE_HEIGHT = 17
PADDING = 9
COLUMN_GAP = 70


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in ("arial.ttf", "DejaVuSans.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _columns() -> list[tuple[str, str, list[str]]]:
    placed = {name for _, _, tables in COLUMNS for name in tables}
    missing = [name for name in sorted(Base.metadata.tables) if name not in placed]
    if missing:
        return [*COLUMNS, ("Unplaced", "Not yet placed in this diagram", missing)]
    return list(COLUMNS)


def main() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    title_font, header_font, body_font = _font(34), _font(18), _font(13)

    columns = _columns()
    total = len(Base.metadata.tables)

    draw.text((40, 26), "Grow Vyaapar - data model", fill=(17, 24, 39), font=title_font)
    draw.text(
        (40, 72),
        f"{total} tables. Every core, agent and commerce table carries store_id. "
        "Generated from the SQLAlchemy metadata, so it cannot drift from the schema.",
        fill=(75, 85, 99),
        font=header_font,
    )

    boxes: dict[str, tuple[int, int, int, int]] = {}
    for index, (group, heading, tables) in enumerate(columns):
        x = 40 + index * (BOX_WIDTH + COLUMN_GAP)
        y = 120
        draw.text((x, y), heading, fill=BORDER[group], font=header_font)
        y += 30
        for table_name in tables:
            table = Base.metadata.tables.get(table_name)
            if table is None:
                continue
            fields = [
                f"{column.name}{' PK' if column.primary_key else ''}"
                f"{' FK' if column.foreign_keys else ''}"
                for column in table.columns
            ]
            height = 27 + LINE_HEIGHT * len(fields) + PADDING
            draw.rounded_rectangle(
                [x, y, x + BOX_WIDTH, y + height],
                radius=9,
                fill=COLOURS[group],
                outline=BORDER[group],
                width=2,
            )
            draw.text((x + PADDING, y + 5), table_name, fill=(17, 24, 39), font=header_font)
            draw.line([x, y + 27, x + BOX_WIDTH, y + 27], fill=BORDER[group], width=1)
            for position, label in enumerate(fields):
                draw.text(
                    (x + PADDING, y + 31 + position * LINE_HEIGHT),
                    label,
                    fill=(31, 41, 55),
                    font=body_font,
                )
            boxes[table_name] = (x, y, x + BOX_WIDTH, y + height)
            y += height + 12

    for table in Base.metadata.tables.values():
        if table.name not in boxes:
            continue
        for column in table.columns:
            for foreign_key in column.foreign_keys:
                target = foreign_key.column.table.name
                if target not in boxes or target == table.name:
                    continue
                x0, y0, x1, y1 = boxes[table.name]
                tx0, ty0, tx1, ty1 = boxes[target]
                start, end = (x0, (y0 + y1) // 2), (tx1, (ty0 + ty1) // 2)
                if tx0 > x1:
                    start, end = (x1, (y0 + y1) // 2), (tx0, (ty0 + ty1) // 2)
                draw.line([start, end], fill=(190, 195, 202), width=1)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT)
    print(f"wrote {OUTPUT} ({len(boxes)} of {total} tables drawn)")


if __name__ == "__main__":
    main()
