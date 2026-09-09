"use client";

import { use, useState } from "react";
import { Boxes, PackageCheck, Snowflake, TrendingDown } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageHeader, StatTile } from "@/components/ui/page-header";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, Notice, SkeletonRows } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR, TRowHeader } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { AdjustStockDialog } from "@/components/inventory/adjust-stock-dialog";
import { useAdjustStock, useDeadStock, useLowStock } from "@/lib/queries";
import { canManage, useSession } from "@/lib/session";
import { useActiveStore } from "@/lib/active-store";
import { money, quantity, count, relativeDays } from "@/lib/format";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { StockRow } from "@/lib/types";

type Tab = "low" | "dead";

/**
 * Stock, split by the two questions a shopkeeper actually asks: what do I need
 * to buy, and what is my money sitting in.
 *
 * Both thresholds come from the store's vertical configuration - a kirana's
 * dead-stock window is not a boutique's - so the copy quotes the store's own
 * numbers rather than a hard-coded one.
 */
export default function InventoryPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId: raw } = use(params);
  const storeId = Number(raw);
  const store = useActiveStore();
  const [tab, setTab] = useState<Tab>("low");

  const low = useLowStock(storeId);
  const dead = useDeadStock(storeId);

  const session = useSession();
  const manager = canManage(session.user);
  const toast = useToast();
  const adjust = useAdjustStock(storeId);
  const [adjusting, setAdjusting] = useState<StockRow | null>(null);

  const deadStockDays = store.config.dead_stock_days;
  const reorderCycle = store.config.reorder_cycle_days;

  const lowValue = (low.data ?? []).reduce(
    (sum, row) => sum + row.qty_on_hand * row.sell_price,
    0,
  );
  const deadValue = (dead.data ?? []).reduce(
    (sum, row) => sum + row.qty_on_hand * row.sell_price,
    0,
  );

  const active = tab === "low" ? low : dead;
  const rows = active.data ?? [];

  return (
    <>
      <PageHeader
        title="Inventory"
        subtitle={`Stock levels for ${store.store_name}, against this vertical's own thresholds.`}
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Needs reordering"
          value={count(low.data?.length ?? 0)}
          hint="At or below the reorder point"
          tone={low.data?.length ? "warning" : "neutral"}
          icon={<TrendingDown className="size-4" aria-hidden />}
        />
        <StatTile
          label="Out of stock"
          value={count((low.data ?? []).filter((row) => row.qty_on_hand <= 0).length)}
          hint="Cannot be sold at all"
          tone={(low.data ?? []).some((row) => row.qty_on_hand <= 0) ? "danger" : "neutral"}
          icon={<PackageCheck className="size-4" aria-hidden />}
        />
        <StatTile
          label="Dead stock"
          value={count(dead.data?.length ?? 0)}
          hint={
            typeof deadStockDays === "number"
              ? `Unsold for ${deadStockDays}+ days`
              : "Unsold for a long time"
          }
          icon={<Snowflake className="size-4" aria-hidden />}
        />
        <StatTile
          label="Value at risk"
          value={money(deadValue)}
          hint="Retail value sitting in dead stock"
          icon={<Boxes className="size-4" aria-hidden />}
        />
      </div>

      <Card className="mt-4">
        <Card.Header>
          {/* A tab list, not two boolean props on one table. */}
          <div role="tablist" aria-label="Stock view" className="flex gap-1">
            <TabButton
              selected={tab === "low"}
              onSelect={() => setTab("low")}
              label="Needs reordering"
              badge={low.data?.length}
            />
            <TabButton
              selected={tab === "dead"}
              onSelect={() => setTab("dead")}
              label="Dead stock"
              badge={dead.data?.length}
            />
          </div>
          <p className="text-xs text-ink-3">
            {tab === "low"
              ? `Retail value shown: ${money(lowValue)}` +
                (typeof reorderCycle === "number" ? ` · reorder cycle ${reorderCycle} days` : "")
              : `Retail value shown: ${money(deadValue)}`}
          </p>
        </Card.Header>

        {active.isPending ? (
          <SkeletonRows rows={8} columns={5} />
        ) : active.isError ? (
          <ErrorState detail={active.error.message} onRetry={() => void active.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState
            title={tab === "low" ? "Everything is in stock" : "No dead stock"}
            hint={
              tab === "low"
                ? `Nothing in ${store.store_name} has fallen to its reorder point.`
                : `Nothing has gone unsold long enough to count as dead stock in ${store.store_name}.`
            }
          />
        ) : (
          <Table caption={tab === "low" ? "Products needing a reorder" : "Products not selling"}>
            <THead>
              <TH>Product</TH>
              <TH align="right">In stock</TH>
              <TH align="right">Reorder point</TH>
              {tab === "dead" ? <TH>Last sold</TH> : null}
              <TH align="right">Retail value</TH>
              <TH>Status</TH>
              {manager ? <TH>Adjust</TH> : null}
            </THead>
            <TBody>
              {rows.map((row) => (
                <TR key={row.product_id}>
                  <TRowHeader>
                    <span className="block truncate">{row.name}</span>
                    <span className="block font-mono text-[11px] font-normal text-ink-3">
                      {row.sku}
                    </span>
                  </TRowHeader>
                  <TD align="right" numeric className="font-medium">
                    {quantity(row.qty_on_hand, row.unit_label)}
                  </TD>
                  <TD align="right" numeric className="text-ink-2">
                    {quantity(row.reorder_point, row.unit_label)}
                  </TD>
                  {tab === "dead" ? (
                    <TD className="text-ink-2">{relativeDays(row.days_since_sold)}</TD>
                  ) : null}
                  <TD align="right" numeric>
                    {money(row.qty_on_hand * row.sell_price)}
                  </TD>
                  <TD>
                    {row.qty_on_hand <= 0 ? (
                      <Badge tone="danger">Out of stock</Badge>
                    ) : tab === "low" ? (
                      <Badge tone="warning">Reorder</Badge>
                    ) : (
                      <Badge tone="neutral">Not selling</Badge>
                    )}
                  </TD>
                  {manager ? (
                    <TD>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => {
                          adjust.reset();
                          setAdjusting(row);
                        }}
                      >
                        Adjust stock
                      </Button>
                    </TD>
                  ) : null}
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <Notice tone="info">
        Stock moves on its own when a bill is completed or refunded and when a purchase order is
        received, so those movements trace back to the event that caused them. Adjust stock is for
        the ones that do not have an event: breakage, a miscount, something found at the back of a
        shelf. It asks for a reason and records who made it, so a shelf can never change with
        nothing saying why.
      </Notice>

      <AdjustStockDialog
        open={adjusting !== null}
        product={adjusting}
        busy={adjust.isPending}
        serverError={adjust.error instanceof ApiError ? adjust.error.message : null}
        onClose={() => {
          adjust.reset();
          setAdjusting(null);
        }}
        onSubmit={(values) => {
          if (adjusting === null) return;
          adjust.mutate(
            { productId: adjusting.product_id, ...values },
            {
              onSuccess: (result) => {
                setAdjusting(null);
                toast.success(
                  `${result.sku} adjusted to ${quantity(result.qty_after, result.unit_label)}.`,
                );
              },
            },
          );
        }}
      />
    </>
  );
}

function TabButton({
  selected,
  onSelect,
  label,
  badge,
}: {
  selected: boolean;
  onSelect: () => void;
  label: string;
  badge?: number;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={selected}
      onClick={onSelect}
      className={cn(
        "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
        selected ? "bg-primary-soft text-primary" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
      )}
    >
      {label}
      {badge === undefined ? null : (
        <span className="tnum rounded-full bg-surface-3 px-1.5 text-[11px] text-ink-2">
          {count(badge)}
        </span>
      )}
    </button>
  );
}
