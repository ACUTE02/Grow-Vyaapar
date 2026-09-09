"use client";

import { ArrowRight, CircleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/cn";
import type { Job } from "@/lib/types";

const LABELS: Record<string, string> = {
  pending: "Pending",
  in_progress: "In progress",
  ready: "Ready",
  delivered: "Delivered",
  cancelled: "Cancelled",
};

export function statusLabel(status: string): string {
  return LABELS[status] ?? status.replace(/_/g, " ");
}

/**
 * One job on the board.
 *
 * The buttons come from the job's own `next_statuses`. The status graph lives
 * in the service layer and the API hands it over per job, so this component
 * never encodes which transition is legal - a rule change on the server needs
 * no change here.
 */
export function JobCard({
  job,
  busy,
  onAdvance,
}: {
  job: Job;
  busy: boolean;
  onAdvance: (status: string) => void;
}) {
  return (
    <li
      className={cn(
        "rounded-lg border bg-surface p-3 shadow-card transition-colors",
        job.is_overdue ? "border-danger/40" : "border-line",
      )}
    >
      <div className="flex items-start gap-2">
        {job.is_overdue ? (
          <CircleAlert className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
        ) : null}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-ink">
            {job.customer_name ?? `Customer ${job.customer_id}`}
          </p>
          <p className="mt-0.5 font-mono text-[11px] text-ink-3">{job.type}</p>
        </div>
      </div>

      {job.promised_date ? (
        <p
          className={cn(
            "mt-1.5 text-[11px]",
            job.is_overdue ? "font-medium text-danger" : "text-ink-3",
          )}
        >
          {job.is_overdue ? "Overdue since " : "Promised "}
          {formatDate(job.promised_date)}
        </p>
      ) : null}

      {job.next_statuses.length > 0 ? (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {job.next_statuses.map((next) => (
            <Button
              key={next}
              size="sm"
              variant={next === "cancelled" ? "ghost" : "secondary"}
              busy={busy}
              onClick={() => onAdvance(next)}
              className="text-[12px]"
            >
              {next === "cancelled" ? null : (
                <ArrowRight className="size-3" aria-hidden />
              )}
              {statusLabel(next)}
            </Button>
          ))}
        </div>
      ) : null}
    </li>
  );
}
