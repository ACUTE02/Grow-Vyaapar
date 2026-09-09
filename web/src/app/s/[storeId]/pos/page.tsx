"use client";

import { use, useEffect, useMemo, useRef, useState } from "react";
import { Download, Minus, Plus, Search, ShoppingCart, Trash2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Button, IconButton } from "@/components/ui/button";
import { EmptyState, ErrorState, Notice, SkeletonRows } from "@/components/ui/states";
import { CustomerPicker } from "@/components/pos/customer-picker";
import { useToast } from "@/components/ui/toast";
import { useCreateSale, useProducts } from "@/lib/queries";
import { useActiveStore } from "@/lib/active-store";
import { apiBlob } from "@/lib/api";
import { money, quantity, count } from "@/lib/format";
import type { CustomerListItem, Product, Transaction } from "@/lib/types";

type Line = { product: Product; qty: number };

/**
 * A key identifying one checkout, sent as Idempotency-Key.
 *
 * crypto.randomUUID needs a secure context, which localhost and https both
 * are; the fallback is there so a plain-http deployment degrades to a still
 * unguessable key rather than to no key at all, which the API would refuse.
 */
function newCheckoutKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export default function PosPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId: raw } = use(params);
  const storeId = Number(raw);
  const store = useActiveStore();
  const unit = store.unit_labels.default;
  const toast = useToast();
  const searchRef = useRef<HTMLInputElement>(null);

  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [lines, setLines] = useState<Map<number, Line>>(new Map());
  const [customer, setCustomer] = useState<CustomerListItem | null>(null);
  const [discount, setDiscount] = useState(0);
  const [paymentMode, setPaymentMode] = useState("cash");
  const [lastInvoice, setLastInvoice] = useState<Transaction | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(search.trim()), 200);
    return () => window.clearTimeout(timer);
  }, [search]);

  // A counter is worked from the keyboard: "/" jumps to the product search
  // from anywhere on the page without reaching for the mouse.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing = target?.tagName === "INPUT" || target?.tagName === "TEXTAREA";
      if (event.key === "/" && !typing) {
        event.preventDefault();
        searchRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const productQuery = useMemo(
    () => ({ q: debounced, categoryId: null, includeInactive: false, limit: 25, offset: 0 }),
    [debounced],
  );
  const products = useProducts(storeId, productQuery);
  const sale = useCreateSale(storeId);
  const checkoutKey = useRef<string | null>(null);

  // Derived during render, not stored in an effect: the totals are a function
  // of the cart and nothing else.
  const subtotal = useMemo(
    () =>
      [...lines.values()].reduce(
        (sum, line) => sum + line.qty * line.product.sell_price,
        0,
      ),
    [lines],
  );

  function addLine(product: Product) {
    setLines((current) => {
      const next = new Map(current);
      const existing = next.get(product.id);
      next.set(product.id, { product, qty: (existing?.qty ?? 0) + 1 });
      return next;
    });
  }

  function setQty(productId: number, qty: number) {
    setLines((current) => {
      const next = new Map(current);
      const line = next.get(productId);
      if (!line) return current;
      if (qty <= 0) next.delete(productId);
      else next.set(productId, { ...line, qty });
      return next;
    });
  }

  function completeSale() {
    const payload = [...lines.values()]
      .filter((line) => line.qty > 0)
      .map((line) => ({ product_id: line.product.id, qty: line.qty }));

    if (payload.length === 0) {
      setFailure("Every line has a quantity of zero.");
      return;
    }
    setFailure(null);

    // One key per checkout, not per request. It is minted on the first attempt
    // and kept until a bill actually exists, so pressing Complete sale again
    // after a timeout sends the same key and gets the first bill back instead
    // of writing a second one. A disabled button cannot do this: it stops a
    // second click and knows nothing about a request that was resent.
    checkoutKey.current ??= newCheckoutKey();

    sale.mutate(
      {
        idempotencyKey: checkoutKey.current,
        body: {
          customer_id: customer?.id ?? null,
          lines: payload,
          discount,
          payment_mode: paymentMode,
        },
      },
      {
        onSuccess: (invoice) => {
          // The bill exists, so this checkout is over and the next one is a
          // new one. Cleared here rather than on failure: a failed attempt has
          // written nothing, and its key is still the right one to retry with.
          checkoutKey.current = null;
          setLastInvoice(invoice);
          setLines(new Map());
          setDiscount(0);
          // The next bill is a new customer until someone says otherwise -
          // never inherit the last one's selection.
          setCustomer(null);
          setSearch("");
          toast.success(`Invoice ${invoice.invoice_no} completed — ${money(invoice.total)}`);
        },
        onError: (error) => {
          setFailure(error.message);
          toast.error(error.message);
        },
      },
    );
  }

  async function downloadInvoice(invoice: Transaction) {
    try {
      const { blob, contentType } = await apiBlob(
        `/billing/transactions/${invoice.id}/invoice.pdf`,
        { store_id: storeId },
      );
      const isPdf = contentType.startsWith("application/pdf");
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `invoice-${invoice.invoice_no}.${isPdf ? "pdf" : "html"}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "The invoice could not be fetched.");
    }
  }

  const cart = [...lines.values()];

  return (
    <>
      <PageHeader
        title="Point of sale"
        subtitle={`${store.store_name} · quantities in ${unit} · press / to jump to search`}
      />

      <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
        {/* ---- catalog ---- */}
        <Card className="self-start">
          <Card.Header>
            <div className="relative flex-1">
              <Search
                className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3"
                aria-hidden
              />
              <input
                ref={searchRef}
                type="search"
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
                placeholder="Search the catalog by name or SKU"
                aria-label="Search the catalog"
                className="h-9 w-full rounded-lg border border-line bg-surface pr-3 pl-9 text-sm text-ink placeholder:text-ink-3 hover:border-line-strong"
              />
            </div>
          </Card.Header>

          {products.isPending ? (
            <SkeletonRows rows={6} columns={3} />
          ) : products.isError ? (
            <ErrorState detail={products.error.message} onRetry={() => void products.refetch()} />
          ) : products.data === undefined ? null : products.data.items.length === 0 ? (
            <EmptyState
              title="No products match that search"
              hint="Add stock on the Products page, or clear the search box."
            />
          ) : (
            <ul className="divide-y divide-line">
              {products.data.items.map((product) => {
                const inCart = lines.get(product.id)?.qty ?? 0;
                const out = product.qty_on_hand <= 0;
                return (
                  <li key={product.id} className="flex items-center gap-3 px-4 py-2.5">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-ink">
                        {product.name}
                      </span>
                      <span className="block font-mono text-[11px] text-ink-3">{product.sku}</span>
                    </span>
                    <span className="tnum shrink-0 text-right text-sm">
                      <span className="block font-medium text-ink">
                        {money(product.sell_price)}
                      </span>
                      <span className="block text-[11px] text-ink-3">
                        GST {product.gst_rate}%
                      </span>
                    </span>
                    <span
                      className={`tnum w-20 shrink-0 text-right text-xs ${out ? "text-danger" : "text-ink-2"}`}
                    >
                      {quantity(product.qty_on_hand, product.unit_label)}
                    </span>
                    <Button
                      size="sm"
                      variant={inCart > 0 ? "primary" : "secondary"}
                      onClick={() => addLine(product)}
                      aria-label={`Add ${product.name} to the bill`}
                    >
                      <Plus className="size-3.5" aria-hidden />
                      {inCart > 0 ? count(inCart) : "Add"}
                    </Button>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        {/* ---- the bill ---- */}
        <div className="space-y-4">
          <Card>
            <Card.Header>
              <Card.Title hint={cart.length === 0 ? undefined : `${cart.length} line(s)`}>
                Current bill
              </Card.Title>
              {cart.length > 0 ? (
                <Button size="sm" variant="ghost" onClick={() => setLines(new Map())}>
                  <Trash2 className="size-3.5" aria-hidden />
                  Clear
                </Button>
              ) : null}
            </Card.Header>

            {cart.length === 0 ? (
              <EmptyState
                icon={<ShoppingCart className="size-5" aria-hidden />}
                title="The bill is empty"
                hint="Add an item from the catalog to start."
              />
            ) : (
              <ul className="divide-y divide-line">
                {cart.map((line) => (
                  <li key={line.product.id} className="flex items-center gap-2 px-4 py-2.5">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-ink">{line.product.name}</span>
                      <span className="tnum block text-[11px] text-ink-3">
                        {money(line.product.sell_price)} × {line.qty} {unit}
                      </span>
                    </span>
                    <div className="flex shrink-0 items-center gap-1">
                      <IconButton
                        label={`Reduce ${line.product.name}`}
                        size="sm"
                        variant="secondary"
                        onClick={() => setQty(line.product.id, line.qty - 1)}
                      >
                        <Minus className="size-3.5" aria-hidden />
                      </IconButton>
                      <input
                        type="number"
                        min={0}
                        step="any"
                        value={line.qty}
                        onChange={(event) =>
                          setQty(line.product.id, Number(event.currentTarget.value))
                        }
                        aria-label={`Quantity of ${line.product.name} in ${unit}`}
                        className="tnum h-8 w-16 rounded-lg border border-line bg-surface px-2 text-center text-sm"
                      />
                      <IconButton
                        label={`Add one more ${line.product.name}`}
                        size="sm"
                        variant="secondary"
                        onClick={() => setQty(line.product.id, line.qty + 1)}
                      >
                        <Plus className="size-3.5" aria-hidden />
                      </IconButton>
                    </div>
                    <span className="tnum w-20 shrink-0 text-right text-sm font-medium text-ink">
                      {money(line.qty * line.product.sell_price)}
                    </span>
                  </li>
                ))}
              </ul>
            )}

            <Card.Body className="space-y-4 border-t border-line">
              <div>
                <p className="mb-1.5 text-xs font-medium tracking-wide text-ink-2 uppercase">
                  Customer
                </p>
                <CustomerPicker
                  storeId={storeId}
                  storeName={store.store_name}
                  selected={customer}
                  onSelect={setCustomer}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="mb-1.5 block text-xs font-medium tracking-wide text-ink-2 uppercase">
                    Bill discount
                  </span>
                  <input
                    type="number"
                    min={0}
                    step={10}
                    value={discount}
                    onChange={(event) => setDiscount(Number(event.currentTarget.value))}
                    className="tnum h-9 w-full rounded-lg border border-line bg-surface px-3 text-sm"
                  />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-xs font-medium tracking-wide text-ink-2 uppercase">
                    Payment
                  </span>
                  <select
                    value={paymentMode}
                    onChange={(event) => setPaymentMode(event.currentTarget.value)}
                    className="h-9 w-full rounded-lg border border-line bg-surface px-2 text-sm"
                  >
                    <option value="cash">Cash</option>
                    <option value="upi">UPI</option>
                    <option value="card">Card</option>
                  </select>
                </label>
              </div>

              {failure ? <Notice tone="danger">{failure}</Notice> : null}

              <div className="flex items-baseline justify-between border-t border-line pt-3">
                <span className="text-sm text-ink-2">Subtotal before GST</span>
                <span className="tnum font-display text-xl font-semibold text-ink">
                  {money(subtotal - discount)}
                </span>
              </div>

              <Button
                variant="primary"
                size="lg"
                className="w-full"
                busy={sale.isPending}
                disabled={cart.length === 0}
                onClick={completeSale}
              >
                Complete sale
              </Button>
            </Card.Body>
          </Card>

          {lastInvoice ? (
            <Card>
              <Card.Header>
                <Card.Title hint={lastInvoice.customer_name ?? "Walk-in"}>
                  Invoice {lastInvoice.invoice_no}
                </Card.Title>
                <Button size="sm" variant="secondary" onClick={() => void downloadInvoice(lastInvoice)}>
                  <Download className="size-3.5" aria-hidden />
                  Invoice
                </Button>
              </Card.Header>
              <Card.Body>
                <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                  <Figure label="Subtotal" value={money(lastInvoice.subtotal)} />
                  <Figure label="Discount" value={money(lastInvoice.discount)} />
                  <Figure label="GST" value={money(lastInvoice.gst_amount)} />
                  <Figure label="Total" value={money(lastInvoice.total)} strong />
                </dl>
                {lastInvoice.customer_id ? (
                  <p className="mt-3 text-xs text-ink-3">
                    The marketing agent has already reacted to this sale. Nothing is sent until
                    someone presses send in the Outbox.
                  </p>
                ) : null}
              </Card.Body>
            </Card>
          ) : null}
        </div>
      </div>
    </>
  );
}

function Figure({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div>
      <dt className="text-[11px] text-ink-3">{label}</dt>
      <dd
        className={`tnum mt-0.5 ${strong ? "font-display text-lg font-semibold text-primary" : "text-ink"}`}
      >
        {value}
      </dd>
    </div>
  );
}
