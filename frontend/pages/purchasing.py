"""Suppliers, purchase orders and receiving. Manager and above only."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from lib import api, ui

ctx = ui.page_header("Purchasing")
if ctx is None:
    st.stop()

store_id = ctx["store_id"]
unit = ctx["unit_labels"]["default"]
tracks_expiry = ctx["feature_flags"].get("expiry", False)

pending = ui.fetch("/purchasing/pending-payments", {"store_id": store_id}) or {}
top = st.columns(3)
top[0].metric("Unpaid orders", pending.get("orders", 0))
top[1].metric("Owed to suppliers", ui.money(pending.get("amount", 0)))
top[2].caption(
    "Receiving an order raises stock"
    + (" and creates a batch per line." if tracks_expiry else ".")
)

suppliers_tab, orders_tab, audit_tab = st.tabs(["Suppliers", "Purchase orders", "Audit trail"])

# -- suppliers ---------------------------------------------------------------
with suppliers_tab:
    suppliers = ui.fetch("/purchasing/suppliers", {"store_id": store_id}) or []
    if suppliers:
        st.dataframe(
            pd.DataFrame(suppliers)[
                ["name", "phone", "gstin", "rating", "orders", "total_ordered"]
            ],
            hide_index=True,
            use_container_width=True,
        )
    else:
        ui.empty_state("No suppliers yet.", "Add the first one below.")

    with st.form("new_supplier"):
        fields = st.columns(4)
        name = fields[0].text_input("Name")
        phone = fields[1].text_input("Phone")
        gstin = fields[2].text_input("GSTIN")
        rating = fields[3].number_input("Rating", min_value=0.0, max_value=5.0, step=0.5, value=4.0)
        if st.form_submit_button("Add supplier", type="primary") and name:
            ok, payload = api.post(
                "/purchasing/suppliers",
                params={"store_id": store_id},
                json={"name": name, "phone": phone or None, "gstin": gstin or None,
                      "rating": rating},
            )
            if ok:
                st.success(f"Added {payload['name']}")
                st.rerun()
            else:
                ui.error_state(str(payload))

# -- purchase orders ---------------------------------------------------------
with orders_tab:
    orders = ui.fetch("/purchasing/orders", {"store_id": store_id, "limit": 100}) or []
    if orders:
        frame = pd.DataFrame(orders)
        frame["total"] = frame["total"].map(ui.money)
        st.dataframe(
            frame[["id", "supplier_name", "status", "lines", "total", "is_paid",
                   "ordered_at", "received_at"]],
            hide_index=True,
            use_container_width=True,
        )
        open_orders = [order for order in orders if order["status"] == "ordered"]
        if open_orders:
            action = st.columns([3, 2, 2])
            chosen = action[0].selectbox(
                "Order",
                [order["id"] for order in open_orders],
                format_func=lambda value: next(
                    f"#{o['id']} · {o['supplier_name']} · {ui.money(o['total'])}"
                    for o in open_orders
                    if o["id"] == value
                ),
            )
            if action[1].button("Receive stock", type="primary", use_container_width=True):
                ok, payload = api.post(
                    f"/purchasing/orders/{chosen}/receive", params={"store_id": store_id}
                )
                if ok:
                    st.success(
                        f"Received {payload['lines_received']} line(s), "
                        f"{payload['batches_created']} batch(es) created"
                    )
                    st.rerun()
                else:
                    ui.error_state(str(payload))
            if action[2].button("Mark paid", use_container_width=True):
                ok, payload = api.post(
                    f"/purchasing/orders/{chosen}/pay", params={"store_id": store_id}
                )
                st.toast("Marked paid" if ok else str(payload))
                st.rerun()
    else:
        ui.empty_state("No purchase orders yet.", "Raise one below from a reorder suggestion.")

    st.divider()
    st.subheader("Raise an order")
    reorder = ui.fetch(
        "/ml/forecast/stock", {"store_id": store_id, "view": "reorder", "limit": 25}
    ) or []
    if reorder:
        st.caption(
            "Quantities are pre-filled from the forecast: velocity over the reorder "
            "cycle, with a safety margin, rounded to pack size."
        )
    products = ui.fetch("/products", {"store_id": store_id, "limit": 300}) or []
    supplier_options = {supplier["id"]: supplier["name"] for supplier in suppliers}

    if not supplier_options or not products:
        ui.empty_state("Add a supplier and at least one product first.")
    else:
        with st.form("new_order"):
            head = st.columns(2)
            supplier_id = head[0].selectbox(
                "Supplier", list(supplier_options),
                format_func=lambda value: supplier_options[value],
            )
            suggested = {row["sku"]: row for row in reorder}
            product_options = {
                product["id"]: f"{product['name']} ({product['sku']})" for product in products
            }
            default = [
                product["id"] for product in products if product["sku"] in suggested
            ][:5]
            chosen_products = head[1].multiselect(
                "Products",
                list(product_options),
                default=default,
                format_func=lambda value: product_options[value],
            )

            lines = []
            for product_id in chosen_products:
                product = next(item for item in products if item["id"] == product_id)
                row = st.columns([3, 2, 2, 2])
                row[0].markdown(f"**{product['name']}**  \n`{product['sku']}`")
                hint = suggested.get(product["sku"], {})
                qty = row[1].number_input(
                    f"Qty ({unit})",
                    min_value=1.0,
                    value=float(hint.get("suggested_reorder_qty") or 10),
                    key=f"po_qty_{product_id}",
                )
                cost = row[2].number_input(
                    "Unit cost",
                    min_value=0.0,
                    value=float(product["cost_price"]),
                    key=f"po_cost_{product_id}",
                )
                line = {"product_id": product_id, "qty": qty, "unit_cost": cost}
                if tracks_expiry:
                    expiry = row[3].date_input(
                        "Expiry",
                        value=date.today() + timedelta(days=365),
                        key=f"po_exp_{product_id}",
                    )
                    line["expiry_date"] = str(expiry)
                    line["batch_no"] = f"B{date.today():%y%m}-{product_id}"
                lines.append(line)

            if st.form_submit_button("Create order", type="primary"):
                if not lines:
                    ui.error_state("Pick at least one product.")
                else:
                    ok, payload = api.post(
                        "/purchasing/orders",
                        params={"store_id": store_id},
                        json={"supplier_id": supplier_id, "items": lines},
                    )
                    if ok:
                        st.success(f"Order #{payload['id']} for {ui.money(payload['total'])}")
                        st.rerun()
                    else:
                        ui.error_state(str(payload))

# -- audit -------------------------------------------------------------------
with audit_tab:
    st.caption(
        "Every mutating request leaves a row. Price changes, user edits and stock "
        "receipts also record what the values were before and after."
    )
    trail = ui.fetch("/purchasing/audit", {"store_id": store_id, "limit": 200}) or []
    if trail:
        st.dataframe(
            pd.DataFrame(trail)[
                ["created_at", "action", "entity", "entity_id", "user_id", "before", "after"]
            ],
            hide_index=True,
            use_container_width=True,
            height=460,
        )
    else:
        ui.empty_state("Nothing has been changed yet.")
