"""Draw docs/er-diagram.png straight from the SQLAlchemy metadata.

    python -m scripts.make_er_diagram

Reading the models means the picture cannot drift from the schema.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.models import Base

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "er-diagram.png"

# One entry per drawn column. Core needs two columns to stay legible.
COLUMNS = [
    ("Configuration", "Configuration",
     ["verticals", "stores", "store_config", "reminder_rules", "message_templates"]),
    ("Core", "Core",
     ["customers", "customer_records", "product_categories", "products", "stock_levels"]),
    ("Core", "Core (continued)",
     ["batches", "transactions", "transaction_items", "jobs", "daily_sales_summary"]),
    ("Agent-owned", "Agent-owned",
     ["segments", "reminders", "campaigns", "insights", "churn_scores"]),
]

COLOURS = {
    "Configuration": (219, 234, 254),
    "Core": (220, 252, 231),
    "Agent-owned": (254, 226, 226),
}
BORDER = {
    "Configuration": (37, 99, 235),
    "Core": (22, 163, 74),
    "Agent-owned": (220, 38, 38),
}

WIDTH, HEIGHT = 2100, 1320
BOX_WIDTH = 380
LINE_HEIGHT = 19
PADDING = 10


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in ("arial.ttf", "DejaVuSans.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    title_font, header_font, body_font = _font(34), _font(19), _font(14)

    draw.text((40, 30), "LocalAI OS - data model", fill=(17, 24, 39), font=title_font)
    draw.text(
        (40, 76),
        "20 tables. Every core and agent table carries store_id. Generated from the "
        "SQLAlchemy metadata.",
        fill=(75, 85, 99),
        font=header_font,
    )

    boxes: dict[str, tuple[int, int, int, int]] = {}
    column_x = [40, 550, 1060, 1610]

    for column, (group, heading, tables) in enumerate(COLUMNS):
        x = column_x[column]
        y = 130
        draw.text((x, y), heading, fill=BORDER[group], font=header_font)
        y += 34
        for table_name in tables:
            table = Base.metadata.tables[table_name]
            columns = [
                f"{col.name}{' PK' if col.primary_key else ''}"
                f"{' FK' if col.foreign_keys else ''}"
                for col in table.columns
            ]
            height = 30 + LINE_HEIGHT * len(columns) + PADDING
            draw.rounded_rectangle(
                [x, y, x + BOX_WIDTH, y + height],
                radius=10,
                fill=COLOURS[group],
                outline=BORDER[group],
                width=2,
            )
            draw.text((x + PADDING, y + 7), table_name, fill=(17, 24, 39), font=header_font)
            draw.line(
                [x, y + 30, x + BOX_WIDTH, y + 30], fill=BORDER[group], width=1
            )
            for index, column_label in enumerate(columns):
                draw.text(
                    (x + PADDING, y + 34 + index * LINE_HEIGHT),
                    column_label,
                    fill=(31, 41, 55),
                    font=body_font,
                )
            boxes[table_name] = (x, y, x + BOX_WIDTH, y + height)
            y += height + 14

    # Foreign key lines, drawn behind nothing important: box edge to box edge.
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
                start = (x0, (y0 + y1) // 2)
                end = (tx1, (ty0 + ty1) // 2)
                if tx0 > x1:
                    start, end = (x1, (y0 + y1) // 2), (tx0, (ty0 + ty1) // 2)
                draw.line([start, end], fill=(156, 163, 175), width=1)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT)
    print(f"wrote {OUTPUT} ({len(boxes)} tables)")


if __name__ == "__main__":
    main()
