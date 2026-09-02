"""Campaigns: an occasion plus overstocked SKUs becomes a caption and a poster."""
from __future__ import annotations

import streamlit as st

from lib import api, ui

ctx = ui.page_header("Campaigns")
if ctx is None:
    st.stop()

store_id = ctx["store_id"]
profile = ctx["prompt_profile"]

st.caption(
    f"Tone for this vertical: {profile.get('tone')}. The copy generator is told never "
    f"to write: {', '.join(profile.get('forbidden', []))}."
)

with st.form("new_campaign"):
    columns = st.columns([3, 1])
    occasion = columns[0].text_input(
        "Occasion", placeholder="Diwali, Eid, Onam, Republic Day, monsoon sale…"
    )
    submitted = columns[1].form_submit_button("Generate", type="primary")
    if submitted:
        if not occasion.strip():
            ui.error_state("Type an occasion first.")
        else:
            with st.spinner("Drafting caption and poster…"):
                ok, payload = api.post(
                    "/marketing/campaigns",
                    params={"store_id": store_id},
                    json={"occasion": occasion},
                )
            if ok:
                st.success(f"Drafted a campaign for {payload['occasion']}")
            else:
                ui.error_state(str(payload))

campaigns = ui.fetch("/marketing/campaigns", {"store_id": store_id, "limit": 12})
if campaigns is None:
    st.stop()

if not campaigns:
    ui.empty_state(
        "No campaigns yet.",
        "Type an occasion above and press Generate. The agent picks the three SKUs "
        "that have been sitting longest.",
    )
else:
    for campaign in campaigns:
        with st.container(border=True):
            left, right = st.columns([2, 3], gap="large")
            with left:
                if campaign.get("image_url"):
                    st.image(campaign["image_url"], use_container_width=True)
                    st.caption("Poster generated from the visual prompt below.")
            with right:
                st.markdown(f"### {campaign['occasion']}")
                st.write(campaign.get("caption") or "_No caption_")
                st.write(" ".join(campaign.get("hashtags") or []))
                with st.expander("Visual prompt"):
                    st.code(campaign.get("prompt") or "", language=None)

                status_columns = st.columns(3)
                for index, next_status in enumerate(["draft", "saved", "published"]):
                    disabled = campaign["status"] == next_status
                    if status_columns[index].button(
                        next_status.capitalize(),
                        key=f"status_{campaign['id']}_{next_status}",
                        disabled=disabled,
                        use_container_width=True,
                    ):
                        ok, payload = api.patch(
                            f"/marketing/campaigns/{campaign['id']}",
                            params={"store_id": store_id},
                            json={"status": next_status},
                        )
                        st.toast(f"Marked {next_status}" if ok else str(payload))
                        st.rerun()
                st.caption(f"Status: {campaign['status']} · created {campaign['created_at'][:16]}")
