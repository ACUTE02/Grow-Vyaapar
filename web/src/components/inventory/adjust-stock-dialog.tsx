"use client";

import { useState } from "react";
import { Modal } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { SelectField, TextAreaField, TextField } from "@/components/ui/field";
import { Notice } from "@/components/ui/states";
import { ADJUSTMENT_REASONS } from "@/lib/types";
import { quantity } from "@/lib/format";

/**
 * Correct one product's count, and say why.
 *
 * A delta rather than a new total, because that is what a shopkeeper standing
 * at a shelf actually knows: "six fewer than the screen says" is reliable,
 * "the true total is ninety-four" is arithmetic done twice. It also cannot
 * silently swallow a sale that landed between reading the screen and pressing
 * the button.
 *
 * Built on the same <dialog>-backed Modal as everything else, so Escape, the
 * focus trap and the inert background come from the platform.
 */
export function AdjustStockDialog({
  open,
  product,
  busy,
  serverError,
  onClose,
  onSubmit,
}: {
  open: boolean;
  product: { product_id: number; sku: string; name: string; qty_on_hand: number; unit_label: string } | null;
  busy: boolean;
  serverError?: string | null;
  onClose: () => void;
  onSubmit: (values: { quantity_delta: string; reason: string; note: string }) => void;
}) {
  const [delta, setDelta] = useState("");
  const [reason, setReason] = useState<string>(ADJUSTMENT_REASONS[0].value);
  const [note, setNote] = useState("");

  if (product === null) return null;

  const parsed = delta.trim() === "" ? Number.NaN : Number(delta);
  const valid = Number.isFinite(parsed) && parsed !== 0;
  const nextQty = valid ? product.qty_on_hand + parsed : product.qty_on_hand;
  const wouldGoNegative = valid && nextQty < 0;

  // The same rules the API enforces, said early so the answer sits beside the
  // field instead of arriving as a round trip. The API remains the authority.
  const fieldError =
    delta.trim() === ""
      ? undefined
      : !Number.isFinite(parsed)
        ? "Enter a number, for example -6 or 12"
        : parsed === 0
          ? "An adjustment of zero changes nothing"
          : wouldGoNegative
            ? `That would leave ${nextQty} ${product.unit_label}. Stock cannot go below zero.`
            : undefined;

  function reset() {
    setDelta("");
    setReason(ADJUSTMENT_REASONS[0].value);
    setNote("");
  }

  return (
    <Modal
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title="Adjust stock"
      description={`${product.name} · ${product.sku}`}
      footer={
        <>
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              reset();
              onClose();
            }}
            disabled={busy}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            form="adjust-stock-form"
            variant="primary"
            busy={busy}
            disabled={!valid || wouldGoNegative}
          >
            Adjust stock
          </Button>
        </>
      }
    >
      <form
        id="adjust-stock-form"
        noValidate
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (!valid || wouldGoNegative) return;
          onSubmit({ quantity_delta: delta.trim(), reason, note: note.trim() });
        }}
      >
        {serverError ? <Notice tone="danger">{serverError}</Notice> : null}

        <dl className="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
          <div>
            <dt className="text-[11px] text-ink-3">Currently in stock</dt>
            <dd className="tnum mt-0.5 font-medium text-ink">
              {quantity(product.qty_on_hand, product.unit_label)}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-ink-3">After this adjustment</dt>
            <dd
              className={
                wouldGoNegative
                  ? "tnum mt-0.5 font-medium text-danger"
                  : "tnum mt-0.5 font-medium text-ink"
              }
            >
              {valid ? quantity(nextQty, product.unit_label) : "—"}
            </dd>
          </div>
        </dl>

        <TextField
          label="Adjustment"
          type="text"
          inputMode="decimal"
          autoComplete="off"
          placeholder="-6 to remove, 12 to add"
          hint="A signed change, not a new total."
          error={fieldError}
          value={delta}
          onChange={(event) => setDelta(event.currentTarget.value)}
        />

        <SelectField
          label="Reason"
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
        >
          {ADJUSTMENT_REASONS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </SelectField>

        <TextAreaField
          label="Note"
          maxLength={280}
          placeholder="Optional. What happened?"
          hint="Kept with the adjustment in the audit trail."
          value={note}
          onChange={(event) => setNote(event.currentTarget.value)}
        />
      </form>
    </Modal>
  );
}
