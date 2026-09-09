"use client";

import { use } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowRight,
  IndianRupee,
  Receipt,
  TrendingUp,
  Users,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageHeader, StatTile } from "@/components/ui/page-header";
import { Button, linkButtonClass } from "@/components/ui/button";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { EmptyState, ErrorState, SkeletonRows, SkeletonTiles } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { SalesTrend } from "@/components/charts/sales-trend";
import { SegmentMix } from "@/components/charts/segment-mix";
import {
  useLowStock,
  useRebuildSegments,
  useSegmentSummary,
  useSummary,
  useTransactions,
} from "@/lib/queries";
import { useActiveStore } from "@/lib/active-store";
import { useToast } from "@/components/ui/toast";
import { formatDateTime, money, count, quantity } from "@/lib/format";

export default function DashboardPage({
  params,
}: {
  params: Promise<{ storeId: string }>;
}) {
  const { storeId: raw } = use(params);
  const storeId = Number(raw);
  const store = useActiveStore();
  const toast = useToast();

  const summary = useSummary(storeId, 30);
  const recent = useTransactions(storeId, { limit: 8, offset: 0 });
  const lowStock = useLowStock(storeId);
  const segments = useSegmentSummary(storeId);
  const rebuild = useRebuildSegments(storeId);

  const today = summary.data?.series.at(-1);

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle={`${store.store_name} · ${store.city} · last 30 days`}
        actions={
          <Button
            variant="secondary"
            size="sm"
            busy={rebuild.isPending}
            onClick={() =>
              rebuild.mutate(undefined, {
                onSuccess: (data) => {
                  const total = Object.values(data.distribution ?? {}).reduce(
                    (sum, value) => sum + value,
                    0,
                  );
                  toast.success(`Segments rebuilt for ${count(total)} customers.`);
                },
                onError: (error) => toast.error(error.message),
              })
            }
          >
            Rebuild segments
          </Button>
        }
      />

      {summary.isLoading ? (
        <SkeletonTiles />
      ) : summary.isError ? (
        <Card>
          <ErrorState
            detail={summary.error.message}
            onRetry={() => void summary.refetch()}
          />
        </Card>
      ) : summary.data === undefined ? null : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatTile
            label="Sales today"
            value={money(today?.net ?? 0)}
            hint={`${count(today?.invoices ?? 0)} bills`}
            tone="primary"
            icon={<IndianRupee className="size-4" aria-hidden />}
          />
          <StatTile
            label="Revenue · 30 days"
            value={money(summary.data.net_total)}
            hint={`${count(summary.data.invoices)} bills`}
            icon={<TrendingUp className="size-4" aria-hidden />}
          />
          <StatTile
            label="Average bill"
            value={money(summary.data.average_bill)}
            hint="Net of discounts, including GST"
            icon={<Receipt className="size-4" aria-hidden />}
          />
          <StatTile
            label="Low stock"
            value={count(lowStock.data?.length ?? 0)}
            hint={
              lowStock.data?.length
                ? "Items at or below their reorder point"
                : "Nothing needs reordering"
            }
            tone={lowStock.data?.length ? "warning" : "neutral"}
            icon={<AlertTriangle className="size-4" aria-hidden />}
          />
        </div>
      )}

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card>
          <Card.Header>
            <Card.Title hint="Net of discounts, per day">Sales trend</Card.Title>
          </Card.Header>
          <Card.Body>
            {summary.isLoading ? (
              <div className="skeleton h-60 rounded-lg" />
            ) : summary.data && summary.data.series.length > 0 ? (
              <SalesTrend series={summary.data.series} />
            ) : (
              <EmptyState
                title="No sales in this period yet"
                hint="Complete a bill on the POS page and the trend starts here."
                action={
                  <Link href={`/s/${storeId}/pos`} className={linkButtonClass("primary", "sm")}>
                    Open POS
                  </Link>
                }
              />
            )}
          </Card.Body>
        </Card>

        <Card>
          <Card.Header>
            <Card.Title hint="Recency, frequency and spend">Customer segments</Card.Title>
          </Card.Header>
          <Card.Body>
            {segments.isLoading ? (
              <div className="skeleton h-32 rounded-lg" />
            ) : (
              <SegmentMix distribution={segments.data ?? {}} />
            )}
          </Card.Body>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card>
          <Card.Header>
            <Card.Title>Recent bills</Card.Title>
            <Link
              href={`/s/${storeId}/analytics`}
              className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              All analytics <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          </Card.Header>
          {recent.isLoading ? (
            <SkeletonRows rows={6} columns={4} />
          ) : recent.isError ? (
            <ErrorState detail={recent.error.message} onRetry={() => void recent.refetch()} />
          ) : recent.data === undefined ? null : recent.data.items.length === 0 ? (
            <EmptyState
              title="No bills yet"
              hint="The first sale you complete will appear here."
            />
          ) : (
            <Table caption="Most recent bills" minWidth="34rem">
              <THead>
                <TH>Invoice</TH>
                <TH>Customer</TH>
                <TH>When</TH>
                <TH align="right">Total</TH>
                <TH>Status</TH>
              </THead>
              <TBody>
                {recent.data.items.map((row) => (
                  <TR key={row.id}>
                    <TD className="font-mono text-xs">{row.invoice_no}</TD>
                    <TD>{row.customer_name ?? <span className="text-ink-3">Walk-in</span>}</TD>
                    <TD className="text-ink-2">{formatDateTime(row.created_at)}</TD>
                    <TD align="right" numeric className="font-medium">
                      {money(row.total)}
                    </TD>
                    <TD>
                      <StatusBadge status={row.status} />
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>

        <Card>
          <Card.Header>
            <Card.Title hint="At or below the reorder point">Needs reordering</Card.Title>
            <Link
              href={`/s/${storeId}/inventory`}
              className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
            >
              Inventory <ArrowRight className="size-3.5" aria-hidden />
            </Link>
          </Card.Header>
          {lowStock.isLoading ? (
            <SkeletonRows rows={5} columns={2} />
          ) : lowStock.isError ? (
            <ErrorState detail={lowStock.error.message} onRetry={() => void lowStock.refetch()} />
          ) : lowStock.data === undefined ? null : lowStock.data.length === 0 ? (
            <EmptyState
              title="Everything is in stock"
              hint={`Nothing in ${store.store_name} has fallen to its reorder point.`}
            />
          ) : (
            <ul className="divide-y divide-line">
              {lowStock.data.slice(0, 8).map((row) => (
                <li key={row.product_id} className="flex items-center gap-3 px-4 py-2.5">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-ink">{row.name}</span>
                    <span className="block font-mono text-[11px] text-ink-3">{row.sku}</span>
                  </span>
                  <Badge tone={row.qty_on_hand <= 0 ? "danger" : "warning"}>
                    {quantity(row.qty_on_hand, row.unit_label)}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <p className="mt-6 flex items-center gap-1.5 text-xs text-ink-3">
        <Users className="size-3.5" aria-hidden />
        Every figure above is computed in SQL. The assistant narrates these numbers; it never
        invents one.
      </p>
    </>
  );
}
