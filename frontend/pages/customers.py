"""Customers: search, segment filter, add, and the append-only record log."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import api, ui

ctx = ui.page_header("Customers")
if ctx is None:
    st.stop()

store_id = ctx["store_id"]

filters = st.columns([3, 2, 2])
query = filters[0].text_input("Search", placeholder="name or phone")
segment = filters[1].selectbox(
    "Segment", ["All", "New", "Regular", "VIP", "Inactive"],
    index=["All", "New", "Regular", "VIP", "Inactive"].index(
        st.session_state.get("customer_segment", "All")
    ),
)
st.session_state["customer_segment"] = segment
limit = filters[2].number_input("Rows", min_value=10, max_value=500, value=50, step=10)

customers = ui.fetch(
    "/customers",
    {
        "store_id": store_id,
        "q": query or None,
        "segment": None if segment == "All" else segment,
        "limit": int(limit),
    },
)

if customers is None:
    st.stop()

if not customers:
    ui.empty_state(
        "No customer matches those filters.",
        "Clear the search, or rebuild segments from the Dashboard if the segment "
        "filter is empty for every value.",
    )
else:
    frame = pd.DataFrame(customers)
    frame["total_spend"] = frame["total_spend"].fillna(0).map(ui.money)
    st.dataframe(
        frame[
            ["name", "phone", "segment", "recency_days", "visits", "total_spend",
             "marketing_opt_in"]
        ].rename(
            columns={
                "recency_days": "days since visit",
                "total_spend": "lifetime spend",
                "marketing_opt_in": "messages ok",
            }
        ),
        hide_index=True,
        use_container_width=True,
        height=380,
    )

    chosen = st.selectbox(
        "Open a customer",
        [customer["id"] for customer in customers],
        format_func=lambda value: next(
            f"{c['name']} · {c['phone']}" for c in customers if c["id"] == value
        ),
    )
    detail_left, detail_right = st.columns([2, 3], gap="large")

    with detail_left:
        current = next(c for c in customers if c["id"] == chosen)
        st.subheader("Consent")
        opted_in = st.toggle(
            "Send marketing messages to this customer",
            value=bool(current.get("marketing_opt_in", True)),
            key=f"consent_{chosen}",
        )
        if opted_in != bool(current.get("marketing_opt_in", True)):
            ok, payload = api.patch(
                f"/customers/{chosen}",
                params={"store_id": store_id},
                json={"marketing_opt_in": opted_in},
            )
            st.toast("Consent updated" if ok else str(payload))
            st.rerun()
        st.caption(
            "An opted-out customer is skipped when messages are drafted, and refused "
            "again at send time."
        )

        st.subheader("Recent bills")
        bills = ui.fetch(
            "/billing/transactions",
            {"store_id": store_id, "customer_id": chosen, "limit": 10},
        )
        if bills:
            st.dataframe(
                pd.DataFrame(bills)[["invoice_no", "created_at", "total", "status"]],
                hide_index=True,
                use_container_width=True,
            )
        elif bills is not None:
            ui.empty_state("This customer has not bought anything yet.")

    with detail_right:
        st.subheader("Records")
        st.caption("Append-only: a correction is a new row, never an edit.")
        records = ui.fetch(f"/customers/{chosen}/records", {"store_id": store_id})
        if records:
            st.dataframe(
                pd.DataFrame(records)[["recorded_on", "record_type", "data"]],
                hide_index=True,
                use_container_width=True,
            )
        elif records is not None:
            ui.empty_state("No records for this customer.")

        with st.form("add_record"):
            record_type = st.text_input("Record type", placeholder="prescription, measurement…")
            note = st.text_area("Note")
            if st.form_submit_button("Add record") and record_type:
                ok, payload = api.post(
                    f"/customers/{chosen}/records",
                    params={"store_id": store_id},
                    json={"record_type": record_type, "data": {"note": note}},
                )
                st.toast("Record added" if ok else str(payload))
                if ok:
                    st.rerun()

st.divider()
with st.expander("Add a customer"):
    with st.form("add_customer"):
        columns = st.columns(2)
        name = columns[0].text_input("Name")
        phone = columns[1].text_input("Phone", placeholder="10 digits, starts 6-9")
        dates = st.columns(2)
        dob = dates[0].date_input("Date of birth", value=None, format="DD/MM/YYYY")
        anniversary = dates[1].date_input("Anniversary", value=None, format="DD/MM/YYYY")
        if st.form_submit_button("Save customer", type="primary"):
            ok, payload = api.post(
                "/customers",
                params={"store_id": store_id},
                json={
                    "name": name,
                    "phone": phone,
                    "dob": str(dob) if dob else None,
                    "anniversary": str(anniversary) if anniversary else None,
                },
            )
            if ok:
                st.success(f"Added {payload['name']}")
                st.rerun()
            else:
                ui.error_state(str(payload))
