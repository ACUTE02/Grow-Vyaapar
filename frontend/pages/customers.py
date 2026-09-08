"""Customers: search, segment filter, add, edit, and the append-only record log."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from lib import api, ui

SEGMENTS = ["All", "New", "Regular", "VIP", "Inactive"]

ctx = ui.page_header("Customers")
if ctx is None:
    st.stop()

store_id = ctx["store_id"]
store_name = ctx["store_name"]


def _as_date(value) -> date | None:
    """API dates arrive as ISO strings, or not at all. Never invent one."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _iso(value: date | None) -> str | None:
    return str(value) if value else None


def _valid_mobile(value: str) -> str | None:
    """The same rule the API enforces: ten digits, starting 6-9."""
    digits = "".join(character for character in value if character.isdigit())[-10:]
    return digits if len(digits) == 10 and digits[0] in "6789" else None


def _would_hide(search: str, customer: dict) -> bool:
    """True when the current search no longer matches this customer, which is
    how a just-saved customer disappears from an otherwise correct list."""
    needle = (search or "").strip().lower()
    if not needle:
        return False
    return needle not in customer["name"].lower() and needle not in customer["phone"].lower()


# A message set just before a rerun, shown once on the way back. Without this
# the success toast is wiped by the rerun that refreshes the list, which is
# what made a successful save look like it had failed.
flash = st.session_state.pop("customer_flash", None)
if flash:
    st.success(flash)

# Every query on this page is scoped to this store, so say which one plainly.
st.info(f"**Current store: {store_name}.** Customers are stored per store - "
        "a customer added here is only visible while this store is selected.")

# After a save, point the filters at the customer just saved. Applied here,
# before the widgets exist: a widget's state cannot be assigned afterwards.
# Clearing the search is not enough on its own - the list is one page of 50
# ordered by name, so a new customer can still be off the end of it.
retarget = st.session_state.pop("customer_filter_to", None)
if retarget is not None:
    st.session_state["customer_search"] = retarget
    st.session_state["customer_segment"] = "All"

