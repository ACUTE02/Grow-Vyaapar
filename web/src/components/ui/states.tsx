import type { ReactNode } from "react";
import { AlertTriangle, Inbox, RotateCw } from "lucide-react";
import { Button } from "./button";
import { cn } from "@/lib/cn";

/* --------------------------------------------------------------------------
   The four states every page owes the user: loading, empty, error, and the
   real thing. Kept together so it is obvious when a page is missing one.
   -------------------------------------------------------------------------- */

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton rounded-md", className)} aria-hidden />;
}

/** A table's loading state should have the table's shape, not a spinner in the
 *  middle of an empty box - the layout must not jump when the rows land. */
export function SkeletonRows({
  rows = 8,
  columns = 5,
}: {
  rows?: number;
  columns?: number;
}) {
  return (
    <div className="divide-y divide-line" role="status" aria-label="Loading rows">
      {Array.from({ length: rows }, (_, rowIndex) => (
        <div key={rowIndex} className="flex items-center gap-4 px-4 py-3">
          {Array.from({ length: columns }, (_, columnIndex) => (
            <Skeleton
              key={columnIndex}
              className={cn(
                "h-4",
                columnIndex === 0 ? "w-[22%]" : columnIndex === columns - 1 ? "w-[12%]" : "w-[15%]",
              )}
            />
          ))}
        </div>
      ))}
      <span className="sr-only">Loading</span>
    </div>
  );
}

export function SkeletonTiles({ count = 4 }: { count?: number }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" role="status" aria-label="Loading">
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="rounded-card border border-line bg-surface p-4">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="mt-3 h-7 w-32" />
          <Skeleton className="mt-3 h-3 w-20" />
        </div>
      ))}
    </div>
  );
}

/**
 * An empty state says what the user can do next, not merely that there is
 * nothing here - so the action is part of the component, not an afterthought.
 */
export function EmptyState({
  title,
  hint,
  action,
  icon,
}: {
  title: string;
  hint?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <span className="mb-3 grid size-11 place-items-center rounded-full bg-surface-2 text-ink-3">
        {icon ?? <Inbox className="size-5" aria-hidden />}
      </span>
      <p className="font-display text-[15px] font-semibold text-ink">{title}</p>
      {hint === undefined ? null : (
        <p className="mt-1.5 max-w-md text-sm text-ink-2">{hint}</p>
      )}
      {action === undefined ? null : <div className="mt-4">{action}</div>}
    </div>
  );
}

/**
 * An error state is not a dead end: it says what failed and offers the retry.
 * `detail` carries the API's own message, which is written for a shopkeeper
 * ("Phone 98… already belongs to Ronit") rather than a stack trace.
 */
export function ErrorState({
  title = "That did not work",
  detail,
  onRetry,
}: {
  title?: string;
  detail?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center px-6 py-12 text-center"
    >
      <span className="mb-3 grid size-11 place-items-center rounded-full bg-danger-soft text-danger">
        <AlertTriangle className="size-5" aria-hidden />
      </span>
      <p className="font-display text-[15px] font-semibold text-ink">{title}</p>
      {detail ? <p className="mt-1.5 max-w-md text-sm text-ink-2">{detail}</p> : null}
      {onRetry ? (
        <Button className="mt-4" onClick={onRetry} variant="secondary" size="sm">
          <RotateCw className="size-3.5" aria-hidden />
          Try again
        </Button>
      ) : null}
    </div>
  );
}

/** An inline banner for a non-fatal problem that should not replace the page. */
export function Notice({
  tone = "info",
  children,
}: {
  tone?: "info" | "warning" | "danger" | "success";
  children: ReactNode;
}) {
  const tones = {
    info: "bg-info-soft text-info border-info/25",
    warning: "bg-warning-soft text-warning border-warning/25",
    danger: "bg-danger-soft text-danger border-danger/25",
    success: "bg-success-soft text-success border-success/25",
  } as const;
  return (
    <div className={cn("rounded-lg border px-3.5 py-2.5 text-sm", tones[tone])}>
      {children}
    </div>
  );
}
