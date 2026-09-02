"""Expiry. This page exists only for verticals whose expiry feature flag is on."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import ui

ctx = ui.page_header("Expiry")
if ctx is None:
    st.stop()

st.caption(
    "This page is in the sidebar because this vertical has the expiry flag on. "
    "Batch handling beyond this list is out of scope for this phase."
)

within = st.slider("Expiring within (days)", min_value=30, max_value=720, value=180, step=30)
batches = ui.fetch(
    "/products/expiring", {"store_id": ctx["store_id"], "within_days": within, "limit": 200}
)

if batches is None:
    st.stop()
if not batches:
    ui.empty_state("No batch expires inside that window.", "Widen the slider.")
else:
    frame = pd.DataFrame(batches)
    st.dataframe(
        frame[["sku", "name", "batch_no", "expiry_date", "days_left", "qty"]],
        hide_index=True,
        use_container_width=True,
        height=420,
    )
    soon = frame[frame["days_left"] <= 60]
    if not soon.empty:
        st.warning(f"{len(soon)} batch(es) expire within 60 days.")
