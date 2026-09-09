"use client";

import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AXIS_STYLE, ChartTable, ChartTooltip } from "./chart-parts";
import { money, moneyCompact, quantity } from "@/lib/format";
import type { TopProduct } from "@/lib/types";

/**
 * Revenue by product, ranked. Horizontal bars because the labels are product
 * names - rotated names on a vertical axis are the classic unreadable chart.
 *
 * One measure, one hue: ranking is carried by position, so painting each bar a
 * different colour would encode nothing. The 4px rounded end sits on the far
 * side, anchored to the zero baseline.
 */
export function TopProductsBar({ products }: { products: TopProduct[] }) {
  const data = products.map((product) => ({
    name: product.name,
    revenue: product.revenue,
    qty: product.qty,
    unit: product.unit_label,
  }));

  return (
    <>
      <ResponsiveContainer width="100%" height={Math.max(200, data.length * 34)}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 4, right: 16, bottom: 0, left: 0 }}
          barCategoryGap={6}
        >
          <CartesianGrid horizontal={false} stroke="var(--chart-grid)" strokeDasharray="3 3" />
          <XAxis
            type="number"
            tickFormatter={(value: number) => moneyCompact(value)}
            tick={AXIS_STYLE}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            type="category"
            dataKey="name"
            tick={AXIS_STYLE}
            tickLine={false}
            axisLine={false}
            width={150}
            // A long product name is truncated rather than allowed to shove
            // the plot area off the card.
            tickFormatter={(value: string) =>
              value.length > 22 ? `${value.slice(0, 21)}…` : value
            }
          />
          <Tooltip
            cursor={{ fill: "var(--chart-grid)", fillOpacity: 0.35 }}
            content={({ active, payload }) =>
              active && payload?.length ? (
                <ChartTooltip
                  label={String(payload[0]?.payload?.name ?? "")}
                  rows={[
                    {
                      name: "Revenue",
                      value: money(Number(payload[0]?.value ?? 0)),
                      color: "var(--chart-1)",
                    },
                    {
                      name: "Sold",
                      value: quantity(
                        Number(payload[0]?.payload?.qty ?? 0),
                        String(payload[0]?.payload?.unit ?? ""),
                      ),
                    },
                  ]}
                />
              ) : null
            }
          />
          <Bar dataKey="revenue" radius={[0, 4, 4, 0]} maxBarSize={18}>
            {data.map((entry) => (
              <Cell key={entry.name} fill="var(--chart-1)" />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      <ChartTable
        caption="Revenue and quantity sold per product"
        columns={["Product", "Revenue", "Sold"]}
        rows={products.map((product) => [
          product.name,
          money(product.revenue),
          quantity(product.qty, product.unit_label),
        ])}
      />
    </>
  );
}
