"use client";

import { use, useState } from "react";
import { Card } from "@/components/ui/card";
import { PageHeader, StatTile } from "@/components/ui/page-header";
import { EmptyState, ErrorState, Skeleton, SkeletonTiles } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR, TRowHeader } from "@/components/ui/table";
import { SalesTrend } from "@/components/charts/sales-trend";
import { TopProductsBar } from "@/components/charts/top-products-bar";
import { SegmentMix } from "@/components/charts/segment-mix";
import { useSegmentSummary, useSummary, useTopProducts } from "@/lib/queries";
import { useActiveStore } from "@/lib/active-store";
import { money, count, quantity, formatDayShort } from "@/lib/format";
import { cn } from "@/lib/cn";

const RANGES = [
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
  { days: 365, label: "1 year" },
] as const;

export default function AnalyticsPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId: raw } = use(params);
  const storeId = Number(raw);
  const store = useActiveStore();
  const [days, setDays] = useState<number>(30);

  const summary = useSummary(storeId, days);
  const top = useTopProducts(storeId, days);
  const segments = useSegmentSummary(storeId);

  const series = summary.data?.series ?? [];
  const newCustomers = series.reduce((sum, point) => sum + point.new_customers, 0);
  const uniqueCustomers = series.reduce((sum, point) => sum + point.unique_customers, 0);
  const best = series.reduce<(typeof series)[number] | null>(
    (bestSoFar, point) => (bestSoFar === null || point.net > bestSoFar.net ? point : bestSoFar),
    null,
  );

  return (
    <>
      <PageHeader
        title="Analytics"
        subtitle={`${store.store_name} · every figure computed in SQL, none of it estimated.`}
        actions={
          // The time range is one control above the charts, and it drives all
          // of them - not a separate picker per card.
          <div role="group" aria-label="Time range" className="flex gap-1">
            {RANGES.map((range) => (
              <button
                key={range.days}
                type="button"
                aria-pressed={days === range.days}
                onClick={() => setDays(range.days)}
                className={cn(
                  "rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors",
                  days === range.days
                    ? "border-primary bg-primary text-primary-ink"
                    : "border-line bg-surface text-ink-2 hover:border-line-strong hover:text-ink",
                )}
              >
                {range.label}
              </button>
            ))}
          </div>
        }
      />

      {summary.isPending ? (
        <SkeletonTiles />
      ) : summary.isError ? (
        <Card>
          <ErrorState detail={summary.error.message} onRetry={() => void summary.refetch()} />
        </Card>
      ) : summary.data === undefined ? null : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile
            label={`Revenue · ${days} days`}
            value={money(summary.data.net_total)}
            hint="Net of discounts"
            tone="primary"
          />
          <StatTile
            label="Bills"
            value={count(summary.data.invoices)}
            hint={`Average ${money(summary.data.average_bill)}`}
          />
          <StatTile
            label="New customers"
            value={count(newCustomers)}
            hint={`${count(uniqueCustomers)} customer visits in total`}
          />
          <StatTile
            label="Best day"
            value={best ? money(best.net) : "—"}
            hint={best ? formatDayShort(best.date) : "No sales in this period"}
          />
        </div>
      )}

      <Card className="mt-4">
        <Card.Header>
          <Card.Title hint={`Net sales per day over the last ${days} days`}>
            Sales trend
          </Card.Title>
        </Card.Header>
        <Card.Body>
          {summary.isPending ? (
            <Skeleton className="h-60 w-full" />
          ) : series.length > 0 ? (
            <SalesTrend series={series} />
          ) : (
            <EmptyState
              title="No sales in this period"
              hint="Widen the range, or complete a bill on the POS page."
            />
          )}
        </Card.Body>
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <Card>
          <Card.Header>
            <Card.Title hint="By revenue, not by units">Product performance</Card.Title>
          </Card.Header>
          <Card.Body>
            {top.isPending ? (
              <Skeleton className="h-60 w-full" />
            ) : top.isError ? (
              <ErrorState detail={top.error.message} onRetry={() => void top.refetch()} />
            ) : (top.data ?? []).length === 0 ? (
              <EmptyState
                title="Nothing sold in this period"
                hint="Product performance appears once there are bills to rank."
              />
            ) : (
              <TopProductsBar products={top.data ?? []} />
            )}
          </Card.Body>
        </Card>

        <Card>
          <Card.Header>
            <Card.Title hint="How the base is distributed today">Customer growth</Card.Title>
          </Card.Header>
          <Card.Body>
            {segments.isPending ? (
              <Skeleton className="h-32 w-full" />
            ) : (
              <SegmentMix distribution={segments.data ?? {}} />
            )}
          </Card.Body>
        </Card>
      </div>

      {series.length > 0 ? (
        <Card className="mt-4">
          <Card.Header>
            <Card.Title hint="The rows behind every chart above">Daily detail</Card.Title>
          </Card.Header>
          <Table caption="Sales, bills and customers per day">
            <THead>
              <TH>Date</TH>
              <TH align="right">Net sales</TH>
              <TH align="right">Gross</TH>
              <TH align="right">Bills</TH>
              <TH align="right">Customers</TH>
              <TH align="right">New</TH>
            </THead>
            <TBody>
              {[...series].reverse().slice(0, 60).map((point) => (
                <TR key={point.date}>
                  <TRowHeader>{formatDayShort(point.date)}</TRowHeader>
                  <TD align="right" numeric className="font-medium">
                    {money(point.net)}
                  </TD>
                  <TD align="right" numeric className="text-ink-2">
                    {money(point.gross)}
                  </TD>
                  <TD align="right" numeric>
                    {count(point.invoices)}
                  </TD>
                  <TD align="right" numeric>
                    {count(point.unique_customers)}
                  </TD>
                  <TD align="right" numeric className="text-ink-2">
                    {count(point.new_customers)}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
          <Card.Footer>
            <p className="text-xs text-ink-3">
              Showing the most recent {Math.min(series.length, 60)} of {count(series.length)} days.
              Quantities elsewhere on this page are in {quantity(1, store.unit_labels.default)}
              units.
            </p>
          </Card.Footer>
        </Card>
      ) : null}
    </>
  );
}
