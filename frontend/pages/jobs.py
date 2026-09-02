"""Jobs. This page exists only for verticals whose jobs feature flag is on."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import ui

ctx = ui.page_header("Jobs")
if ctx is None:
    st.stop()

st.caption(
    "This page is in the sidebar because this vertical has the jobs flag on. "
    "Switch to a store without it and the page disappears - no code change."
)

status = st.selectbox("Status", ["all", "pending", "in_progress", "ready", "delivered"])
jobs = ui.fetch(
    "/billing/jobs",
    {"store_id": ctx["store_id"], "status": None if status == "all" else status},
)

if jobs is None:
    st.stop()
if not jobs:
    ui.empty_state("No jobs with that status.", "Try 'all', or seed the demo data.")
else:
    st.dataframe(
        pd.DataFrame(jobs)[
            ["customer_name", "type", "status", "promised_date", "ready_at", "delivered_at"]
        ],
        hide_index=True,
        use_container_width=True,
    )
    ready = [job for job in jobs if job["status"] == "ready"]
    if ready:
        st.info(
            f"{len(ready)} job(s) are ready. The reminder agent turns each of these into a "
            "pickup_ready message in the Outbox."
        )
