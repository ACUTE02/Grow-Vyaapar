"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { TextField, TextAreaField } from "@/components/ui/field";
import { Notice } from "@/components/ui/states";
import { normaliseMobile } from "@/lib/format";
import type { Customer } from "@/lib/types";

/**
 * One form for adding and for editing.
 *
 * The phone rule mirrors the API's (ten digits, starting 6-9) so an obvious
 * mistake is caught before the round trip - but the API still enforces it, and
 * a conflict it detects (the number already belongs to someone) comes back as
 * `serverError` rather than being guessed at here.
 */
const schema = z.object({
  name: z.string().trim().min(2, "A customer needs a name of at least 2 characters"),
  phone: z
    .string()
    .refine(
      (value) => normaliseMobile(value) !== null,
      "Enter a 10-digit Indian mobile number starting with 6-9",
    ),
  dob: z.string().optional(),
  anniversary: z.string().optional(),
  notes: z.string().optional(),
});

export type CustomerFields = z.infer<typeof schema>;

export function CustomerForm({
  customer,
  serverError,
  busy,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  customer?: Customer;
  serverError?: string | null;
  busy: boolean;
  submitLabel: string;
  onSubmit: (changes: Record<string, unknown>) => void;
  onCancel?: () => void;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CustomerFields>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: customer?.name ?? "",
      phone: customer?.phone ?? "",
      dob: customer?.dob?.slice(0, 10) ?? "",
      anniversary: customer?.anniversary?.slice(0, 10) ?? "",
      notes: customer?.notes ?? "",
    },
  });

  function submit(fields: CustomerFields) {
    const next = {
      name: fields.name.trim(),
      phone: normaliseMobile(fields.phone)!,
      dob: fields.dob || null,
      anniversary: fields.anniversary || null,
      notes: fields.notes?.trim() || null,
    };

    if (customer === undefined) {
      onSubmit(next);
      return;
    }

    // PATCH only what actually changed: the API applies a partial update, so
    // an untouched field must not be sent at all - that is what keeps clearing
    // a date distinguishable from never having touched it.
    const current: Record<string, unknown> = {
      name: customer.name,
      phone: customer.phone,
      dob: customer.dob?.slice(0, 10) ?? null,
      anniversary: customer.anniversary?.slice(0, 10) ?? null,
      notes: customer.notes ?? null,
    };
    const changes = Object.fromEntries(
      Object.entries(next).filter(([key, value]) => value !== current[key]),
    );
    onSubmit(changes);
  }

  return (
    <form onSubmit={handleSubmit(submit)} noValidate className="space-y-4">
      {serverError ? <Notice tone="danger">{serverError}</Notice> : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label="Name" autoComplete="off" error={errors.name?.message} {...register("name")} />
        <TextField
          label="Phone"
          inputMode="numeric"
          placeholder="10 digits, starts 6-9"
          error={errors.phone?.message}
          {...register("phone")}
        />
        <TextField label="Date of birth" type="date" error={errors.dob?.message} {...register("dob")} />
        <TextField
          label="Anniversary"
          type="date"
          error={errors.anniversary?.message}
          {...register("anniversary")}
        />
      </div>

      <TextAreaField
        label="Notes"
        hint="Anything the counter should remember. Not sent to the customer."
        {...register("notes")}
      />

      <div className="flex justify-end gap-2">
        {onCancel ? (
          <Button type="button" variant="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        ) : null}
        <Button type="submit" variant="primary" busy={busy}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
