"""LocalAI OS - Streamlit front end.

The sidebar store selector is the whole demo: changing it re-reads the context
and every page changes thresholds, fields, copy and navigation with it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from lib import api  # noqa: E402

st.set_page_config(page_title="LocalAI OS", page_icon="🛒", layout="wide")


def _login_screen() -> None:
    """No token, no app. The same check runs in the API for every request."""
    st.title("LocalAI OS")
    st.caption("Sign in to continue.")
    with st.form("login"):
        email = st.text_input("Email", value=st.session_state.get("last_email", ""))
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", type="primary"):
            ok, payload = api.login(email.strip(), password)
            if ok:
                st.session_state["token"] = payload["access_token"]
                st.session_state["user"] = payload["user"]
                st.session_state["last_email"] = email.strip()
                api.invalidate()
                st.rerun()
            else:
                st.error(str(payload))
    st.info(
        "The demo seed creates one account per store plus a platform owner. "
        "See the README for the addresses and the demo password."
    )


def _load_stores() -> list[dict] | None:
    ok, payload = api.stores(st.session_state.get("token"))
    if not ok:
        st.sidebar.error(str(payload))
        st.title("LocalAI OS")
        st.error(
            "The API is not reachable. Start it with:\n\n"
            "```\ncd backend\nuvicorn app.main:app --reload\n```"
        )
        return None
    if not payload:
        st.sidebar.warning("No stores yet.")
        st.title("LocalAI OS")
        st.info("No stores found. Seed the demo data:\n\n```\ncd backend\npython -m scripts.seed\n```")
        return None
    return payload


def _sidebar(stores: list[dict]) -> dict | None:
    st.sidebar.title("LocalAI OS")
    labels = {store["id"]: f"{store['name']} · {store['vertical_name']}" for store in stores}
    ids = list(labels)

    previous = st.session_state.get("store_id", ids[0])
    index = ids.index(previous) if previous in ids else 0
    store_id = st.sidebar.selectbox(
        "Store", ids, index=index, format_func=lambda value: labels[value]
    )

    if store_id != st.session_state.get("store_id"):
        # A different store means a different vertical: drop everything cached.
        st.session_state["store_id"] = store_id
        st.session_state.pop("cart", None)
        api.invalidate()

    ok, context = api.store_context(store_id, st.session_state.get("token"))
    if not ok:
        st.sidebar.error(str(context))
        st.session_state["context"] = None
        return None

    st.session_state["context"] = context
    config = context["config"]
    flags = context["feature_flags"]

    user = st.session_state.get("user") or {}
    st.sidebar.caption(f"{context['city']} · {context['vertical_name']}")
    st.sidebar.caption(f"Signed in as {user.get('name', 'unknown')} ({user.get('role', '?')})")
    if st.sidebar.button("Sign out"):
        for key in ("token", "user"):
            st.session_state.pop(key, None)
        api.invalidate()
        st.rerun()
    with st.sidebar.expander("Active configuration", expanded=False):
        st.write(
            {
                "unit": context["unit_labels"]["default"],
                "reorder cycle (days)": config.get("reorder_cycle_days"),
                "revisit cycle (days)": config.get("revisit_cycle_days"),
                "inactive after (days)": config.get("inactive_days"),
                "dead stock after (days)": config.get("dead_stock_days"),
            }
        )
        st.write({name: bool(value) for name, value in flags.items()})
        st.caption("These come from the vertical row, not from code.")

    return context


if not st.session_state.get("token"):
    # A one-page navigation with the sidebar hidden, so Streamlit does not
    # advertise every page in pages/ to someone who has not signed in.
    st.navigation(
        [st.Page(_login_screen, title="Sign in", url_path="sign-in")], position="hidden"
    ).run()
    st.stop()

stores = _load_stores()
if stores:
    context = _sidebar(stores)
    flags = (context or {}).get("feature_flags", {})

    pages = [
        st.Page("pages/pos.py", title="POS", icon="🧾", default=True),
        st.Page("pages/dashboard.py", title="Dashboard", icon="📊"),
        st.Page("pages/customers.py", title="Customers", icon="👥"),
        st.Page("pages/catalog.py", title="Catalog", icon="📦"),
        st.Page("pages/reorder.py", title="Reorder", icon="🔮"),
        st.Page("pages/outbox.py", title="Outbox", icon="✉️"),
        st.Page("pages/campaigns.py", title="Campaigns", icon="🎉"),
        st.Page("pages/performance.py", title="Performance", icon="📈"),
    ]
    # Feature-flagged navigation: these appear only for verticals that need them.
    if flags.get("jobs"):
        pages.append(st.Page("pages/jobs.py", title="Jobs", icon="🧵"))
    if flags.get("expiry"):
        pages.append(st.Page("pages/expiry.py", title="Expiry", icon="⏳"))

    # Buying stock is a manager job, so the page only appears for one.
    if (st.session_state.get("user") or {}).get("role") in ("owner", "manager"):
        pages.append(st.Page("pages/purchasing.py", title="Purchasing", icon="🚚"))

    st.navigation(pages).run()
