"""Reorder suggestions: what to buy, and what is about to stop selling."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import api, ui

ctx = ui.page_header("Reorder suggestions")
if ctx is None:
    st.stop()

store_id = ctx["store_id"]
unit = ctx["unit_labels"]["default"]
cycle = ctx["config"].get("reorder_cycle_days")

st.caption(
    f"Velocity is a day-of-week weighted moving average over this store's own "
    f"lookback window. Anything that runs out inside the {cycle}-day reorder cycle "
    "is listed first. It is a moving average, not a time-series model - the point "
    "is that it is explainable, not that it is clever."
)

if st.button("Recompute forecasts", type="primary"):
    ok, payload = api.post("/ml/forecast/run", params={"store_id": store_id})
    st.toast(
        f"{payload['products']} products, {payload['reorder_soon']} to reorder" if ok
        else str(payload)
    )

buy_tab, risk_tab, all_tab = st.tabs(
    [f"Order now (within {cycle} days)", "Predicted to go stale", "Every product"]
)

with buy_tab:
    rows = ui.fetch("/ml/forecast/stock", {"store_id": store_id, "view": "reorder", "limit": 100})
    if rows:
        frame = pd.DataFrame(rows)
        st.dataframe(
            frame[
                ["sku", "name", "qty_on_hand", "predicted_daily_velocity",
                 "days_to_stockout", "suggested_reorder_qty", "reason"]
            ].rename(
                columns={
                    "qty_on_hand": f"on hand ({unit})",
                    "predicted_daily_velocity": f"{unit}/day",
                    "days_to_stockout": "days left",
                    "suggested_reorder_qty": f"order ({unit})",
                }
            ),
            hide_index=True,
            use_container_width=True,
            height=420,
        )
        st.metric("Lines to raise", len(rows))
    elif rows is not None:
        ui.empty_state(
            "Nothing runs out inside the reorder cycle.",
            "Press 'Recompute forecasts' after a busy day and check again.",
        )

with risk_tab:
    st.caption(
        "These have NOT crossed the dead-stock window yet. That is the difference "
        "between this list and the Catalog dead-stock tab: this one is a prediction."
    )
    rows = ui.fetch("/ml/forecast/stock", {"store_id": store_id, "view": "dead_risk", "limit": 100})
    if rows:
        frame = pd.DataFrame(rows)
        st.dataframe(
            frame[["sku", "name", "qty_on_hand", "predicted_daily_velocity", "reason"]].rename(
                columns={
                    "qty_on_hand": f"on hand ({unit})",
                    "predicted_daily_velocity": f"{unit}/day",
                }
            ),
            hide_index=True,
            use_container_width=True,
            height=420,
        )
        if st.button("Build a campaign around these"):
            ui.goto("pages/campaigns.py")
    elif rows is not None:
        ui.empty_state("Nothing is trending towards dead stock.")

with all_tab:
    rows = ui.fetch("/ml/forecast/stock", {"store_id": store_id, "view": "all", "limit": 500})
    if rows:
        frame = pd.DataFrame(rows)
        st.dataframe(
            frame[
                ["sku", "name", "qty_on_hand", "predicted_daily_velocity",
                 "days_to_stockout", "is_dead_stock_risk", "reason"]
            ],
            hide_index=True,
            use_container_width=True,
            height=520,
        )
    elif rows is not None:
        ui.empty_state("No products in this catalog yet.")
