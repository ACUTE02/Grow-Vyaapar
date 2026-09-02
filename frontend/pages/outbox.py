"""Outbox: everything the reminder agent decided to send, and why."""
from __future__ import annotations

import streamlit as st

from lib import api, ui

ctx = ui.page_header("Outbox")
if ctx is None:
    st.stop()

store_id = ctx["store_id"]

st.caption(
    "The agent evaluates this vertical's reminder rules. A different vertical has "
    "different rules enabled, so a different set of kinds appears here."
)

rules = ui.fetch(f"/config/stores/{store_id}/reminder-rules") or []
if rules:
    with st.expander("Rules active for this vertical", expanded=False):
        st.dataframe(
            [
                {
                    "kind": rule["kind"],
                    "signal": rule["signal"],
                    "template": rule["template_key"],
                    "channel": rule["channel"],
                    "enabled": rule["enabled"],
                }
                for rule in rules
            ],
            hide_index=True,
            use_container_width=True,
        )

controls = st.columns([2, 2, 2, 2])
if controls[0].button("Run reminder check", type="primary", use_container_width=True):
    ok, payload = api.post("/marketing/reminders/run", params={"store_id": store_id})
    if ok:
        st.success(f"Queued {payload['total']}: {payload['created'] or 'nothing new'}")
    else:
        ui.error_state(str(payload))

status = controls[1].selectbox("Status", ["queued", "sent", "failed", "dismissed", "all"])
kinds = sorted({rule["kind"] for rule in rules}) if rules else []
kind = controls[2].selectbox("Kind", ["all"] + kinds)
limit = controls[3].number_input("Rows", min_value=10, max_value=300, value=50, step=10)

reminders = ui.fetch(
    "/marketing/reminders",
    {
        "store_id": store_id,
        "status": None if status == "all" else status,
        "kind": None if kind == "all" else kind,
        "limit": int(limit),
    },
)

if reminders is None:
    st.stop()

if not reminders:
    ui.empty_state(
        "The outbox is empty for these filters.",
        "Press 'Run reminder check', or complete a sale on the POS page and come back.",
    )
else:
    st.caption(f"{len(reminders)} message(s)")
    for reminder in reminders:
        with st.container(border=True):
            head = st.columns([3, 2, 2, 2])
            head[0].markdown(
                f"**{reminder['customer_name']}**  \n`{reminder['phone']}`"
            )
            head[1].markdown(f"`{reminder['kind']}`  \n{reminder['channel']}")
            head[2].markdown(
                f"{reminder['status']}  \n{(reminder['scheduled_for'] or '')[:16].replace('T', ' ')}"
            )
            if reminder["status"] == "queued":
                if head[3].button("Send", key=f"send_{reminder['id']}", use_container_width=True):
                    ok, payload = api.post(
                        f"/marketing/reminders/{reminder['id']}/send",
                        params={"store_id": store_id},
                    )
                    st.toast("Sent" if ok else str(payload))
                    st.rerun()
                if head[3].button(
                    "Dismiss", key=f"dismiss_{reminder['id']}", use_container_width=True
                ):
                    api.post(
                        f"/marketing/reminders/{reminder['id']}/dismiss",
                        params={"store_id": store_id},
                    )
                    st.rerun()
            st.write(reminder["message"])
