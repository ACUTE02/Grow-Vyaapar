"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * The pieces every chart in this app is made of.
 *
 * Colours are referenced as `var(--chart-N)` rather than resolved in JS, so a
 * theme change repaints the SVG without a re-render and without a hook that
 * reads computed styles. The categorical order is fixed: series 1 is always
 * --chart-1, whatever the filter leaves behind, so colour follows the entity
 * and never its rank.
 */
export const CHART_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
] as const;

export const AXIS_STYLE = {
  fontSize: 11,
  fill: "var(--chart-axis)",
} as const;

/** A tooltip that looks like the rest of the app rather than like Recharts. */
export function ChartTooltip({
  label,
  rows,
}: {
  label: ReactNode;
  rows: { name: string; value: string; color?: string }[];
}) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-pop">
      <p className="mb-1 font-medium text-ink">{label}</p>
      <ul className="space-y-0.5">
        {rows.map((row) => (
          <li key={row.name} className="flex items-center gap-2">
            {row.color ? (
              <span
                aria-hidden
                className="size-2 shrink-0 rounded-full"
                style={{ background: row.color }}
              />
            ) : null}
            {/* The value wears ink, not the series colour - the swatch carries
                identity, the text stays readable. */}
            <span className="text-ink-2">{row.name}</span>
            <span className="tnum ml-auto font-medium text-ink">{row.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A legend, always present once there are two or more series. */
export function ChartLegend({
  items,
}: {
  items: { label: string; color: string }[];
}) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5 text-xs text-ink-2">
          <span
            aria-hidden
            className="size-2.5 rounded-[3px]"
            style={{ background: item.color }}
          />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

/**
 * Every chart ships with the numbers behind it, one <details> away.
 *
 * That is the relief the guidance requires for a colour-vision or screen-reader
 * reader, and it costs one disclosure triangle.
 */
export function ChartTable({
  caption,
  columns,
  rows,
}: {
  caption: string;
  columns: string[];
  rows: (string | number)[][];
}) {
  return (
    <details className="mt-3 group">
      <summary className="cursor-pointer text-xs text-ink-3 hover:text-ink-2">
        View the numbers behind this chart
      </summary>
      <div className="mt-2 max-h-64 overflow-auto rounded-lg border border-line">
        <table className="w-full text-xs">
          <caption className="sr-only">{caption}</caption>
          <thead className="bg-surface-2 text-left">
            <tr>
              {columns.map((column, index) => (
                <th
                  key={column}
                  scope="col"
                  className={cn(
                    "px-3 py-1.5 font-medium text-ink-2",
                    index > 0 && "text-right",
                  )}
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td
                    key={cellIndex}
                    className={cn(
                      "px-3 py-1.5 text-ink",
                      cellIndex > 0 && "tnum text-right",
                    )}
                  >
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
