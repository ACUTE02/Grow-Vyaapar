"""Walk the four-minute path against a running API, for two different verticals.

    python -m scripts.rehearse                    # every seeded store
    python -m scripts.rehearse --stores 2 3       # just these

Exits non-zero if any step fails, so it doubles as a smoke test before a demo.
"""
from __future__ import annotations

import argparse
import sys

import httpx

from app.settings import settings

BASE = settings.api_base_url.rstrip("/")
TIMEOUT = 60.0


class StepFailed(Exception):
    pass


def _call(method: str, path: str, **kwargs) -> dict | list:
    response = httpx.request(method, f"{BASE}{path}", timeout=TIMEOUT, **kwargs)
    if response.status_code >= 400:
        raise StepFailed(f"{method} {path} -> {response.status_code} {response.text[:200]}")
    return response.json()


def walk(store_id: int) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    context = _call("GET", f"/config/stores/{store_id}/context")
    vertical = context["vertical_code"]
    unit = context["unit_labels"]["default"]

    # 1 - create a sale on the POS
    products = _call("GET", "/products", params={"store_id": store_id, "limit": 5})
    sellable = [p for p in products if float(p["qty_on_hand"]) >= 2]
    if not sellable:
        raise StepFailed("no product with stock to sell")
    product = sellable[0]
    customers = _call("GET", "/customers", params={"store_id": store_id, "limit": 1})
    before = float(product["qty_on_hand"])

    sale = _call(
        "POST",
        "/billing/transactions",
        params={"store_id": store_id},
        json={
            "customer_id": customers[0]["id"],
            "lines": [{"product_id": product["id"], "qty": 2}],
            "payment_mode": "upi",
        },
    )
    after = float(
        _call("GET", f"/products/{product['id']}", params={"store_id": store_id})["qty_on_hand"]
    )
    if round(before - after, 3) != 2.0:
        raise StepFailed(f"stock moved by {before - after}, expected 2")
    results.append(("1 sale on the POS", f"{sale['invoice_no']}, stock -2 {unit}"))

    # 2 - a review_request appears without being asked for
    queued = _call(
        "GET",
        "/marketing/reminders",
        params={"store_id": store_id, "status": "queued", "kind": "review_request", "limit": 5},
    )
    if not queued:
        raise StepFailed("no review_request queued after the sale")
    results.append(("2 review_request queued", queued[0]["message"][:60] + "..."))

    # 3 - run the reminder check
    _call("POST", "/marketing/segments/rebuild", params={"store_id": store_id})
    run = _call("POST", "/marketing/reminders/run", params={"store_id": store_id, "llm_budget": 0})
    outbox = _call(
        "GET", "/marketing/reminders", params={"store_id": store_id, "status": "queued", "limit": 300}
    )
    kinds = sorted({reminder["kind"] for reminder in outbox})
    if not kinds:
        raise StepFailed("outbox is still empty after a reminder run")
    results.append(("3 reminder check", f"{len(outbox)} queued, kinds: {', '.join(kinds)}"))

    # 4 - three suggestions that reference the seeded numbers
    insights = _call("GET", "/marketing/insights", params={"store_id": store_id, "force": True})
    if len(insights["suggestions"]) != 3:
        raise StepFailed(f"expected 3 suggestions, got {len(insights['suggestions'])}")
    figures = [s.get("figure") or s["title"] for s in insights["suggestions"]]
    results.append(("4 three suggestions", f"[{insights['source']}] " + " | ".join(figures)[:80]))

    # 5 - a campaign with caption and poster
    campaign = _call(
        "POST",
        "/marketing/campaigns",
        params={"store_id": store_id},
        json={"occasion": "Diwali"},
    )
    if not campaign.get("caption") or not campaign.get("image_url"):
        raise StepFailed("campaign has no caption or no image")
    results.append(("5 festival campaign", campaign["caption"][:60] + "..."))

    return [(f"[{vertical}] {label}", detail) for label, detail in results]


def main() -> None:
    parser = argparse.ArgumentParser(description="Rehearse the four-minute demo path")
    parser.add_argument("--stores", nargs="*", type=int, help="store ids to walk")
    args = parser.parse_args()

    try:
        stores = _call("GET", "/config/stores")
    except (httpx.HTTPError, StepFailed) as exc:
        print(f"Cannot reach the API at {BASE}: {exc}")
        sys.exit(2)

    store_ids = args.stores or [store["id"] for store in stores]
    failures = 0
    for store_id in store_ids:
        name = next((s["name"] for s in stores if s["id"] == store_id), str(store_id))
        print(f"\n=== {name} (store {store_id}) ===")
        try:
            for label, detail in walk(store_id):
                print(f"  PASS  {label:<34} {detail}")
        except StepFailed as exc:
            failures += 1
            print(f"  FAIL  {exc}")

    print("\nAll stores passed the four-minute path." if not failures else f"\n{failures} store(s) failed.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
