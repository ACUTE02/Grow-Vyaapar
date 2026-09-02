"""Dashboard: the numbers, then three suggestions that quote them."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import api, ui

ctx = ui.page_header("Dashboard")
if ctx is None:
    st.stop()

store_id = ctx["store_id"]
unit = ctx["unit_labels"]["default"]

controls = st.columns([1, 1, 1, 3])
if controls[0].button("Rebuild segments", use_container_width=True):
    ok, payload = api.post("/marketing/segments/rebuild", params={"store_id": store_id})
    st.toast("Segments rebuilt" if ok else str(payload))
if controls[1].button("Run reminder check", use_container_width=True):
    ok, payload = api.post("/marketing/reminders/run", params={"store_id": store_id})
    st.toast(f"Queued {payload['total']} reminders" if ok else str(payload))
if controls[2].button("Refresh suggestions", use_container_width=True):
    ui.fetch("/marketing/insights", {"store_id": store_id, "force": True})
    st.toast("Suggestions refreshed")

summary = ui.fetch("/analytics/summary", {"store_id": store_id, "days": 30})
insights = ui.fetch("/marketing/insights", {"store_id": store_id})
segments = ui.fetch("/marketing/segments/summary", {"store_id": store_id}) or {}

if summary is None or insights is None:
    st.stop()

# -- headline figures --------------------------------------------------------
metrics = insights.get("metrics", {})
row = st.columns(4)
row[0].metric("Sales, last 30 days", ui.money(summary["net_total"]))
row[1].metric("Invoices", f"{summary['invoices']:,}")
row[2].metric("Average bill", ui.money(summary["average_bill"]))
row[3].metric(
    "This week vs last",
    ui.money(metrics.get("week_sales", 0)),
    f"{metrics.get('week_over_week_change_pct', 0)}%",
)

# -- charts ------------------------------------------------------------------
left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader("Sales trend")
    series = summary.get("series") or []
    if not series:
        ui.empty_state(
            "No sales in this window.",
            "Ring up a sale on the POS page, or seed the demo data.",
        )
    else:
        frame = pd.DataFrame(series)
        frame["date"] = pd.to_datetime(frame["date"])
        st.line_chart(frame.set_index("date")["net"], height=260)

with right:
    st.subheader("Customer segments")
    if not any(segments.values()):
        ui.empty_state("Segments have not been computed yet.", "Press 'Rebuild segments'.")
    else:
        st.bar_chart(pd.Series(segments, name="customers"), height=260)

# -- suggestions -------------------------------------------------------------
st.subheader("What the agent suggests")
source = insights.get("source", "template")
st.caption(
    {
        "llm": "Written by the model from figures computed in SQL.",
        "template": "No LLM key configured - written by the fallback, same figures.",
        "cache": "Served from the cached insight row (refreshed every 24 hours).",
    }.get(source, source)
)

suggestions = insights.get("suggestions") or []
if not suggestions:
    ui.empty_state("No suggestions yet.", "Press 'Refresh suggestions'.")
else:
    columns = st.columns(len(suggestions))
    targets = {
        "low_stock": ("Open low stock", "pages/catalog.py", {"catalog_tab": "low"}),
        "dead_stock": ("Open dead stock", "pages/catalog.py", {"catalog_tab": "dead"}),
        "customers": ("Open customers", "pages/customers.py", {}),
        "outbox": ("Open outbox", "pages/outbox.py", {}),
        "campaigns": ("Open campaigns", "pages/campaigns.py", {}),
        "reorder": ("Open reorder list", "pages/reorder.py", {}),
    }
    for column, suggestion in zip(columns, suggestions):
        with column.container(border=True):
            st.markdown(f"**{suggestion['title']}**")
            st.write(suggestion["detail"])
            if suggestion.get("figure"):
                st.caption(f"Figure: {suggestion['figure']}")
            label, page, state = targets.get(
                suggestion.get("action") or "", ("Open customers", "pages/customers.py", {})
            )
            if st.button(label, key=f"suggestion_{suggestion['title'][:20]}"):
                ui.goto(page, **state)

# -- churn risk --------------------------------------------------------------
st.subheader("Churn risk")
st.caption(
    "A logistic-regression model trained on this store's own history: features as "
    "of a cutoff date, labels from whether the customer came back in the window "
    "after it. The list below is deliberately filtered to customers who have NOT "
    "lapsed yet - reaching them is the point."
)

run = None
ok_run, run_payload = api.get("/ml/churn/latest-run", {"store_id": store_id})
if ok_run:
    run = run_payload

churn_controls = st.columns([1, 1, 4])
if churn_controls[0].button("Train model", use_container_width=True):
    with st.spinner("Training and scoring..."):
        ok, payload = api.post("/ml/churn/train", params={"store_id": store_id})
    st.toast("Model trained" if ok else str(payload))
    st.rerun()
if churn_controls[1].button("Rescore", use_container_width=True):
    ok, payload = api.post("/ml/churn/score", params={"store_id": store_id})
    st.toast(f"Scored {payload['scored']}" if ok else str(payload))
    st.rerun()

if run is None:
    ui.empty_state(
        "No churn model has been trained for this store yet.",
        "Press 'Train model'. It trains on this store's own transactions - nothing is shared "
        "between stores.",
    )
else:
    at_risk = ui.fetch("/ml/churn/at-risk", {"store_id": store_id, "limit": 20}) or []
    metrics_row = st.columns(4)
    metrics_row[0].metric("At risk, not yet lapsed", len(at_risk))
    metrics_row[1].metric("ROC-AUC (holdout)", f"{run['metrics'].get('roc_auc', 0):.3f}")
    metrics_row[2].metric(
        "ROC-AUC (5-fold)",
        f"{run['metrics'].get('roc_auc_cv_mean', 0):.3f}",
        f"+/- {run['metrics'].get('roc_auc_cv_std', 0):.3f}",
    )
    metrics_row[3].metric("Trained on", f"{run['rows_trained']} customers")

    if at_risk:
        frame = pd.DataFrame(at_risk)
        frame["probability"] = frame["probability"].map(lambda value: f"{value:.0%}")
        st.dataframe(
            frame[["name", "phone", "probability", "segment", "recency_days", "total_spend"]]
            .rename(columns={"recency_days": "days since visit", "total_spend": "lifetime spend"}),
            hide_index=True,
            use_container_width=True,
        )
        if st.button("Queue win-back messages for these customers", type="primary"):
            ok, payload = api.post("/ml/churn/queue-winback", params={"store_id": store_id})
            if ok:
                st.success(f"Queued {payload['queued']} win-back messages in the Outbox")
            else:
                ui.error_state(str(payload))
    else:
        ui.empty_state(
            "Nobody is flagged high risk while still active.",
            "Either the model has not scored yet, or every risky customer has already lapsed - "
            "those appear in the Inactive segment instead.",
        )

    with st.expander("Model card (what it learned)"):
        coefficients = run["metrics"].get("coefficients", {})
        ordered = sorted(coefficients.items(), key=lambda item: abs(item[1]), reverse=True)
        st.write(
            {
                "model": f"{run['model_name']} v{run['model_version']}",
                "trained_at": run["trained_at"][:16].replace("T", " "),
                "cutoff_date": run["metrics"].get("cutoff_date"),
                "label window (days)": run["metrics"].get("label_window_days"),
                "churn rate in training data": run["metrics"].get(
                    "churn_rate_in_training_data"
                ),
                "accuracy": run["metrics"].get("accuracy"),
                "precision": run["metrics"].get("precision"),
                "recall": run["metrics"].get("recall"),
            }
        )
        st.caption("Coefficients, largest effect first (positive pushes towards churn):")
        st.dataframe(
            pd.DataFrame(ordered, columns=["feature", "weight"]),
            hide_index=True,
            use_container_width=True,
        )
        matrix = run["metrics"].get("confusion_matrix")
        if matrix:
            st.caption("Confusion matrix (rows: actual stayed/churned, columns: predicted)")
            st.dataframe(
                pd.DataFrame(matrix, columns=["predicted stayed", "predicted churned"],
                             index=["actually stayed", "actually churned"]),
                use_container_width=True,
            )

# -- forward-looking stock ---------------------------------------------------
st.subheader("Stock outlook")
forecast_row = st.columns(4)
reorder_rows = ui.fetch(
    "/ml/forecast/stock", {"store_id": store_id, "view": "reorder", "limit": 100}
) or []
risk_rows = ui.fetch(
    "/ml/forecast/stock", {"store_id": store_id, "view": "dead_risk", "limit": 100}
) or []
forecast_row[0].metric(f"Reorder within {ctx['config'].get('reorder_cycle_days')} days", len(reorder_rows))
forecast_row[1].metric("Predicted to go stale", len(risk_rows))
if reorder_rows:
    soonest = reorder_rows[0]
    forecast_row[2].metric(
        "Runs out first",
        soonest["sku"],
        f"{soonest['days_to_stockout']:.0f} days",
        delta_color="inverse",
    )
if forecast_row[3].button("Open reorder list", use_container_width=True):
    ui.goto("pages/reorder.py")

if ctx["feature_flags"].get("expiry"):
    expiry = ui.fetch("/products/expiring", {"store_id": store_id})
    if expiry and expiry.get("batches"):
        window = expiry.get("near_expiry_days")
        near = expiry["batches"]
        expired = expiry.get("expired_count", 0)
        message = (
            f"{len(near)} batch(es) expire within {window} days"
            if window
            else f"{len(near)} dated batch(es) on the shelf"
        )
        if expired:
            st.error(f"{message}, and {expired} have already expired.")
        else:
            st.warning(message + ".")
        if st.button("Open expiring stock"):
            ui.goto("pages/expiry.py")

# -- the two stock lists -----------------------------------------------------
stock_left, stock_right = st.columns(2, gap="large")
with stock_left:
    st.subheader("Low stock")
    rows = ui.fetch("/products/low-stock", {"store_id": store_id, "limit": 10})
    if rows:
        st.dataframe(
            pd.DataFrame(rows)[["sku", "name", "qty_on_hand", "reorder_point"]].rename(
                columns={"qty_on_hand": f"on hand ({unit})", "reorder_point": "reorder at"}
            ),
            hide_index=True,
            use_container_width=True,
        )
    elif rows is not None:
        ui.empty_state("Nothing is below its reorder point.")

with stock_right:
    st.subheader(f"Dead stock (over {ctx['config'].get('dead_stock_days')} days)")
    rows = ui.fetch("/products/dead-stock", {"store_id": store_id, "limit": 10})
    if rows:
        st.dataframe(
            pd.DataFrame(rows)[["sku", "name", "qty_on_hand", "days_since_sold"]].rename(
                columns={"qty_on_hand": f"on hand ({unit})", "days_since_sold": "days idle"}
            ),
            hide_index=True,
            use_container_width=True,
        )
    elif rows is not None:
        ui.empty_state("Every SKU has sold inside this store's window.")
