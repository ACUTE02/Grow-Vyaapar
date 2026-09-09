"use client";

import { useMemo, useState } from "react";
import { Plus, X } from "lucide-react";
import { Button, IconButton } from "@/components/ui/button";
import { SelectField } from "@/components/ui/field";
import { EmptyState, Notice } from "@/components/ui/states";
import { money, quantity } from "@/lib/format";
import type { Product, StockForecast, Supplier } from "@/lib/types";

type Line = {
  product_id: number;
  qty: number;
  unit_cost: number;
  expiry_date: string;
  batch_no: string;
};

/**
 * Raise a purchase order.
 *
 * Quantities are pre-filled from the reorder forecast where it has an opinion
 * about the product - velocity over the reorder cycle with a safety margin -
 * and fall back to the product's own numbers otherwise. Expiry and batch
 * fields appear only when the vertical tracks batches, because receiving is
 * what creates them and a store that does not track them has nowhere to put
 * the value.
 */
export function OrderBuilder({
  suppliers,
  products,
  forecast,
  tracksExpiry,
  unitLabel,
  busy,
  error,
  onSubmit,
}: {
  suppliers: Supplier[];
  products: Product[];
  forecast: StockForecast[];
  tracksExpiry: boolean;
  unitLabel: string;
  busy: boolean;
  error: string | null;
  onSubmit: (body: Record<string, unknown>) => void;
}) {
  const suggestions = useMemo(
    () => new Map(forecast.map((row) => [row.sku, row])),
    [forecast],
  );

  const [supplierId, setSupplierId] = useState<string>(
    suppliers[0] ? String(suppliers[0].id) : "",
  );
  const [lines, setLines] = useState<Line[]>([]);
  const [picking, setPicking] = useState("");

  const defaultExpiry = useMemo(() => {
    const year = new Date();
    year.setFullYear(year.getFullYear() + 1);
    return year.toISOString().slice(0, 10);
  }, []);

  if (suppliers.length === 0 || products.length === 0) {
    return (
      <EmptyState
        title="Nothing to order yet"
        hint="Add a supplier on this page and at least one product on the Products page first."
      />
    );
  }

  function addLine(productId: number) {
    const product = products.find((item) => item.id === productId);
    if (!product || lines.some((line) => line.product_id === productId)) return;
    const hint = suggestions.get(product.sku);
    const stamp = new Date();
    setLines((current) => [
      ...current,
      {
        product_id: productId,
        qty: Number(hint?.suggested_reorder_qty) || 10,
        unit_cost: product.cost_price,
        expiry_date: defaultExpiry,
        batch_no: `B${String(stamp.getFullYear()).slice(2)}${String(stamp.getMonth() + 1).padStart(2, "0")}-${productId}`,
      },
    ]);
  }

  function patch(productId: number, changes: Partial<Line>) {
    setLines((current) =>
      current.map((line) => (line.product_id === productId ? { ...line, ...changes } : line)),
    );
  }

  const total = lines.reduce((sum, line) => sum + line.qty * line.unit_cost, 0);

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (lines.length === 0) return;
        onSubmit({
          supplier_id: Number(supplierId),
          items: lines.map((line) => ({
            product_id: line.product_id,
            qty: line.qty,
            unit_cost: line.unit_cost,
            ...(tracksExpiry
              ? { expiry_date: line.expiry_date || null, batch_no: line.batch_no || null }
              : {}),
          })),
        });
      }}
    >
      {error ? <Notice tone="danger">{error}</Notice> : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField
          label="Supplier"
          value={supplierId}
          onChange={(event) => setSupplierId(event.currentTarget.value)}
        >
          {suppliers.map((supplier) => (
            <option key={supplier.id} value={supplier.id}>
              {supplier.name}
            </option>
          ))}
        </SelectField>

        <SelectField
          label="Add a product"
          value={picking}
          hint={
            forecast.length > 0
              ? "Quantities pre-fill from the reorder forecast where it has one."
              : "No forecast computed yet, so quantities start at the product's own numbers."
          }
          onChange={(event) => {
            const value = event.currentTarget.value;
            if (value) addLine(Number(value));
            setPicking("");
          }}
        >
          <option value="">Choose a product…</option>
          {products
            .filter((product) => !lines.some((line) => line.product_id === product.id))
            .map((product) => (
              <option key={product.id} value={product.id}>
                {suggestions.has(product.sku) ? "★ " : ""}
                {product.name} ({product.sku})
              </option>
            ))}
        </SelectField>
      </div>

      {lines.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-sm text-ink-3">
          No lines yet. Pick a product above — the ★ ones are what the forecast suggests
          reordering.
        </p>
      ) : (
        <ul className="space-y-2">
          {lines.map((line) => {
            const product = products.find((item) => item.id === line.product_id);
            const hint = product ? suggestions.get(product.sku) : undefined;
            return (
              <li
                key={line.product_id}
                className="rounded-lg border border-line bg-surface-2/40 p-3"
              >
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">{product?.name}</p>
                    <p className="font-mono text-[11px] text-ink-3">{product?.sku}</p>
                  </div>
                  <span className="tnum text-sm font-medium text-ink">
                    {money(line.qty * line.unit_cost)}
                  </span>
                  <IconButton
                    label={`Remove ${product?.name ?? "line"}`}
                    size="sm"
                    onClick={() =>
                      setLines((current) =>
                        current.filter((item) => item.product_id !== line.product_id),
                      )
                    }
                  >
                    <X className="size-3.5" aria-hidden />
                  </IconButton>
                </div>

                <div
                  className={`mt-2 grid gap-2 ${tracksExpiry ? "sm:grid-cols-4" : "sm:grid-cols-2"}`}
                >
                  <LineField
                    label={`Qty (${unitLabel})`}
                    type="number"
                    min={0.01}
                    step="any"
                    value={line.qty}
                    onChange={(value) => patch(line.product_id, { qty: Number(value) })}
                  />
                  <LineField
                    label="Unit cost"
                    type="number"
                    min={0}
                    step="0.01"
                    value={line.unit_cost}
                    onChange={(value) => patch(line.product_id, { unit_cost: Number(value) })}
                  />
                  {tracksExpiry ? (
                    <>
                      <LineField
                        label="Expiry"
                        type="date"
                        value={line.expiry_date}
                        onChange={(value) => patch(line.product_id, { expiry_date: value })}
                      />
                      <LineField
                        label="Batch no."
                        type="text"
                        value={line.batch_no}
                        onChange={(value) => patch(line.product_id, { batch_no: value })}
                      />
                    </>
                  ) : null}
                </div>

                {hint ? (
                  <p className="mt-1.5 text-[11px] text-ink-3">
                    Forecast suggests {quantity(hint.suggested_reorder_qty, unitLabel)} —{" "}
                    {hint.reason}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
        <span className="text-sm text-ink-2">
          {lines.length} line{lines.length === 1 ? "" : "s"} ·{" "}
          <span className="tnum font-medium text-ink">{money(total)}</span>
        </span>
        <Button type="submit" variant="primary" busy={busy} disabled={lines.length === 0}>
          <Plus className="size-4" aria-hidden />
          Create order
        </Button>
      </div>
    </form>
  );
}

function LineField({
  label,
  value,
  onChange,
  ...rest
}: {
  label: string;
  value: string | number;
  onChange: (value: string) => void;
  type: string;
  min?: number;
  step?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-medium tracking-wide text-ink-3 uppercase">
        {label}
      </span>
      <input
        {...rest}
        value={value}
        onChange={(event) => onChange(event.currentTarget.value)}
        className="tnum h-9 w-full rounded-lg border border-line bg-surface px-2 text-sm text-ink hover:border-line-strong"
      />
    </label>
  );
}
