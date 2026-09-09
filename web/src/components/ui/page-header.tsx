import type { ReactNode } from "react";
import { count } from "@/lib/format";
import { cn } from "@/lib/cn";

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="font-display text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle === undefined ? null : (
          <p className="mt-1 text-sm text-ink-2">{subtitle}</p>
        )}
      </div>
      {actions === undefined ? null : (
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      )}
    </div>
  );
}

/**
 * A headline figure. The guidance is explicit that a single number is a stat
 * tile, not a chart - so these carry no sparkline unless one genuinely adds
 * something the number does not.
 */
export function StatTile({
  label,
  value,
  hint,
  tone = "neutral",
  icon,
}: {
  label: string;
  value: string;
  hint?: ReactNode;
  tone?: "neutral" | "primary" | "warning" | "danger";
  icon?: ReactNode;
}) {
  const accent = {
    neutral: "text-ink",
    primary: "text-primary",
    warning: "text-warning",
    danger: "text-danger",
  } as const;

  return (
    <div className="rounded-card border border-line bg-surface p-4 shadow-card">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-medium tracking-wider text-ink-3 uppercase">{label}</p>
        {icon === undefined ? null : <span className="text-ink-3">{icon}</span>}
      </div>
      <p
        className={cn(
          "tnum mt-2 font-display text-2xl font-semibold tracking-tight",
          accent[tone],
        )}
      >
        {value}
      </p>
      {hint === undefined ? null : <p className="mt-1.5 text-xs text-ink-3">{hint}</p>}
    </div>
  );
}

/** A count beside a heading, e.g. "Customers 1,204". */
export function CountPill({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined) return null;
  return (
    <span className="tnum rounded-full bg-surface-2 px-2 py-0.5 text-xs font-medium text-ink-2">
      {count(value)}
    </span>
  );
}
