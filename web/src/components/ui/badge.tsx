import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

type Tone = "neutral" | "primary" | "accent" | "success" | "warning" | "danger" | "info";

const TONES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-ink-2 border-line",
  primary: "bg-primary-soft text-primary border-primary/20",
  accent: "bg-accent-soft text-accent border-accent/25",
  success: "bg-success-soft text-success border-success/25",
  warning: "bg-warning-soft text-warning border-warning/25",
  danger: "bg-danger-soft text-danger border-danger/25",
  info: "bg-info-soft text-info border-info/25",
};

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** The agent's customer segments, always the same colour wherever they appear. */
export function SegmentBadge({ segment }: { segment?: string | null }) {
  if (!segment) return <span className="text-ink-3">—</span>;
  const tone: Tone =
    segment === "VIP"
      ? "accent"
      : segment === "Regular"
        ? "success"
        : segment === "New"
          ? "info"
          : segment === "Inactive"
            ? "warning"
            : "neutral";
  return <Badge tone={tone}>{segment}</Badge>;
}

/** Reminder status, matching the icons the Streamlit outbox used. */
export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { tone: Tone; label: string }> = {
    queued: { tone: "warning", label: "Queued" },
    sent: { tone: "success", label: "Sent" },
    failed: { tone: "danger", label: "Failed" },
    dismissed: { tone: "neutral", label: "Dismissed" },
    completed: { tone: "success", label: "Completed" },
    refunded: { tone: "warning", label: "Refunded" },
  };
  const entry = map[status] ?? { tone: "neutral" as Tone, label: status };
  return <Badge tone={entry.tone}>{entry.label}</Badge>;
}
