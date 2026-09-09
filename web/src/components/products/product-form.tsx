"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { SelectField, TextField, Toggle } from "@/components/ui/field";
import { Notice } from "@/components/ui/states";
import type { Category, Product } from "@/lib/types";
import { useState } from "react";

const schema = z.object({
  sku: z.string().trim().min(1, "A SKU is required"),
  name: z.string().trim().min(2, "A product needs a name of at least 2 characters"),
  category_id: z.string().optional(),
  cost_price: z.coerce.number().min(0, "Cost cannot be negative"),
  sell_price: z.coerce.number().min(0, "Price cannot be negative"),
  gst_rate: z.coerce.number().min(0).max(50, "GST is a percentage"),
  qty_on_hand: z.coerce.number().min(0),
  reorder_point: z.coerce.number().min(0),
});

type Fields = z.input<typeof schema>;

/**
 * Add or edit a product.
 *
 * The fixed fields are the same for every store. The ones below them are not:
 * they are generated from the vertical's own product_schema, so a grocery asks
 * for brand and pack size and a pharmacy for composition, batch and expiry.
 * Nothing here enumerates a vertical - switch the store and the fields change.
 *
 * The API validates the same schema and is the authority; a mismatch comes
 * back as `serverError` rather than being re-implemented here as a second,
 * drifting copy of the rules.
 */
/** One field in the vertical's product_schema. */
type AttributeSpec = { type?: string; required?: boolean };

export function ProductForm({
  product,
  categories,
  unitLabel,
  productSchema,
  busy,
  serverError,
  onSubmit,
  onCancel,
}: {
  product?: Product;
  categories: Category[];
  unitLabel: string;
  /** The vertical's own attribute schema. Drives the fields below - a grocery
   *  asks for brand and pack size, a pharmacy for composition and batch. */
  productSchema: Record<string, unknown>;
  busy: boolean;
  serverError?: string | null;
  onSubmit: (body: Record<string, unknown>) => void;
  onCancel: () => void;
}) {
  const [active, setActive] = useState(product?.is_active ?? true);

  const attributeFields = Object.entries(productSchema) as [string, AttributeSpec][];
  const [attributes, setAttributes] = useState<Record<string, string | boolean>>(() => {
    const initial: Record<string, string | boolean> = {};
    for (const [name, spec] of attributeFields) {
      const existing = (product?.attributes ?? {})[name];
      initial[name] =
        spec?.type === "boolean"
          ? Boolean(existing)
          : existing === undefined || existing === null
            ? ""
            : String(existing);
    }
    return initial;
  });

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<Fields>({
    resolver: zodResolver(schema),
    defaultValues: {
      sku: product?.sku ?? "",
      name: product?.name ?? "",
      category_id: product?.category_id ? String(product.category_id) : "",
      cost_price: product?.cost_price ?? 0,
      sell_price: product?.sell_price ?? 0,
      gst_rate: product?.gst_rate ?? 0,
      qty_on_hand: product?.qty_on_hand ?? 0,
      reorder_point: product?.reorder_point ?? 0,
    },
  });

  return (
    <form
      noValidate
      onSubmit={handleSubmit((fields) => {
        const body: Record<string, unknown> = {
          name: String(fields.name).trim(),
          category_id: fields.category_id ? Number(fields.category_id) : null,
          cost_price: Number(fields.cost_price),
          sell_price: Number(fields.sell_price),
          gst_rate: Number(fields.gst_rate),
          qty_on_hand: Number(fields.qty_on_hand),
          reorder_point: Number(fields.reorder_point),
          is_active: active,
          // Typed the way the schema declares, because the API validates the
          // types as well as the presence - a number sent as "12" is refused.
          attributes: Object.fromEntries(
            attributeFields
              .map(([name, spec]) => {
                const raw = attributes[name];
                if (spec?.type === "boolean") return [name, Boolean(raw)];
                if (raw === "" || raw === undefined) return [name, undefined];
                if (spec?.type === "number") return [name, Number(raw)];
                return [name, raw];
              })
              .filter(([, value]) => value !== undefined),
          ),
        };
        // The SKU identifies the row, so it is set once and never patched.
        if (product === undefined) body.sku = String(fields.sku).trim();
        onSubmit(body);
      })}
      className="space-y-4"
    >
      {serverError ? <Notice tone="danger">{serverError}</Notice> : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label="SKU"
          disabled={product !== undefined}
          hint={product ? "A SKU identifies the product and cannot be changed" : undefined}
          error={errors.sku?.message}
          {...register("sku")}
        />
        <TextField label="Name" error={errors.name?.message} {...register("name")} />
      </div>

      <SelectField label="Category" {...register("category_id")}>
        <option value="">No category</option>
        {categories.map((category) => (
          <option key={category.id} value={category.id}>
            {category.name}
          </option>
        ))}
      </SelectField>

      <div className="grid gap-4 sm:grid-cols-3">
        <TextField
          label="Cost price"
          type="number"
          step="0.01"
          error={errors.cost_price?.message}
          {...register("cost_price")}
        />
        <TextField
          label="Sell price"
          type="number"
          step="0.01"
          error={errors.sell_price?.message}
          {...register("sell_price")}
        />
        <TextField
          label="GST %"
          type="number"
          step="0.01"
          error={errors.gst_rate?.message}
          {...register("gst_rate")}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          label={`Stock on hand (${unitLabel})`}
          type="number"
          step="any"
          error={errors.qty_on_hand?.message}
          {...register("qty_on_hand")}
        />
        <TextField
          label={`Reorder point (${unitLabel})`}
          type="number"
          step="any"
          hint="Below this, it appears in Needs reordering"
          error={errors.reorder_point?.message}
          {...register("reorder_point")}
        />
      </div>

      {attributeFields.length > 0 ? (
        <fieldset className="rounded-lg border border-line p-3">
          <legend className="px-1 text-xs font-medium tracking-wide text-ink-2 uppercase">
            {/* These come from the vertical row, not from this file. Switch the
                store and the fields change with it. */}
            Details this vertical asks for
          </legend>
          <div className="grid gap-4 sm:grid-cols-2">
            {attributeFields.map(([name, spec]) => {
              const label = name.replace(/_/g, " ") + (spec?.required ? " *" : "");
              if (spec?.type === "boolean") {
                return (
                  <div key={name} className="flex items-end pb-1">
                    <Toggle
                      label={label}
                      checked={Boolean(attributes[name])}
                      onChange={(next) =>
                        setAttributes((current) => ({ ...current, [name]: next }))
                      }
                    />
                  </div>
                );
              }
              return (
                <TextField
                  key={name}
                  label={label}
                  required={spec?.required}
                  type={
                    spec?.type === "number" ? "number" : spec?.type === "date" ? "date" : "text"
                  }
                  step={spec?.type === "number" ? "any" : undefined}
                  value={String(attributes[name] ?? "")}
                  onChange={(event) => {
                    // Read the value now, not inside the updater: React has
                    // nulled currentTarget by the time that callback runs.
                    const value = event.currentTarget.value;
                    setAttributes((current) => ({ ...current, [name]: value }));
                  }}
                />
              );
            })}
          </div>
        </fieldset>
      ) : null}

      <Toggle
        label="Sell this product"
        description="An inactive product stays in reports but cannot be added to a bill."
        checked={active}
        onChange={setActive}
      />

      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" busy={busy}>
          {product ? "Save changes" : "Add product"}
        </Button>
      </div>
    </form>
  );
}
