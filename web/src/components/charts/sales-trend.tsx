"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { AXIS_STYLE, ChartTable, ChartTooltip } from "./chart-parts";
import { formatDayShort, money, moneyCompact } from "@/lib/format";

type Point = { date: string; net: number; invoices: number };

/**
 * Net sales over time. One series, so no legend: the card's own title names it.
 *
 * An area rather than a line because the quantity is a magnitude accumulating
 * from zero, and the fill is faint enough that the 2px stroke still reads as
 * the data.
 */
export function SalesTrend({ series }: { series: Point[] }) {
  return (
    <>
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={series} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="netFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.22} />
              <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          {/* Horizontal rules only, and recessive: the grid orients, it does
              not compete with the data. */}
          <CartesianGrid vertical={false} stroke="var(--chart-grid)" strokeDasharray="3 3" />
          <XAxis
            dataKey="date"
            tickFormatter={(value: string) => formatDayShort(value)}
            tick={AXIS_STYLE}
            tickLine={false}
            axisLine={{ stroke: "var(--chart-grid)" }}
            minTickGap={28}
          />
          <YAxis
            tickFormatter={(value: number) => moneyCompact(value)}
            tick={AXIS_STYLE}
            tickLine={false}
            axisLine={false}
            width={56}
          />
          <Tooltip
            cursor={{ stroke: "var(--chart-axis)", strokeDasharray: "3 3" }}
            content={({ active, payload, label }) =>
              active && payload?.length ? (
                <ChartTooltip
                  label={formatDayShort(String(label))}
                  rows={[
                    {
                      name: "Net sales",
                      value: money(Number(payload[0]?.value ?? 0)),
                      color: "var(--chart-1)",
                    },
                    {
                      name: "Bills",
                      value: String(payload[0]?.payload?.invoices ?? 0),
                    },
                  ]}
                />
              ) : null
            }
          />
          <Area
            type="monotone"
            dataKey="net"
            stroke="var(--chart-1)"
            strokeWidth={2}
            fill="url(#netFill)"
            // A dot per day is noise across 30+ points; the crosshair and
            // tooltip do the reading instead.
            dot={false}
            activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
          />
        </AreaChart>
      </ResponsiveContainer>

      <ChartTable
        caption="Net sales and bill count per day"
        columns={["Date", "Net sales", "Bills"]}
        rows={series.map((point) => [
          formatDayShort(point.date),
          money(point.net),
          point.invoices,
        ])}
      />
    </>
  );
}
