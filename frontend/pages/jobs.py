"""Jobs board. Present only for verticals whose jobs feature flag is on."""
from __future__ import annotations

from datetime import date

import streamlit as st

from lib import api, ui

ctx = ui.page_header("Jobs")
if ctx is None:
    st.stop()

store_id = ctx["store_id"]

board = ui.fetch("/jobs/board", {"store_id": store_id})
if board is None:
    st.stop()

if not board.get("takes_jobs"):
    ui.empty_state(
        "This store does not take jobs.",
        "The jobs feature flag is off for this vertical, so nothing here applies.",
    )
    st.stop()

st.caption(
    "This page is in the sidebar because this vertical has the jobs flag on, and the "
    f"job types below come from its config: {', '.join(board['job_types'])}. "
    "Marking a job ready fires the same pickup_ready rule the nightly run uses."
)

jobs = ui.fetch("/jobs", {"store_id": store_id, "limit": 300}) or []
counts = board["counts"]

columns = st.columns(4)
for column, status in zip(columns, ("pending", "in_progress", "ready", "delivered")):
    column.metric(status.replace("_", " ").title(), counts.get(status, 0))

overdue = [job for job in jobs if job["is_overdue"]]
if overdue:
    st.error(f"{len(overdue)} job(s) are past their promised date.")

# -- the board ---------------------------------------------------------------
board_columns = st.columns(4)
for column, status in zip(board_columns, ("pending", "in_progress", "ready", "delivered")):
    with column:
        st.subheader(status.replace("_", " ").title())
        in_column = [job for job in jobs if job["status"] == status]
        if not in_column:
            st.caption("Nothing here.")
        for job in in_column[:25]:
            with st.container(border=True):
                flag = "🔴 " if job["is_overdue"] else ""
                st.markdown(f"{flag}**{job['customer_name']}**  \n`{job['type']}`")
                if job["promised_date"]:
                    st.caption(f"promised {job['promised_date']}")
                for next_status in job["next_statuses"]:
                    if st.button(
                        f"→ {next_status.replace('_', ' ')}",
                        key=f"job_{job['id']}_{next_status}",
                        use_container_width=True,
                    ):
                        ok, payload = api.post(
                            f"/jobs/{job['id']}/status",
                            params={"store_id": store_id},
                            json={"status": next_status},
                        )
                        if not ok:
                            ui.error_state(str(payload))
                        else:
                            queued = payload.get("reminders_queued", 0)
                            st.toast(
                                f"Marked {next_status}"
                                + (f", {queued} pickup reminder queued" if queued else "")
                            )
                            st.rerun()

cancelled = [job for job in jobs if job["status"] == "cancelled"]
if cancelled:
    with st.expander(f"Cancelled ({len(cancelled)})"):
        st.dataframe(
            [
                {
                    "customer": job["customer_name"],
                    "type": job["type"],
                    "promised": job["promised_date"],
                }
                for job in cancelled
            ],
            hide_index=True,
            use_container_width=True,
        )

# -- book a new job ----------------------------------------------------------
st.divider()
with st.expander("Take a new job"):
    customers = ui.fetch("/customers", {"store_id": store_id, "limit": 200}) or []
    if not customers:
        ui.empty_state("No customers yet.", "Add one on the Customers page first.")
    else:
        with st.form("new_job"):
            fields = st.columns(3)
            options = {c["id"]: f"{c['name']} · {c['phone']}" for c in customers}
            customer_id = fields[0].selectbox(
                "Customer", list(options), format_func=lambda value: options[value]
            )
            job_type = fields[1].selectbox("Type", board["job_types"])
            promised = fields[2].date_input("Promised date", value=date.today())
            if st.form_submit_button("Book job", type="primary"):
                ok, payload = api.post(
                    "/jobs",
                    params={"store_id": store_id},
                    json={
                        "customer_id": customer_id,
                        "type": job_type,
                        "promised_date": str(promised),
                    },
                )
                if ok:
                    st.success(f"Booked {payload['type']} for {options[customer_id]}")
                    st.rerun()
                else:
                    ui.error_state(str(payload))
