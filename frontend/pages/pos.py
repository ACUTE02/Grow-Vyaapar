"""Point of sale: build a bill, complete it, watch the agent react."""
from __future__ import annotations

from decimal import Decimal

import streamlit as st

from lib import api, ui

ctx = ui.page_header("Point of sale", "quantities in this store's own unit")
if ctx is None:
    st.stop()

store_id = ctx["store_id"]
unit = ctx["unit_labels"]["default"]
cart: dict[int, dict] = st.session_state.setdefault("cart", {})

left, right = st.columns([3, 2], gap="large")

# --------------------------------------------------------------------------- #
# item picker
# --------------------------------------------------------------------------- #
with left:
    st.subheader("Add items")
    query = st.text_input("Search the catalog", placeholder="name or SKU", key="pos_query")
    products = ui.fetch("/products", {"store_id": store_id, "q": query or None, "limit": 25})

    if products is None:
        st.stop()
    if not products:
        ui.empty_state(
            "No products match that search.",
            "Add stock on the Catalog page, or clear the search box.",
        )
    for product in products:
        row = st.columns([4, 2, 2, 2])
        row[0].markdown(f"**{product['name']}**  \n`{product['sku']}`")
        row[1].markdown(f"{ui.money(product['sell_price'])}  \nGST {product['gst_rate']}%")
        row[2].markdown(f"{float(product['qty_on_hand']):g} {unit}  \nin stock")
        if row[3].button("Add", key=f"add_{product['id']}", use_container_width=True):
            entry = cart.setdefault(
                product["id"],
                {
                    "product_id": product["id"],
                    "name": product["name"],
                    "sku": product["sku"],
                    "unit_price": float(product["sell_price"]),
                    "qty": 0.0,
                    "stock": float(product["qty_on_hand"]),
                },
            )
            entry["qty"] += 1
            st.rerun()

# --------------------------------------------------------------------------- #
# the bill
# --------------------------------------------------------------------------- #
with right:
    st.subheader("Current bill")
    if not cart:
        ui.empty_state("The bill is empty.", "Add an item from the left to start.")
    else:
        subtotal = Decimal("0")
        for product_id, entry in list(cart.items()):
            line = st.columns([4, 3, 1])
            line[0].markdown(f"**{entry['name']}**  \n`{entry['sku']}`")
            entry["qty"] = line[1].number_input(
                f"Qty ({unit})",
                min_value=0.0,
                step=1.0,
                value=float(entry["qty"]),
                key=f"qty_{product_id}",
            )
            if line[2].button("✕", key=f"del_{product_id}"):
                cart.pop(product_id)
                st.rerun()
            subtotal += Decimal(str(entry["qty"])) * Decimal(str(entry["unit_price"]))

        st.metric("Subtotal (before GST)", ui.money(subtotal))

        customers = ui.fetch("/customers", {"store_id": store_id, "limit": 200}) or []
        options = {0: "Walk-in (no customer)"} | {
            customer["id"]: f"{customer['name']} · {customer['phone']}"
            for customer in customers
        }
        customer_id = st.selectbox(
            "Customer", list(options), format_func=lambda value: options[value]
        )
        discount = st.number_input("Bill discount", min_value=0.0, step=10.0, value=0.0)
        payment_mode = st.radio("Payment", ["cash", "upi", "card"], horizontal=True)

        if st.button("Complete sale", type="primary", use_container_width=True):
            lines = [
                {"product_id": entry["product_id"], "qty": entry["qty"]}
                for entry in cart.values()
                if entry["qty"] > 0
            ]
            if not lines:
                ui.error_state("Every line has a quantity of zero.")
            else:
                ok, payload = api.post(
                    "/billing/transactions",
                    params={"store_id": store_id},
                    json={
                        "customer_id": customer_id or None,
                        "lines": lines,
                        "discount": discount,
                        "payment_mode": payment_mode,
                    },
                )
                if not ok:
                    ui.error_state(str(payload))
                else:
                    st.session_state["cart"] = {}
                    st.session_state["last_invoice"] = payload
                    st.rerun()

# --------------------------------------------------------------------------- #
# what the agent did about it
# --------------------------------------------------------------------------- #
invoice = st.session_state.get("last_invoice")
if invoice:
    st.divider()
    st.success(f"Invoice {invoice['invoice_no']} completed - {ui.money(invoice['total'])}")
    columns = st.columns(4)
    columns[0].metric("Subtotal", ui.money(invoice["subtotal"]))
    columns[1].metric("Discount", ui.money(invoice["discount"]))
    columns[2].metric("GST", ui.money(invoice["gst_amount"]))
    columns[3].metric("Total", ui.money(invoice["total"]))

    st.link_button(
        "Open invoice",
        f"{api.BASE_URL}/billing/transactions/{invoice['id']}/invoice.pdf?store_id={store_id}",
    )

    if invoice.get("customer_id"):
        queued = ui.fetch(
            "/marketing/reminders",
            {"store_id": store_id, "status": "queued", "kind": "review_request", "limit": 3},
        )
        if queued:
            st.info(
                "**The marketing agent already reacted.** Nobody asked it to - completing "
                "the sale is the signal it listens for."
            )
            st.markdown(f"> {queued[0]['message']}")
            if st.button("Open the outbox"):
                ui.goto("pages/outbox.py")
