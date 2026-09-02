"""Shared page furniture: the resolved context, empty states, error states."""
from __future__ import annotations

from typing import Any

import streamlit as st

from lib import api

RUPEE = "₹"


def context() -> dict[str, Any] | None:
    """The store context resolved by the backend, or None if it is unavailable."""
    return st.session_state.get("context")


def require_context() -> dict[str, Any] | None:
    ctx = context()
    if ctx is None:
        st.error(
            "No store context loaded. Pick a store in the sidebar, and check that the "
            "API is running."
        )
        return None
    return ctx


def page_header(title: str, subtitle: str = "") -> dict[str, Any] | None:
    ctx = require_context()
    st.title(title)
    if ctx:
        st.caption(
            f"{ctx['store_name']} - {ctx['city']} - {ctx['vertical_name']}"
            + (f" - {subtitle}" if subtitle else "")
        )
    return ctx


def empty_state(message: str, hint: str = "") -> None:
    st.info(f"**Nothing here yet.** {message}" + (f"\n\n{hint}" if hint else ""))


def error_state(detail: str) -> None:
    st.error(f"**That did not work.** {detail}")


def money(value: Any) -> str:
    try:
        return f"{RUPEE}{float(value):,.2f}"
    except (TypeError, ValueError):
        return f"{RUPEE}0.00"


def fetch(path: str, params: dict | None = None, *, empty: str = "") -> Any | None:
    """GET and render the error state on failure. Returns None on failure."""
    ok, payload = api.get(path, params)
    if not ok:
        error_state(str(payload))
        return None
    if empty and not payload:
        empty_state(empty)
    return payload


def goto(page: str, **state: Any) -> None:
    """Deep link from a suggestion card to the page that acts on it."""
    for key, value in state.items():
        st.session_state[key] = value
    st.switch_page(page)
