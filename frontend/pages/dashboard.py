"""Dashboard: the numbers, then three suggestions that quote them."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import api, ui

ctx = ui.page_header("Dashboard")
if ctx is None:
    st.stop()

store_id = ctx["store_id"]
unit = ctx["unit_labels"]["default"]

controls = st.columns([1, 1, 1, 3])
if controls[0].button("Rebuild segments", use_container_width=True):
    ok, payload = api.post("/marketing/segments/rebuild", params={"store_id": store_id})
    st.toast("Segments rebuilt" if ok else str(payload))
if controls[1].button("Run reminder check", use_container_width=True):
    ok, payload = api.post("/marketing/reminders/run", params={"store_id": store_id})
    st.toast(f"Queued {payload['total']} reminders" if ok else str(payload))
if controls[2].button("Refresh suggestions", use_container_width=True):
    ui.fetch("/marketing/insights", {"store_id": store_id, "force": True})
    st.toast("Suggestions refreshed")

summary = ui.fetch("/analytics/summary", {"store_id": store_id, "days": 30})
insights = ui.fetch("/marketing/insights", {"store_id": store_id})
segments = ui.fetch("/marketing/segments/summary", {"store_id": store_id}) or {}

if summary is None or insights is None:
    st.stop()

# -- headline figures --------------------------------------------------------
metrics = insights.get("metrics", {})
row = st.columns(4)
row[0].metric("Sales, last 30 days", ui.money(summary["net_total"]))
row[1].metric("Invoices", f"{summary['invoices']:,}")
row[2].metric("Average bill", ui.money(summary["average_bill"]))
row[3].metric(
    "This week vs last",
    ui.money(metrics.get("week_sales", 0)),
    f"{metrics.get('week_over_week_change_pct', 0)}%",
)

# -- charts ------------------------------------------------------------------
left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader("Sales trend")
    series = summary.get("series") or []
    if not series:
        ui.empty_state(
            "No sales in this window.",
            "Ring up a sale on the POS page, or seed the demo data.",
        )
    else:
        frame = pd.DataFrame(series)
        frame["date"] = pd.to_datetime(frame["date"])
        st.line_chart(frame.set_index("date")["net"], height=260)

with right:
    st.subheader("Customer segments")
    if not any(segments.values()):
        ui.empty_state("Segments have not been computed yet.", "Press 'Rebuild segments'.")
    else:
        st.bar_chart(pd.Series(segments, name="customers"), height=260)

# -- suggestions -------------------------------------------------------------
st.subheader("What the agent suggests")
source = insights.get("source", "template")
st.caption(
    {
        "llm": "Written by the model from figures computed in SQL.",
        "template": "No LLM key configured - written by the fallback, same figures.",
        "cache": "Served from the cached insight row (refreshed every 24 hours).",
    }.get(source, source)
)

suggestions = insights.get("suggestions") or []
if not suggestions:
    ui.empty_state("No suggestions yet.", "Press 'Refresh suggestions'.")
else:
    columns = st.columns(len(suggestions))
    targets = {
        "low_stock": ("Open low stock", "pages/catalog.py", {"catalog_tab": "low"}),
        "dead_stock": ("Open dead stock", "pages/catalog.py", {"catalog_tab": "dead"}),
        "customers": ("Open customers", "pages/customers.py", {}),
        "outbox": ("Open outbox", "pages/outbox.py", {}),
        "campaigns": ("Open campaigns", "pages/campaigns.py", {}),
    }
    for column, suggestion in zip(columns, suggestions):
        with column.container(border=True):
            st.markdown(f"**{suggestion['title']}**")
            st.write(suggestion["detail"])
            if suggestion.get("figure"):
                st.caption(f"Figure: {suggestion['figure']}")
            label, page, state = targets.get(
                suggestion.get("action") or "", ("Open customers", "pages/customers.py", {})
            )
            if st.button(label, key=f"suggestion_{suggestion['title'][:20]}"):
                ui.goto(page, **state)

# -- the two stock lists -----------------------------------------------------
stock_left, stock_right = st.columns(2, gap="large")
with stock_left:
    st.subheader("Low stock")
    rows = ui.fetch("/products/low-stock", {"store_id": store_id, "limit": 10})
    if rows:
        st.dataframe(
            pd.DataFrame(rows)[["sku", "name", "qty_on_hand", "reorder_point"]].rename(
                columns={"qty_on_hand": f"on hand ({unit})", "reorder_point": "reorder at"}
            ),
            hide_index=True,
            use_container_width=True,
        )
    elif rows is not None:
        ui.empty_state("Nothing is below its reorder point.")

with stock_right:
    st.subheader(f"Dead stock (over {ctx['config'].get('dead_stock_days')} days)")
    rows = ui.fetch("/products/dead-stock", {"store_id": store_id, "limit": 10})
    if rows:
        st.dataframe(
            pd.DataFrame(rows)[["sku", "name", "qty_on_hand", "days_since_sold"]].rename(
                columns={"qty_on_hand": f"on hand ({unit})", "days_since_sold": "days idle"}
            ),
            hide_index=True,
            use_container_width=True,
        )
    elif rows is not None:
        ui.empty_state("Every SKU has sold inside this store's window.")
