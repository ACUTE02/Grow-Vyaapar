"use client";

import { use, useState } from "react";
import { useForm } from "react-hook-form";
import { IndianRupee, PackageCheck, ShieldCheck, Truck } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageHeader, StatTile } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { TextField } from "@/components/ui/field";
import { EmptyState, ErrorState, Notice, SkeletonRows } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR, TRowHeader } from "@/components/ui/table";
import { ConfirmDialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { OrderBuilder } from "@/components/purchasing/order-builder";
import {
  usePendingPayments,
  useProducts,
  usePurchaseOrders,
  usePurchasingActions,
  usePurchasingAudit,
  useReorderForecast,
  useSuppliers,
} from "@/lib/queries";
import { useActiveStore } from "@/lib/active-store";
import { useSession, canManage } from "@/lib/session";
import { count, formatDate, formatDateTime, money } from "@/lib/format";
import { cn } from "@/lib/cn";

type Tab = "suppliers" | "orders" | "audit";
type SupplierFields = { name: string; phone: string; gstin: string; rating: string };

export default function PurchasingPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId: raw } = use(params);
  const storeId = Number(raw);
  const store = useActiveStore();
  const session = useSession();
  const toast = useToast();

  const [tab, setTab] = useState<Tab>("orders");
  const [supplierError, setSupplierError] = useState<string | null>(null);
  const [orderError, setOrderError] = useState<string | null>(null);
  const [confirmReceive, setConfirmReceive] = useState<number | null>(null);

  const manager = canManage(session.user);
  const tracksExpiry = Boolean(store.feature_flags.expiry);

  const pending = usePendingPayments(storeId);
  const suppliers = useSuppliers(storeId);
  const orders = usePurchaseOrders(storeId);
  const auditTrail = usePurchasingAudit(storeId);
  const forecast = useReorderForecast(storeId);
  const products = useProducts(storeId, {
    q: "",
    categoryId: null,
    includeInactive: false,
    limit: 300,
    offset: 0,
  });
  const actions = usePurchasingActions(storeId);

  const supplierForm = useForm<SupplierFields>({
    defaultValues: { name: "", phone: "", gstin: "", rating: "4" },
  });

  // The API gates every write behind the manager role; hiding the page for a
  // cashier only saves them a refusal they could not have acted on.
  if (!manager) {
    return (
      <>
        <PageHeader title="Purchasing" />
        <Card>
          <EmptyState
            icon={<ShieldCheck className="size-5" aria-hidden />}
            title="Purchasing needs the manager role"
            hint={`You are signed in as ${session.user?.role ?? "a cashier"}. Buying stock commits money, so the API refuses these writes for a cashier whether or not this page is on screen.`}
          />
        </Card>
      </>
    );
  }

  const openOrders = (orders.data ?? []).filter((order) => order.status === "ordered");

  return (
    <>
      <PageHeader
        title="Purchasing"
        subtitle={
          tracksExpiry
            ? `Receiving an order raises stock in ${store.store_name} and creates a batch per line, because this vertical tracks expiry.`
            : `Receiving an order raises stock in ${store.store_name}.`
        }
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <StatTile
          label="Unpaid orders"
          value={count(pending.data?.orders ?? 0)}
          tone={pending.data?.orders ? "warning" : "neutral"}
          icon={<Truck className="size-4" aria-hidden />}
        />
        <StatTile
          label="Owed to suppliers"
          value={money(pending.data?.amount ?? 0)}
          icon={<IndianRupee className="size-4" aria-hidden />}
        />
        <StatTile
          label="Open orders"
          value={count(openOrders.length)}
          hint="Ordered, not yet received"
          icon={<PackageCheck className="size-4" aria-hidden />}
        />
      </div>

      <Card className="mt-4">
        <Card.Header>
          <div role="tablist" aria-label="Purchasing view" className="flex flex-wrap gap-1">
            <TabButton selected={tab === "orders"} onSelect={() => setTab("orders")} label="Purchase orders" badge={orders.data?.length} />
            <TabButton selected={tab === "suppliers"} onSelect={() => setTab("suppliers")} label="Suppliers" badge={suppliers.data?.length} />
            <TabButton selected={tab === "audit"} onSelect={() => setTab("audit")} label="Audit trail" badge={auditTrail.data?.length} />
          </div>
        </Card.Header>

        {/* ---- suppliers ---- */}
        {tab === "suppliers" ? (
          suppliers.isPending ? (
            <SkeletonRows rows={5} columns={5} />
          ) : suppliers.isError ? (
            <ErrorState detail={suppliers.error.message} onRetry={() => void suppliers.refetch()} />
          ) : (
            <>
              {(suppliers.data ?? []).length === 0 ? (
                <EmptyState title="No suppliers yet" hint="Add the first one below." />
              ) : (
                <Table caption="Suppliers" minWidth="44rem">
                  <THead>
                    <TH>Name</TH>
                    <TH>Phone</TH>
                    <TH>GSTIN</TH>
                    <TH align="right">Rating</TH>
                    <TH align="right">Orders</TH>
                    <TH align="right">Total ordered</TH>
                  </THead>
                  <TBody>
                    {(suppliers.data ?? []).map((supplier) => (
                      <TR key={supplier.id}>
                        <TRowHeader>{supplier.name}</TRowHeader>
                        <TD numeric className="font-mono text-xs text-ink-2">
                          {supplier.phone ?? "—"}
                        </TD>
                        <TD className="font-mono text-xs text-ink-2">{supplier.gstin ?? "—"}</TD>
                        <TD align="right" numeric>
                          {supplier.rating ?? "—"}
                        </TD>
                        <TD align="right" numeric>
                          {count(supplier.orders)}
                        </TD>
                        <TD align="right" numeric className="font-medium">
                          {money(supplier.total_ordered)}
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}

              <Card.Body className="border-t border-line">
                <form
                  className="grid gap-3 sm:grid-cols-5 sm:items-end"
                  onSubmit={supplierForm.handleSubmit((fields) => {
                    setSupplierError(null);
                    actions.addSupplier.mutate(
                      {
                        name: fields.name.trim(),
                        phone: fields.phone.trim() || null,
                        gstin: fields.gstin.trim() || null,
                        rating: fields.rating ? Number(fields.rating) : null,
                      },
                      {
                        onSuccess: (created) => {
                          supplierForm.reset();
                          toast.success(`${created.name} added.`);
                        },
                        onError: (error) => setSupplierError(error.message),
                      },
                    );
                  })}
                >
                  <TextField label="Name" required {...supplierForm.register("name")} />
                  <TextField label="Phone" {...supplierForm.register("phone")} />
                  <TextField label="GSTIN" {...supplierForm.register("gstin")} />
                  <TextField
                    label="Rating"
                    type="number"
                    min={0}
                    max={5}
                    step="0.5"
                    {...supplierForm.register("rating")}
                  />
                  <Button type="submit" variant="primary" busy={actions.addSupplier.isPending}>
                    Add supplier
                  </Button>
                </form>
                {supplierError ? (
                  <div className="mt-3">
                    <Notice tone="danger">{supplierError}</Notice>
                  </div>
                ) : null}
              </Card.Body>
            </>
          )
        ) : null}

        {/* ---- purchase orders ---- */}
        {tab === "orders" ? (
          orders.isPending ? (
            <SkeletonRows rows={5} columns={6} />
          ) : orders.isError ? (
            <ErrorState detail={orders.error.message} onRetry={() => void orders.refetch()} />
          ) : (
            <>
              {(orders.data ?? []).length === 0 ? (
                <EmptyState
                  title="No purchase orders yet"
                  hint="Raise one below — quantities pre-fill from the reorder forecast."
                />
              ) : (
                <Table caption="Purchase orders" minWidth="52rem">
                  <THead>
                    <TH>Order</TH>
                    <TH>Supplier</TH>
                    <TH>Status</TH>
                    <TH align="right">Lines</TH>
                    <TH align="right">Total</TH>
                    <TH>Ordered</TH>
                    <TH align="right">Actions</TH>
                  </THead>
                  <TBody>
                    {(orders.data ?? []).map((order) => (
                      <TR key={order.id}>
                        <TRowHeader>#{order.id}</TRowHeader>
                        <TD>{order.supplier_name ?? `Supplier ${order.supplier_id}`}</TD>
                        <TD>
                          <span className="flex flex-wrap items-center gap-1.5">
                            <StatusBadge status={order.status} />
                            {order.is_paid ? (
                              <Badge tone="success">Paid</Badge>
                            ) : (
                              <Badge tone="warning">Unpaid</Badge>
                            )}
                          </span>
                        </TD>
                        <TD align="right" numeric>
                          {count(order.lines)}
                        </TD>
                        <TD align="right" numeric className="font-medium">
                          {money(order.total)}
                        </TD>
                        <TD className="text-ink-2">{formatDate(order.ordered_at)}</TD>
                        <TD align="right">
                          <span className="flex justify-end gap-1.5">
                            {order.status === "ordered" ? (
                              <Button
                                size="sm"
                                variant="secondary"
                                onClick={() => setConfirmReceive(order.id)}
                              >
                                Receive
                              </Button>
                            ) : null}
                            {order.is_paid ? null : (
                              <Button
                                size="sm"
                                variant="ghost"
                                busy={
                                  actions.markPaid.isPending &&
                                  actions.markPaid.variables === order.id
                                }
                                onClick={() =>
                                  actions.markPaid.mutate(order.id, {
                                    onSuccess: () => toast.success(`Order #${order.id} marked paid.`),
                                    onError: (error) => toast.error(error.message),
                                  })
                                }
                              >
                                Mark paid
                              </Button>
                            )}
                          </span>
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}

              <Card.Body className="border-t border-line">
                {/* h2, not h3: the only heading above this on the page is the
                    h1 in the page header, and a screen reader's heading list
                    should not have a gap in it. */}
                <h2 className="mb-3 font-display text-sm font-semibold text-ink">
                  Raise an order
                </h2>
                {products.isPending ? (
                  <SkeletonRows rows={3} columns={3} />
                ) : (
                  <OrderBuilder
                    suppliers={suppliers.data ?? []}
                    products={products.data?.items ?? []}
                    forecast={forecast.data ?? []}
                    tracksExpiry={tracksExpiry}
                    unitLabel={store.unit_labels.default}
                    busy={actions.createOrder.isPending}
                    error={orderError}
                    onSubmit={(body) => {
                      setOrderError(null);
                      actions.createOrder.mutate(body, {
                        onSuccess: (order) =>
                          toast.success(
                            `Order #${order.id} raised for ${money(order.total)}.`,
                          ),
                        onError: (error) => setOrderError(error.message),
                      });
                    }}
                  />
                )}
              </Card.Body>
            </>
          )
        ) : null}

        {/* ---- audit ---- */}
        {tab === "audit" ? (
          auditTrail.isPending ? (
            <SkeletonRows rows={8} columns={5} />
          ) : auditTrail.isError ? (
            <ErrorState detail={auditTrail.error.message} onRetry={() => void auditTrail.refetch()} />
          ) : (auditTrail.data ?? []).length === 0 ? (
            <EmptyState title="Nothing has been changed yet" hint="Every mutating request leaves a row here." />
          ) : (
            <>
              <Table caption="Audit trail" minWidth="56rem">
                <THead>
                  <TH>When</TH>
                  <TH>Action</TH>
                  <TH>Entity</TH>
                  <TH align="right">User</TH>
                  <TH>Before</TH>
                  <TH>After</TH>
                </THead>
                <TBody>
                  {(auditTrail.data ?? []).map((entry) => (
                    <TR key={entry.id}>
                      <TRowHeader className="whitespace-nowrap">
                        {formatDateTime(entry.created_at)}
                      </TRowHeader>
                      <TD className="font-mono text-xs">{entry.action}</TD>
                      <TD className="text-ink-2">
                        {entry.entity ?? "—"}
                        {entry.entity_id ? ` #${entry.entity_id}` : ""}
                      </TD>
                      <TD align="right" numeric className="text-ink-2">
                        {entry.user_id ?? "—"}
                      </TD>
                      <TD>
                        <Json value={entry.before} />
                      </TD>
                      <TD>
                        <Json value={entry.after} />
                      </TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
              <Card.Footer>
                <p className="text-xs text-ink-3">
                  Every mutating request leaves a row. Price changes, user edits and stock receipts
                  also record what the values were before and after.
                </p>
              </Card.Footer>
            </>
          )
        ) : null}
      </Card>

      <ConfirmDialog
        open={confirmReceive !== null}
        title={`Receive order #${confirmReceive ?? ""}?`}
        description={
          tracksExpiry
            ? "Stock goes up by each line's quantity and a batch is created per line, using the expiry date and batch number on the order. This cannot be undone from here."
            : "Stock goes up by each line's quantity. This cannot be undone from here."
        }
        confirmLabel="Receive stock"
        busy={actions.receive.isPending}
        onCancel={() => setConfirmReceive(null)}
        onConfirm={() => {
          const orderId = confirmReceive;
          if (orderId === null) return;
          actions.receive.mutate(orderId, {
            onSuccess: (result) => {
              setConfirmReceive(null);
              toast.success(
                `Received ${count(result.lines_received)} line${result.lines_received === 1 ? "" : "s"}` +
                  (result.batches_created
                    ? `, ${count(result.batches_created)} batch${result.batches_created === 1 ? "" : "es"} created.`
                    : "."),
              );
            },
            onError: (error) => {
              setConfirmReceive(null);
              toast.error(error.message);
            },
          });
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

/** Audit before/after values are arbitrary JSON; show them without pretending
 *  to know their shape, and keep a long one from blowing out the row. */
function Json({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-ink-3">—</span>;
  const text = typeof value === "string" ? value : JSON.stringify(value);
  if (text === "null" || text === "{}") return <span className="text-ink-3">—</span>;
  return (
    <span
      title={text}
      className="block max-w-56 truncate font-mono text-[11px] text-ink-2"
    >
      {text}
    </span>
  );
}
