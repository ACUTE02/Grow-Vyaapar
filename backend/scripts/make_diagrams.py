"""Draw docs/architecture.png and docs/nightly-flow.png.

    python -m scripts.make_diagrams

Hand-drawn boxes rather than a Graphviz dependency: the shapes are few, and one
fewer system library to install on a marker's machine is worth more than an
automatic layout.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DOCS = Path(__file__).resolve().parents[2] / "docs"

INK = (17, 24, 39)
MUTED = (90, 99, 112)
ARROW = (120, 130, 145)

PALETTE = {
    "ui": ((219, 234, 254), (37, 99, 235)),
    "api": ((220, 252, 231), (22, 163, 74)),
    "agent": ((254, 226, 226), (220, 38, 38)),
    "data": ((237, 233, 254), (109, 40, 217)),
    "external": ((254, 243, 199), (217, 119, 6)),
    "config": ((224, 242, 254), (2, 132, 199)),
}


def font(size: int) -> ImageFont.ImageFont:
    for candidate in ("arial.ttf", "DejaVuSans.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def box(draw, xy, title, lines, kind, title_font, body_font):
    x0, y0, x1, y1 = xy
    fill, border = PALETTE[kind]
    draw.rounded_rectangle([x0, y0, x1, y1], radius=10, fill=fill, outline=border, width=2)
    draw.text((x0 + 12, y0 + 9), title, fill=INK, font=title_font)
    for index, line in enumerate(lines):
        draw.text((x0 + 12, y0 + 34 + index * 17), line, fill=MUTED, font=body_font)


def arrow(draw, start, end, label="", label_font=None, dashed=False):
    x0, y0 = start
    x1, y1 = end
    if dashed:
        steps = max(int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 // 12), 1)
        for step in range(steps):
            if step % 2:
                continue
            ax = x0 + (x1 - x0) * step / steps
            ay = y0 + (y1 - y0) * step / steps
            bx = x0 + (x1 - x0) * (step + 1) / steps
            by = y0 + (y1 - y0) * (step + 1) / steps
            draw.line([ax, ay, bx, by], fill=ARROW, width=2)
    else:
        draw.line([x0, y0, x1, y1], fill=ARROW, width=2)

    angle_x, angle_y = x1 - x0, y1 - y0
    length = max((angle_x**2 + angle_y**2) ** 0.5, 1)
    ux, uy = angle_x / length, angle_y / length
    head = 9
    draw.polygon(
        [
            (x1, y1),
            (x1 - head * ux - head * 0.5 * uy, y1 - head * uy + head * 0.5 * ux),
            (x1 - head * ux + head * 0.5 * uy, y1 - head * uy - head * 0.5 * ux),
        ],
        fill=ARROW,
    )
    if label and label_font:
        draw.text(((x0 + x1) / 2 - 4, (y0 + y1) / 2 - 20), label, fill=MUTED, font=label_font)


# --------------------------------------------------------------------------- #
# system architecture
# --------------------------------------------------------------------------- #
def architecture() -> Path:
    image = Image.new("RGB", (1800, 1010), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    title_font, header_font, body_font, small = font(30), font(17), font(13), font(12)

    draw.text((40, 26), "Grow Vyaapar - system architecture", fill=INK, font=title_font)
    draw.text(
        (40, 68),
        "One deployable. The agents are Python modules inside the same process, not services.",
        fill=MUTED,
        font=header_font,
    )

    box(draw, (40, 120, 400, 250), "Streamlit front end", [
        "POS, Dashboard, Customers, Catalog,",
        "Reorder, Outbox, Campaigns, Performance",
        "Jobs / Expiry / Purchasing appear only",
        "when the flag or the role allows",
    ], "ui", header_font, body_font)

    box(draw, (40, 290, 400, 400), "Any HTTP client", [
        "/docs is the same API the UI uses.",
        "scripts/rehearse.py walks the demo",
        "path against a deployed instance.",
    ], "ui", header_font, body_font)

    box(draw, (470, 120, 860, 300), "FastAPI", [
        "middleware: request id -> authorisation",
        "  -> audit trail",
        "routers: config, customers, products,",
        "  billing, jobs, marketing, ml, loyalty,",
        "  purchasing, analytics, auth",
        "one exception handler, no stack traces out",
    ], "api", header_font, body_font)

    box(draw, (470, 330, 860, 470), "Services", [
        "billing (GST, stock, FEFO), stock,",
        "customers, products, coupons, loyalty,",
        "suppliers, delivery, invoice PDF,",
        "finance rollup",
        "domain errors, never HTTP concepts",
    ], "api", header_font, body_font)

    box(draw, (470, 500, 860, 640), "StoreContext", [
        "the ONE place configuration is read",
        "verticals.default_config",
        "  + store_config overrides",
        "thresholds, flags, product schema, tone",
    ], "config", header_font, body_font)

    box(draw, (930, 120, 1320, 400), "Agents (read core, write only their own)", [
        "segmentation  -> segments",
        "reminders     -> reminders",
        "insights      -> insights",
        "campaigns     -> campaigns",
        "churn         -> churn_scores, model_runs",
        "forecasting   -> stock_forecasts",
        "attribution   -> campaign_stats",
        "",
        "scheduler.py runs the same functions",
        "the buttons call, nightly at 02:00 IST",
    ], "agent", header_font, body_font)

    box(draw, (930, 440, 1320, 620), "LLM layer", [
        "one call(): gemini -> groq -> None",
        "token bucket, prompt cache, 429 backoff",
        "batched drafting, 20 messages per call",
        "every call has a template fallback",
    ], "agent", header_font, body_font)

    box(draw, (1390, 120, 1760, 320), "Database", [
        "SQLite in development,",
        "Postgres in production,",
        "same code and same migrations",
        "",
        "34 tables, every one carries store_id",
        "Alembic, one revision per task",
    ], "data", header_font, body_font)

    box(draw, (1390, 360, 1760, 560), "Outside world", [
        "Gemini / Groq   captions and suggestions",
        "Pollinations    poster images, no key",
        "WhatsApp Cloud  opt-in per send only",
        "Twilio sandbox  the same, behind a flag",
        "",
        "every one of them optional",
    ], "external", header_font, body_font)

    box(draw, (470, 690, 1320, 800), "The claim this shape protects", [
        "A kirana, a chemist and a clothing shop run the same binary. What differs is rows:",
        "thresholds, feature flags, product fields, reminder rules and copy tone.",
        "A test walks every module outside app/verticals/ and fails if a vertical name appears.",
    ], "config", header_font, body_font)

    box(draw, (470, 840, 1320, 960), "What the agent does on its own", [
        "A completed sale is itself the trigger for a review request - nobody asks for it.",
        "The nightly run resegments, rescores churn, forecasts stock, drafts messages and",
        "attributes campaigns. It never sends: delivery is always an explicit human action.",
    ], "agent", header_font, body_font)

    arrow(draw, (400, 185), (470, 185), "HTTP", small)
    arrow(draw, (400, 345), (470, 345), "HTTP", small)
    arrow(draw, (860, 210), (930, 210), "calls", small)
    arrow(draw, (860, 400), (930, 400))
    arrow(draw, (665, 300), (665, 330))
    arrow(draw, (665, 470), (665, 500))
    arrow(draw, (1320, 220), (1390, 220), "SQLAlchemy", small)
    arrow(draw, (860, 560), (930, 500))
    draw.text((868, 520), "context", fill=MUTED, font=small)
    arrow(draw, (1320, 520), (1390, 470))
    draw.text((1326, 486), "optional", fill=MUTED, font=small)

    path = DOCS / "architecture.png"
    image.save(path)
    return path


# --------------------------------------------------------------------------- #
# the nightly agent run
# --------------------------------------------------------------------------- #
def nightly_flow() -> Path:
    image = Image.new("RGB", (1800, 1000), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    title_font, header_font, body_font, small = font(30), font(17), font(13), font(12)

    draw.text((40, 26), "The nightly agent run - data flow", fill=INK, font=title_font)
    draw.text(
        (40, 68),
        "scheduler.py, 02:00 Asia/Kolkata, one pass per store. Every step calls the same "
        "function the manual button calls.",
        fill=MUTED,
        font=header_font,
    )

    box(draw, (40, 130, 330, 300), "Read: core tables", [
        "transactions, transaction_items",
        "customers, products, stock_levels",
        "jobs, batches, reminder_rules",
        "",
        "agents never write here",
    ], "data", header_font, body_font)

    steps = [
        ("1. finance rollup", [
            "recompute daily_sales_summary",
            "for the last 45 days",
            "-> daily_sales_summary",
        ], "api"),
        ("2. segmentation", [
            "one SQL pass: recency, frequency,",
            "spend; classify with the store's",
            "own thresholds -> segments",
        ], "agent"),
        ("3. churn scoring", [
            "features as of today, clipped to",
            "the trained range, logistic model",
            "-> churn_scores",
        ], "agent"),
        ("4. stock forecast", [
            "day-of-week weighted velocity,",
            "days to stockout, reorder qty",
            "-> stock_forecasts",
        ], "agent"),
        ("5. reminder rules", [
            "for each enabled rule, evaluate its",
            "signal; skip opted-out customers;",
            "draft in batches -> reminders",
        ], "agent"),
        ("6. attribution", [
            "who was messaged, who came back",
            "within 14 days, what they spent",
            "-> campaign_stats",
        ], "agent"),
        ("7. insights", [
            "compute every figure in SQL, hand",
            "them to the model as facts, cache",
            "-> insights",
        ], "agent"),
    ]

    x = 390
    for index, (title, lines, kind) in enumerate(steps):
        row, column = divmod(index, 4)
        left = x + column * 340
        top = 130 + row * 210
        box(draw, (left, top, left + 300, top + 160), title, lines, kind, header_font, body_font)
        if column < 3 and index < len(steps) - 1:
            arrow(draw, (left + 300, top + 80), (left + 340, top + 80))
    arrow(draw, (390 + 3 * 340 + 150, 290), (390 + 150, 340))

    box(draw, (40, 340, 330, 470), "Write: agent tables only", [
        "segments, reminders, insights,",
        "campaigns, churn_scores,",
        "stock_forecasts, campaign_stats,",
        "model_runs",
    ], "agent", header_font, body_font)

    box(draw, (40, 560, 1740, 690), "What it does NOT do", [
        "It does not send. Not a message, not an email, not a WhatsApp. Every reminder it drafts sits in",
        "the Outbox with status 'queued' until a person ticks it and presses send, and even then a daily",
        "cap and a per-customer consent flag stand in the way. A scheduled job that can message a real",
        "customer is one bug away from messaging all of them.",
    ], "external", header_font, body_font)

    box(draw, (40, 730, 1740, 900), "Next morning, the shopkeeper sees", [
        "Dashboard  - three suggestions quoting figures computed in SQL, a churn-risk tile, a stock outlook",
        "Outbox     - drafted messages grouped by kind, each with the customer and the reason",
        "Reorder    - what runs out inside the reorder cycle, and what is trending towards dead stock",
        "Performance- what the last campaign reached, and what it plausibly earned",
        "",
        "Nothing here was asked for. That is the point of calling it an agent rather than a report.",
    ], "ui", header_font, body_font)

    arrow(draw, (185, 300), (185, 340))
    arrow(draw, (330, 200), (390, 200), "reads", small)

    path = DOCS / "nightly-flow.png"
    image.save(path)
    return path


if __name__ == "__main__":
    for produced in (architecture(), nightly_flow()):
        print(f"wrote {produced}")
