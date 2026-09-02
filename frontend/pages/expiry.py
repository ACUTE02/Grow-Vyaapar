"""Expiring stock. Present only for verticals whose expiry flag is on."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import ui

ctx = ui.page_header("Expiring soon")
if ctx is None:
    st.stop()

store_id = ctx["store_id"]
window = ctx["config"].get("near_expiry_days")

st.caption(
    "This page is in the sidebar because this vertical has the expiry flag on. "
    + (
        f"Its alert window is {window} days - a chemist and a baker need very "
        "different warnings, and that number is a config row, not a branch."
        if window is not None
        else "This vertical tracks batches but sets no alert window, so everything "
        "dated is listed and nothing is flagged."
    )
)

override = st.slider(
    "Show batches expiring within (days)",
    min_value=3,
    max_value=365,
    value=int(window) if window else 90,
    step=1,
)

body = ui.fetch("/products/expiring", {"store_id": store_id, "within_days": override})
if body is None:
    st.stop()

if not body.get("tracks_expiry"):
    ui.empty_state("This store does not track batches.", "Switch to a vertical with the expiry flag on.")
    st.stop()

batches = body.get("batches") or []
if not batches:
    ui.empty_state("No batch expires inside that window.", "Widen the slider.")
    st.stop()

row = st.columns(3)
row[0].metric("Batches in window", len(batches))
row[1].metric("Already expired", body.get("expired_count", 0))
row[2].metric(
    "Value at risk",
    ui.money(sum(item["value"] for item in batches if not item["is_expired"])),
)

if body.get("expired_count"):
    st.error(
        f"{body['expired_count']} batch(es) are already past their expiry date. "
        "Pull them off the shelf before anything else."
    )

frame = pd.DataFrame(batches)
st.dataframe(
    frame[["sku", "name", "batch_no", "expiry_date", "days_left", "qty", "value", "is_expired"]]
    .rename(columns={"qty": f"qty ({ctx['unit_labels']['default']})", "is_expired": "expired"}),
    hide_index=True,
    use_container_width=True,
    height=420,
)

st.info(
    "Sales pick from these batches first-expired-first-out, so the oldest stock "
    "leaves the shelf before the newest without anyone deciding at the counter."
)
if st.button("Build a campaign around this stock"):
    ui.goto("pages/campaigns.py")
