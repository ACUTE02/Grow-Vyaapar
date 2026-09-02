"""Catalog. The add-product form is generated from the vertical's product_schema."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import api, ui

ctx = ui.page_header("Catalog")
if ctx is None:
    st.stop()

store_id = ctx["store_id"]
unit = ctx["unit_labels"]["default"]
schema: dict[str, dict] = ctx["product_schema"]

tab_names = ["All products", "Low stock", f"Dead stock (>{ctx['config'].get('dead_stock_days')}d)"]
default_tab = {"low": 1, "dead": 2}.get(st.session_state.pop("catalog_tab", ""), 0)
tabs = st.tabs(tab_names)

with tabs[0]:
    columns = st.columns([3, 2, 2])
    query = columns[0].text_input("Search", placeholder="name or SKU", key="catalog_query")
    categories = ui.fetch("/products/categories", {"store_id": store_id}) or []
    options = {0: "All categories"} | {item["id"]: item["name"] for item in categories}
    category_id = columns[1].selectbox(
        "Category", list(options), format_func=lambda value: options[value]
    )
    limit = columns[2].number_input("Rows", min_value=10, max_value=500, value=50, step=10)

    products = ui.fetch(
        "/products",
        {
            "store_id": store_id,
            "q": query or None,
            "category_id": category_id or None,
            "limit": int(limit),
        },
    )
    if products:
        frame = pd.DataFrame(products)
        frame["sell_price"] = frame["sell_price"].map(ui.money)
        st.dataframe(
            frame[
                ["sku", "name", "category_name", "sell_price", "gst_rate",
                 "qty_on_hand", "reorder_point", "attributes"]
            ].rename(columns={"qty_on_hand": f"on hand ({unit})", "reorder_point": "reorder at"}),
            hide_index=True,
            use_container_width=True,
            height=420,
        )
    elif products is not None:
        ui.empty_state("No products match.", "Clear the filters or add a product below.")

with tabs[1]:
    rows = ui.fetch("/products/low-stock", {"store_id": store_id, "limit": 100})
    if rows:
        st.dataframe(
            pd.DataFrame(rows)[["sku", "name", "qty_on_hand", "reorder_point", "sell_price"]],
            hide_index=True,
            use_container_width=True,
        )
    elif rows is not None:
        ui.empty_state("Nothing is at or below its reorder point.")

with tabs[2]:
    st.caption(
        f"'Dead' means no sale in {ctx['config'].get('dead_stock_days')} days - this "
        "store's own window, not a global one."
    )
    rows = ui.fetch("/products/dead-stock", {"store_id": store_id, "limit": 100})
    if rows:
        st.dataframe(
            pd.DataFrame(rows)[["sku", "name", "qty_on_hand", "days_since_sold", "sell_price"]],
            hide_index=True,
            use_container_width=True,
        )
    elif rows is not None:
        ui.empty_state("Every SKU has sold inside the window.")

st.divider()
st.subheader("Add a product")
st.caption(
    "These attribute fields come from the vertical's product_schema. Switch the store "
    "in the sidebar and the form changes with it."
)

with st.form("add_product"):
    base = st.columns(3)
    sku = base[0].text_input("SKU")
    name = base[1].text_input("Name")
    category_id = base[2].selectbox(
        "Category",
        [0] + [item["id"] for item in (categories or [])],
        format_func=lambda value: options.get(value, "No category"),
    )

    prices = st.columns(4)
    cost_price = prices[0].number_input("Cost price", min_value=0.0, step=1.0)
    sell_price = prices[1].number_input("Sell price", min_value=0.0, step=1.0)
    gst_rate = prices[2].number_input("GST %", min_value=0.0, max_value=28.0, step=1.0, value=5.0)
    qty_on_hand = prices[3].number_input(f"Opening stock ({unit})", min_value=0.0, step=1.0)

    st.markdown("**Attributes**")
    attributes: dict = {}
    attribute_columns = st.columns(max(len(schema), 1))
    for column, (field, spec) in zip(attribute_columns, schema.items()):
        label = field.replace("_", " ") + (" *" if spec.get("required") else "")
        kind = spec.get("type", "string")
        if kind == "boolean":
            attributes[field] = column.checkbox(label)
        elif kind == "number":
            attributes[field] = column.number_input(label, min_value=0.0, step=1.0)
        elif kind == "date":
            value = column.date_input(label, value=None, format="DD/MM/YYYY")
            attributes[field] = str(value) if value else ""
        else:
            attributes[field] = column.text_input(label)

    if st.form_submit_button("Save product", type="primary"):
        payload = {
            "sku": sku,
            "name": name,
            "category_id": category_id or None,
            "cost_price": cost_price,
            "sell_price": sell_price,
            "gst_rate": gst_rate,
            "qty_on_hand": qty_on_hand,
            "reorder_point": 5,
            "attributes": {key: value for key, value in attributes.items() if value not in ("", None)},
        }
        ok, response = api.post("/products", params={"store_id": store_id}, json=payload)
        if ok:
            st.success(f"Added {response['name']} ({response['sku']})")
            st.rerun()
        else:
            ui.error_state(str(response))
