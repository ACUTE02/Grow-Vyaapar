"""Invoice rendering. HTML via Jinja2, PDF via WeasyPrint when it is installed.

WeasyPrint needs native GTK libraries that are not present on every machine, so
the import is lazy and the caller can fall back to the HTML body. Never let a
missing system library break the billing screen.
"""
from __future__ import annotations

from decimal import Decimal

from jinja2 import Environment, select_autoescape
from sqlalchemy.orm import Session

from app.models.core import Customer, Product, Transaction, TransactionItem
from app.services.errors import NotFoundError
from app.verticals.context import StoreContext

_env = Environment(autoescape=select_autoescape(["html"]))

INVOICE_TEMPLATE = """
<!doctype html>
<html><head><meta charset="utf-8"><title>{{ invoice_no }}</title>
<style>
  @page { size: A4; margin: 14mm; }
  body { font-family: "DejaVu Sans", Arial, sans-serif; font-size: 11px; color: #111; }
  h1 { font-size: 18px; margin: 0 0 2px; }
  .muted { color: #555; }
  table { width: 100%; border-collapse: collapse; margin-top: 12px; }
  th, td { border-bottom: 1px solid #ddd; padding: 6px 4px; text-align: left; }
  td.num, th.num { text-align: right; }
  .totals { width: 42%; margin-left: auto; margin-top: 10px; }
  .totals td { border: none; padding: 3px 4px; }
  .grand { font-weight: bold; border-top: 1px solid #333 !important; }
  .foot { margin-top: 18px; font-size: 10px; color: #555; }
</style></head>
<body>
  <h1>{{ store_name }}</h1>
  <div class="muted">{{ city }}{% if gstin %} &middot; GSTIN {{ gstin }}{% endif %}</div>
  <div class="muted">Tax invoice {{ invoice_no }} &middot; {{ created_at }}</div>
  <div class="muted">Customer: {{ customer_name }}{% if customer_phone %} ({{ customer_phone }}){% endif %}</div>

  <table>
    <thead><tr>
      <th>SKU</th><th>Item</th>
      <th class="num">Qty ({{ unit_label }})</th>
      <th class="num">Rate</th><th class="num">Disc</th>
      <th class="num">GST %</th><th class="num">Amount</th>
    </tr></thead>
    <tbody>
    {% for line in lines %}
      <tr>
        <td>{{ line.sku }}</td><td>{{ line.name }}</td>
        <td class="num">{{ line.qty }}</td>
        <td class="num">{{ line.unit_price }}</td>
        <td class="num">{{ line.line_discount }}</td>
        <td class="num">{{ line.gst_rate }}</td>
        <td class="num">{{ line.line_total }}</td>
      </tr>
    {% endfor %}
    </tbody>
  </table>

  <table class="totals">
    <tr><td>Subtotal</td><td class="num">{{ subtotal }}</td></tr>
    <tr><td>Discount</td><td class="num">-{{ discount }}</td></tr>
    <tr><td>GST</td><td class="num">{{ gst_amount }}</td></tr>
    <tr class="grand"><td>Total</td><td class="num">INR {{ total }}</td></tr>
  </table>

  <div class="foot">
    Paid by {{ payment_mode }} &middot; status {{ status }}<br>
    {{ signature }}
  </div>
</body></html>
"""


def _invoice_context(db: Session, context: StoreContext, transaction_id: int) -> dict:
    transaction = db.get(Transaction, transaction_id)
    if transaction is None or transaction.store_id != context.store_id:
        raise NotFoundError(f"Invoice {transaction_id} does not belong to {context.store_name}")

    lines = []
    for item in transaction.items:
        product = db.get(Product, item.product_id)
        lines.append(
            {
                "sku": product.sku if product else str(item.product_id),
                "name": product.name if product else "Removed product",
                "qty": f"{Decimal(str(item.qty)).normalize():f}",
                "unit_price": f"{Decimal(str(item.unit_price)):.2f}",
                "line_discount": f"{Decimal(str(item.line_discount)):.2f}",
                "gst_rate": f"{Decimal(str(product.gst_rate)):.2f}" if product else "0.00",
                "line_total": f"{Decimal(str(item.line_total)):.2f}",
            }
        )

    customer_name, customer_phone = "Walk-in", None
    if transaction.customer_id:
        customer = db.get(Customer, transaction.customer_id)
        if customer:
            customer_name, customer_phone = customer.name, customer.phone

    signature = str(context.prompt_profile.get("signature", "{store_name}, {city}")).format(
        store_name=context.store_name, city=context.city
    )

    return {
        "store_name": context.store_name,
        "city": context.city,
        "gstin": context.gstin,
        "invoice_no": transaction.invoice_no,
        "created_at": transaction.created_at.strftime("%d %b %Y, %H:%M"),
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "unit_label": context.unit_label,
        "lines": lines,
        "subtotal": f"{Decimal(str(transaction.subtotal)):.2f}",
        "discount": f"{Decimal(str(transaction.discount)):.2f}",
        "gst_amount": f"{Decimal(str(transaction.gst_amount)):.2f}",
        "total": f"{Decimal(str(transaction.total)):.2f}",
        "payment_mode": transaction.payment_mode,
        "status": transaction.status,
        "signature": signature,
    }


def render_invoice_html(db: Session, context: StoreContext, transaction_id: int) -> str:
    return _env.from_string(INVOICE_TEMPLATE).render(
        **_invoice_context(db, context, transaction_id)
    )


def render_invoice_pdf(db: Session, context: StoreContext, transaction_id: int) -> bytes | None:
    """Return PDF bytes, or None when WeasyPrint is unavailable on this machine."""
    html = render_invoice_html(db, context, transaction_id)
    try:
        from weasyprint import HTML  # noqa: PLC0415
    except Exception:  # pragma: no cover - depends on system libraries
        return None
    try:
        return HTML(string=html).write_pdf()
    except Exception:  # pragma: no cover
        return None
