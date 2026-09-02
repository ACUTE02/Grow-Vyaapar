"""Campaign performance. Attribution, stated honestly."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import api, ui

ctx = ui.page_header("Campaign performance")
if ctx is None:
    st.stop()

store_id = ctx["store_id"]

if st.button("Recompute attribution", type="primary"):
    ok, payload = api.post("/marketing/campaigns/attribution/run", params={"store_id": store_id})
    st.toast(f"Recomputed {payload['campaigns']} campaigns" if ok else str(payload))

body = ui.fetch("/marketing/campaigns/performance", {"store_id": store_id})
if body is None:
    st.stop()

st.warning(
    f"**How to read this.** {body['method']}. A customer who was messaged after a "
    f"campaign went out and then bought within {body['window_days']} days is counted "
    "against it. There is no control group in a single shop, so this shows association, "
    "not proof that the campaign caused the sale."
)

campaigns = body.get("campaigns") or []
if not campaigns:
    ui.empty_state(
        "No campaigns to measure yet.",
        "Draft one on the Campaigns page, send some messages from the Outbox, then come back.",
    )
    st.stop()

totals = st.columns(4)
totals[0].metric("Campaigns", len(campaigns))
totals[1].metric("Customers reached", sum(row["customers_reached"] for row in campaigns))
totals[2].metric("Visits attributed", sum(row["visits_attributed"] for row in campaigns))
totals[3].metric(
    "Revenue attributed", ui.money(sum(row["revenue_attributed"] for row in campaigns))
)

frame = pd.DataFrame(campaigns)
frame["revenue_attributed"] = frame["revenue_attributed"].map(ui.money)
frame["conversion_rate"] = frame["conversion_rate"].map(lambda value: f"{value:.0%}")
st.dataframe(
    frame[
        ["occasion", "status", "created_at", "messages_sent", "customers_reached",
         "visits_attributed", "conversion_rate", "revenue_attributed", "coupons_redeemed"]
    ].rename(columns={"created_at": "drafted"}),
    hide_index=True,
    use_container_width=True,
    height=380,
)

st.divider()
st.subheader("Coupons")
coupons = ui.fetch("/loyalty/coupons", {"store_id": store_id, "limit": 50})
if coupons:
    st.dataframe(
        pd.DataFrame(coupons)[
            ["code", "discount_type", "discount_value", "times_redeemed",
             "max_redemptions", "valid_to", "is_active"]
        ],
        hide_index=True,
        use_container_width=True,
    )
elif coupons is not None:
    ui.empty_state("No coupons yet.", "Create one from the Campaigns page.")

st.subheader("Referrals")
referrals = ui.fetch("/loyalty/referrals", {"store_id": store_id, "limit": 50})
if referrals:
    st.dataframe(
        pd.DataFrame(referrals)[
            ["code", "referrer_name", "referred_customer_id", "status", "rewarded_at"]
        ],
        hide_index=True,
        use_container_width=True,
    )
elif referrals is not None:
    ui.empty_state(
        "No referral codes issued yet.",
        "Open a customer on the Customers page and press 'Issue referral code'.",
    )