filters = st.columns([3, 2, 2])
query = filters[0].text_input("Search", placeholder="name or phone", key="customer_search")
segment = filters[1].selectbox(
    "Segment", SEGMENTS, index=SEGMENTS.index(st.session_state.get("customer_segment", "All"))
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
        f"No customer matches those filters in {store_name}.",
        "Customers are not shared between stores, so check the store selector in the "
        "sidebar if you expected to find someone added elsewhere. Otherwise clear the "
        "search, or rebuild segments from the Dashboard if the segment filter is empty "
        "for every value.",
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

    # Keep the open customer open across the reruns that follow a save.
    customer_ids = [customer["id"] for customer in customers]
    remembered = st.session_state.get("selected_customer_id")
    chosen = st.selectbox(
        "Open a customer",
        customer_ids,
        index=customer_ids.index(remembered) if remembered in customer_ids else 0,
        format_func=lambda value: next(
            f"{c['name']} · {c['phone']}" for c in customers if c["id"] == value
        ),
    )
    st.session_state["selected_customer_id"] = chosen
    detail_left, detail_right = st.columns([2, 3], gap="large")

    with detail_left:
        current = next(c for c in customers if c["id"] == chosen)

        with st.expander("Edit details"):
            # Identity is correctable in place. The record log below is not:
            # there a correction is a new row, and that stays true.
            with st.form(f"edit_customer_{chosen}"):
                edit_columns = st.columns(2)
                new_name = edit_columns[0].text_input("Name", value=current["name"])
                new_phone = edit_columns[1].text_input("Phone", value=current["phone"])
                edit_dates = st.columns(2)
                new_dob = edit_dates[0].date_input(
                    "Date of birth",
                    value=_as_date(current.get("dob")),
                    format="DD/MM/YYYY",
                    min_value=date(1900, 1, 1),
                )
                new_anniversary = edit_dates[1].date_input(
                    "Anniversary",
                    value=_as_date(current.get("anniversary")),
                    format="DD/MM/YYYY",
                    min_value=date(1900, 1, 1),
                )
                new_notes = st.text_area("Notes", value=current.get("notes") or "")

                if st.form_submit_button("Save changes", type="primary"):
                    name = new_name.strip()
                    phone = _valid_mobile(new_phone)
                    if len(name) < 2:
                        ui.error_state("A customer needs a name of at least 2 characters.")
                    elif phone is None:
                        ui.error_state(
                            f"'{new_phone}' is not a 10-digit Indian mobile number "
                            "starting with 6-9."
                        )
                    else:
                        # Only what actually changed: the API applies a partial
                        # update, so an untouched field is never overwritten.
                        candidate = {
                            "name": name,
                            "phone": phone,
                            "dob": _iso(new_dob),
                            "anniversary": _iso(new_anniversary),
                            "notes": new_notes.strip() or None,
                        }
                        changes = {
                            key: value
                            for key, value in candidate.items()
                            if value != (
                                _iso(_as_date(current.get(key)))
                                if key in ("dob", "anniversary")
                                else current.get(key)
                            )
                        }
                        if not changes:
                            st.info("Nothing to update - no field changed.")
                        else:
                            ok, payload = api.patch(
                                f"/customers/{chosen}",
                                params={"store_id": store_id},
                                json=changes,
                            )
                            if ok:
                                st.session_state["selected_customer_id"] = payload["id"]
                                if _would_hide(query, payload):
                                    # e.g. the phone was searched for and then
                                    # corrected - follow it rather than lose it.
                                    st.session_state["customer_filter_to"] = payload["phone"]
                                st.session_state["customer_flash"] = (
                                    f"{payload['name']} was updated at {store_name}."
                                )
                                st.rerun()
                            else:
                                ui.error_state(str(payload))

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

        st.subheader("Loyalty")
        loyalty = ui.fetch(f"/loyalty/customers/{chosen}", {"store_id": store_id})
        if loyalty:
            points = st.columns(2)
            points[0].metric("Points", loyalty["points_balance"])
            points[1].metric("Lifetime", loyalty["lifetime_points"])
            st.caption(
                f"One point per {ui.money(loyalty['rupees_per_point'])} spent, worth "
                f"{ui.money(loyalty['point_value'])} at the counter. The balance is the "
                "sum of the ledger, never edited on its own."
            )
            if loyalty["ledger"]:
                with st.expander("Points ledger"):
                    st.dataframe(
                        pd.DataFrame(loyalty["ledger"])[
                            ["created_at", "points_delta", "reason", "transaction_id"]
                        ],
                        hide_index=True,
                        use_container_width=True,
                    )
        if st.button("Issue referral code"):
            ok, payload = api.post(f"/loyalty/referrals/{chosen}", params={"store_id": store_id})
            if ok:
                st.success(f"Referral code: {payload['code']}")
            else:
                ui.error_state(str(payload))

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
with st.expander(f"Add a customer to {store_name}"):
    with st.form("add_customer"):
        st.caption(f"This customer will belong to **{store_name}** and will not be "
                   "visible under any other store.")
        columns = st.columns(2)
        name = columns[0].text_input("Name")
        phone = columns[1].text_input("Phone", placeholder="10 digits, starts 6-9")
        dates = st.columns(2)
        dob = dates[0].date_input(
            "Date of birth", value=None, format="DD/MM/YYYY", min_value=date(1900, 1, 1)
        )
        anniversary = dates[1].date_input(
            "Anniversary", value=None, format="DD/MM/YYYY", min_value=date(1900, 1, 1)
        )
        if st.form_submit_button("Save customer", type="primary"):
            ok, payload = api.post(
                "/customers",
                params={"store_id": store_id},
                json={
                    "name": name,
                    "phone": phone,
                    "dob": _iso(dob),
                    "anniversary": _iso(anniversary),
                },
            )
            if ok:
                # Open the new customer and filter the list to them. A stale
                # search or segment filter - or simply page one of fifty names -
                # is the usual reason a just-added customer looks missing.
                st.session_state["selected_customer_id"] = payload["id"]
                st.session_state["customer_filter_to"] = payload["phone"]
                st.session_state["customer_flash"] = (
                    f"Customer {payload['name']} was successfully added to "
                    f"{store_name}. The list below is filtered to show them - "
                    "clear the search to see everyone."
                )
                st.rerun()
            else:
                ui.error_state(str(payload))
