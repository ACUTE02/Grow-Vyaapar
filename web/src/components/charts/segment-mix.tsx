"use client";

import { CHART_COLORS, ChartTable } from "./chart-parts";
import { count } from "@/lib/format";

const ORDER = ["New", "Regular", "VIP", "Inactive"] as const;

/**
 * The agent's four customer segments as one stacked bar.
 *
 * A pie was the obvious reach and the wrong one: four parts of a whole are read
 * far more accurately along a common baseline than as angles. Each segment is
 * separated by a 2px surface gap and directly labelled, so identity never rests
 * on colour alone - which is also what lets the palette's adjacent-pair ΔE sit
 * where it does.
 */
export function SegmentMix({ distribution }: { distribution: Record<string, number> }) {
  const parts = ORDER.map((name, index) => ({
    name,
    value: distribution[name] ?? 0,
    color: CHART_COLORS[index],
  }));
  const total = parts.reduce((sum, part) => sum + part.value, 0);

  if (total === 0) {
    return (
      <p className="py-6 text-center text-sm text-ink-3">
        No segments yet. Rebuild them to group customers by recency and spend.
      </p>
    );
  }

  return (
    <>
      <div className="flex h-7 w-full gap-0.5 overflow-hidden rounded-lg" role="img"
        aria-label={parts.map((part) => `${part.name}: ${part.value}`).join(", ")}>
        {parts
          .filter((part) => part.value > 0)
          .map((part) => (
            <div
              key={part.name}
              style={{ background: part.color, width: `${(part.value / total) * 100}%` }}
              title={`${part.name}: ${count(part.value)}`}
            />
          ))}
      </div>

      <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        {parts.map((part) => (
          <li key={part.name} className="min-w-0">
            <span className="flex items-center gap-1.5 text-xs text-ink-2">
              <span
                aria-hidden
                className="size-2.5 shrink-0 rounded-[3px]"
                style={{ background: part.color }}
              />
              {part.name}
            </span>
            <span className="tnum mt-0.5 block font-display text-lg font-semibold text-ink">
              {count(part.value)}
            </span>
            <span className="tnum text-[11px] text-ink-3">
              {Math.round((part.value / total) * 100)}%
            </span>
          </li>
        ))}
      </ul>

      <ChartTable
        caption="Customer count per segment"
        columns={["Segment", "Customers", "Share"]}
        rows={parts.map((part) => [
          part.name,
          count(part.value),
          `${Math.round((part.value / total) * 100)}%`,
        ])}
      />
    </>
  );
}
