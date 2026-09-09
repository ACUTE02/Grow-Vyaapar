"use client";

import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

/* --------------------------------------------------------------------------
   Form controls that cannot be built without a label.

   Every control takes `label` as a required prop and wires htmlFor/id itself.
   A placeholder is not a label, and a control with neither is invisible to a
   screen reader - making it a required prop is cheaper than auditing for it
   later.
   -------------------------------------------------------------------------- */

const CONTROL =
  "w-full rounded-lg border border-line bg-surface px-3 text-sm text-ink " +
  "placeholder:text-ink-3 transition-colors " +
  "hover:border-line-strong focus:border-primary " +
  "disabled:cursor-not-allowed disabled:bg-surface-2 disabled:text-ink-3";

function Shell({
  id,
  label,
  hint,
  error,
  children,
  className,
}: {
  id: string;
  label: string;
  hint?: ReactNode;
  error?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <label
        htmlFor={id}
        className="mb-1.5 block text-xs font-medium tracking-wide text-ink-2 uppercase"
      >
        {label}
      </label>
      {children}
      {error ? (
        // aria-live so a validation message that appears after submit is
        // announced, not just drawn.
        <p id={`${id}-error`} role="alert" className="mt-1.5 text-xs text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="mt-1.5 text-xs text-ink-3">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

type FieldExtras = { label: string; hint?: ReactNode; error?: string; wrapClassName?: string };

export function TextField({
  label,
  hint,
  error,
  wrapClassName,
  className,
  id: providedId,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & FieldExtras) {
  const generatedId = useId();
  const id = providedId ?? generatedId;
  return (
    <Shell id={id} label={label} hint={hint} error={error} className={wrapClassName}>
      <input
        {...rest}
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        className={cn(CONTROL, "h-10", error && "border-danger", className)}
      />
    </Shell>
  );
}

export function SelectField({
  label,
  hint,
  error,
  wrapClassName,
  className,
  children,
  id: providedId,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement> & FieldExtras) {
  const generatedId = useId();
  const id = providedId ?? generatedId;
  return (
    <Shell id={id} label={label} hint={hint} error={error} className={wrapClassName}>
      <select
        {...rest}
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        className={cn(CONTROL, "h-10 pr-8", error && "border-danger", className)}
      >
        {children}
      </select>
    </Shell>
  );
}

export function TextAreaField({
  label,
  hint,
  error,
  wrapClassName,
  className,
  id: providedId,
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement> & FieldExtras) {
  const generatedId = useId();
  const id = providedId ?? generatedId;
  return (
    <Shell id={id} label={label} hint={hint} error={error} className={wrapClassName}>
      <textarea
        {...rest}
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
        className={cn(CONTROL, "min-h-20 py-2 leading-relaxed", error && "border-danger", className)}
      />
    </Shell>
  );
}

/** A labelled switch. The label is the click target, so no separate <label>. */
export function Toggle({
  label,
  description,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3 select-none">
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.currentTarget.checked)}
        className="peer sr-only"
      />
      <span
        aria-hidden
        className={cn(
          "mt-0.5 flex h-5 w-9 shrink-0 items-center rounded-full border p-0.5 transition-colors",
          checked ? "border-primary bg-primary" : "border-line-strong bg-surface-3",
          disabled && "opacity-50",
          "peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-primary",
        )}
      >
        <span
          className={cn(
            "size-4 rounded-full bg-white shadow-sm transition-transform",
            checked && "translate-x-4",
          )}
        />
      </span>
      <span className="min-w-0">
        <span className="block text-sm text-ink">{label}</span>
        {description ? (
          <span className="mt-0.5 block text-xs text-ink-3">{description}</span>
        ) : null}
      </span>
    </label>
  );
}
