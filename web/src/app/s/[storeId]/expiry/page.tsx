"use client";

import Link from "next/link";
import { use, useState } from "react";
import { CalendarClock, Megaphone, PackageX, TriangleAlert } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageHeader, StatTile } from "@/components/ui/page-header";
import { linkButtonClass } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, Notice, SkeletonRows, SkeletonTiles } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR, TRowHeader } from "@/components/ui/table";
import { useExpiring } from "@/lib/queries";
import { useActiveStore } from "@/lib/active-store";
import { count, formatDate, money, quantity } from "@/lib/format";

/**
 * Batches approaching their expiry date.
 *
 * The alert window is the vertical's own `near_expiry_days` - a chemist and a
 * baker need very different warnings, and that number is a configuration row
 * rather than a branch in this file. The slider overrides it per visit without
 * changing the store's setting.
 */
export default function ExpiryPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId: raw } = use(params);
  const storeId = Number(raw);
  const store = useActiveStore();

  const configured = store.config.near_expiry_days;
  const defaultWindow = typeof configured === "number" ? configured : 90;
  const [windowDays, setWindowDays] = useState(defaultWindow);

  const expiring = useExpiring(storeId, windowDays);
  const data = expiring.data;
  // undefined while it loads, so the subtitle says nothing rather than guessing.
  const tracksExpiry = data?.tracks_expiry;

  const batches = data?.batches ?? [];
  const valueAtRisk = batches
    .filter((batch) => !batch.is_expired)
    .reduce((sum, batch) => sum + batch.value, 0);

  return (
    <>
      <PageHeader
        title="Expiring soon"
        subtitle={
          // The flag comes first: claiming a store "tracks batches but sets no
          // window" directly above an empty state saying it does not track
          // them at all is worse than saying nothing.
          tracksExpiry === false
            ? `${store.vertical_name} does not track batches.`
            : typeof configured === "number"
              ? `${store.vertical_name} alerts at ${configured} days. That number is configuration, not code.`
              : `${store.vertical_name} tracks batches but sets no alert window, so everything dated is listed.`
        }
      />

      {/* The API answers this even when the flag is off, and says why - so the
          page explains itself rather than 404ing or hiding the nav link. */}
      {tracksExpiry === false ? (
        <Card>
          <EmptyState
            icon={<PackageX className="size-5" aria-hidden />}
            title="This store does not track batches"
            hint={`The expiry flag is off for ${store.vertical_name}, so nothing on this page applies. A pharmacy or a bakery would have it on.`}
          />
        </Card>
      ) : (
        <>
          {expiring.isPending ? (
            <SkeletonTiles count={3} />
          ) : expiring.isError ? (
            <Card>
              <ErrorState
                title="Unable to load batches"
                detail={expiring.error.message}
                onRetry={() => void expiring.refetch()}
              />
            </Card>
          ) : (
            <div className="grid gap-4 sm:grid-cols-3">
              <StatTile
                label="Batches in window"
                value={count(batches.length)}
                hint={`Expiring within ${count(windowDays)} days`}
                icon={<CalendarClock className="size-4" aria-hidden />}
              />
              <StatTile
                label="Already expired"
                value={count(data?.expired_count ?? 0)}
                hint="Pull these off the shelf first"
                tone={data?.expired_count ? "danger" : "neutral"}
                icon={<TriangleAlert className="size-4" aria-hidden />}
              />
              <StatTile
                label="Value at risk"
                value={money(valueAtRisk)}
                hint="Retail value of stock still in date"
              />
            </div>
          )}

          {data?.expired_count ? (
            <div className="mt-4">
              <Notice tone="danger">
                <strong>
                  {count(data.expired_count)} batch
                  {data.expired_count === 1 ? " is" : "es are"} already past the expiry date.
                </strong>{" "}
                Pull them off the shelf before anything else.
              </Notice>
            </div>
          ) : null}

          <Card className="mt-4">
            <Card.Header>
              <Card.Title hint="Soonest first">Batches</Card.Title>

              <label className="flex min-w-56 flex-1 items-center gap-3 text-xs text-ink-2 sm:flex-none sm:basis-72">
                <span className="whitespace-nowrap">Within</span>
                <input
                  type="range"
                  min={3}
                  max={365}
                  step={1}
                  value={windowDays}
                  onChange={(event) => setWindowDays(Number(event.currentTarget.value))}
                  aria-label="Show batches expiring within this many days"
                  className="flex-1 accent-[var(--primary)]"
                />
                <span className="tnum w-16 text-right whitespace-nowrap text-ink">
                  {count(windowDays)} days
                </span>
              </label>
            </Card.Header>

            {expiring.isPending ? (
              <SkeletonRows rows={8} columns={6} />
            ) : batches.length === 0 ? (
              <EmptyState
                title="No batch expires inside that window"
                hint="Widen the slider to look further ahead."
              />
            ) : (
              <Table caption="Batches by expiry date" minWidth="52rem">
                <THead>
                  <TH>Product</TH>
                  <TH>Batch</TH>
                  <TH>Expires</TH>
                  <TH align="right">Days left</TH>
                  <TH align="right">Quantity</TH>
                  <TH align="right">Value</TH>
                </THead>
                <TBody>
                  {batches.map((batch) => (
                    <TR key={batch.batch_id}>
                      <TRowHeader>
                        <span className="block truncate">{batch.name}</span>
                        <span className="block font-mono text-[11px] font-normal text-ink-3">
                          {batch.sku}
                        </span>
                      </TRowHeader>
                      <TD className="font-mono text-xs text-ink-2">
                        {batch.batch_no ?? "—"}
                      </TD>
                      <TD className="text-ink-2">{formatDate(batch.expiry_date)}</TD>
                      <TD align="right">
                        {batch.is_expired ? (
                          <Badge tone="danger">
                            expired {count(Math.abs(batch.days_left))}d ago
                          </Badge>
                        ) : (
                          <span
                            className={`tnum ${batch.days_left <= 7 ? "font-medium text-warning" : ""}`}
                          >
                            {count(batch.days_left)}
                          </span>
                        )}
                      </TD>
                      <TD align="right" numeric>
                        {quantity(batch.qty, batch.unit_label)}
                      </TD>
                      <TD align="right" numeric className="font-medium">
                        {money(batch.value)}
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            )}

            <Card.Footer>
              <p className="text-xs text-ink-3">
                Sales pick from these batches first-expired-first-out, so the oldest stock leaves
                the shelf before the newest without anyone deciding at the counter.
              </p>
              <Link
                href={`/s/${storeId}/marketing`}
                className={linkButtonClass("secondary", "sm")}
              >
                <Megaphone className="size-3.5" aria-hidden />
                Build a campaign around this stock
              </Link>
            </Card.Footer>
          </Card>
        </>
      )}
    </>
  );
}
