"use client";

import { useEffect, useRef, useState } from "react";
import { Pencil, X } from "lucide-react";
import { Button, IconButton } from "@/components/ui/button";
import { Toggle } from "@/components/ui/field";
import { SegmentBadge } from "@/components/ui/badge";
import { ErrorState, Skeleton, Notice } from "@/components/ui/states";
import { CustomerForm } from "./customer-form";
import { useToast } from "@/components/ui/toast";
import { useCustomer, useLoyalty, useTransactions, useUpdateCustomer } from "@/lib/queries";
import { formatDate, formatDateTime, money, count } from "@/lib/format";

/**
 * The detail panel for one customer: identity, consent, loyalty and bills.
 *
 * A side sheet rather than a route, because the list is the context - a
 * shopkeeper looking someone up wants to glance and go back, not lose their
 * page and their search.
 *
 * Built on <dialog> for the same reason the modal is. It previously said
 * role="dialog" aria-modal="true" on an <aside>, which is a claim rather than
 * a behaviour: Escape did nothing, Tab walked straight out into the page
 * behind, and focus never entered the panel or came back afterwards. The
 * platform gives all four - focus trap, Escape, top layer, inert background -
 * and cannot be subtly wrong about them.
 */
export function CustomerPanel({
  storeId,
  customerId,
  onClose,
}: {
  storeId: number;
  customerId: number | null;
  onClose: () => void;
}) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const customer = useCustomer(storeId, customerId);
  const loyalty = useLoyalty(storeId, customerId);
  const bills = useTransactions(storeId, { customerId, limit: 5, offset: 0 });
  const update = useUpdateCustomer(storeId);
  const ref = useRef<HTMLDialogElement>(null);

  const open = customerId !== null;
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    // showModal is what puts it in the top layer, traps focus and makes the
    // page behind inert. Rendering it open with an attribute would not.
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  const record = customer.data;

  return (
    <dialog
      ref={ref}
      aria-label="Customer details"
      // Escape and a click on the backdrop both mean cancel, and the parent
      // owns the open state, so neither is allowed to close the element
      // behind its back.
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
      className="fixed inset-y-0 right-0 left-auto m-0 h-full max-h-full w-full max-w-md overscroll-contain border-l border-line bg-surface p-0 text-ink shadow-pop backdrop:bg-black/30"
    >
      <div className="flex h-full flex-col overflow-y-auto">
        <header className="sticky top-0 z-10 flex items-start gap-3 border-b border-line bg-surface px-5 py-4">
          <div className="min-w-0 flex-1">
            {customer.isPending ? (
              <>
                <Skeleton className="h-6 w-40" />
                <Skeleton className="mt-2 h-4 w-28" />
              </>
            ) : (
              <>
                <h2 className="font-display truncate text-lg font-semibold text-ink">
                  {record?.name ?? "Customer"}
                </h2>
                <p className="tnum mt-0.5 font-mono text-xs text-ink-2">{record?.phone}</p>
              </>
            )}
          </div>
          {record && !editing ? (
            <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
              <Pencil className="size-3.5" aria-hidden />
              Edit
            </Button>
          ) : null}
          <IconButton label="Close" size="sm" onClick={onClose}>
            <X className="size-4" aria-hidden />
          </IconButton>
        </header>

        <div className="flex-1 space-y-6 px-5 py-5">
          {customer.isError ? (
            <ErrorState
              detail={customer.error.message}
              onRetry={() => void customer.refetch()}
            />
          ) : customer.isPending || record === undefined ? (
            <div className="space-y-3">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
          ) : editing ? (
            <CustomerForm
              customer={record}
              busy={update.isPending}
              serverError={formError}
              submitLabel="Save changes"
              onCancel={() => {
                setEditing(false);
                setFormError(null);
              }}
              onSubmit={(changes) => {
                if (Object.keys(changes).length === 0) {
                  setEditing(false);
                  toast.info("Nothing to update — no field changed.");
                  return;
                }
                setFormError(null);
                update.mutate(
                  { id: record.id, changes },
                  {
                    onSuccess: (saved) => {
                      setEditing(false);
                      toast.success(`${saved.name} updated.`);
                    },
                    onError: (error) => setFormError(error.message),
                  },
                );
              }}
            />
          ) : (
            <>
              <section>
                <h3 className="mb-2 text-[11px] font-semibold tracking-wider text-ink-3 uppercase">
                  Identity
                </h3>
                <dl className="grid grid-cols-2 gap-3 text-sm">
                  <Detail label="Segment">
                    <SegmentBadge segment={record.segment} />
                  </Detail>
                  <Detail label="Customer since">{formatDate(record.created_at)}</Detail>
                  <Detail label="Date of birth">{formatDate(record.dob)}</Detail>
                  <Detail label="Anniversary">{formatDate(record.anniversary)}</Detail>
                </dl>
                {record.notes ? (
                  <p className="mt-3 rounded-lg bg-surface-2 px-3 py-2 text-sm text-ink-2">
                    {record.notes}
                  </p>
                ) : null}
              </section>

              <section>
                <h3 className="mb-2 text-[11px] font-semibold tracking-wider text-ink-3 uppercase">
                  Consent
                </h3>
                <Toggle
                  label="Send marketing messages to this customer"
                  description="An opted-out customer is skipped when messages are drafted, and refused again at send time."
                  checked={record.marketing_opt_in}
                  disabled={update.isPending}
                  onChange={(next) =>
                    update.mutate(
                      { id: record.id, changes: { marketing_opt_in: next } },
                      {
                        onSuccess: () =>
                          toast.success(next ? "Marketing consent given." : "Marketing consent withdrawn."),
                        onError: (error) => toast.error(error.message),
                      },
                    )
                  }
                />
              </section>

              <section>
                <h3 className="mb-2 text-[11px] font-semibold tracking-wider text-ink-3 uppercase">
                  Loyalty
                </h3>
                {loyalty.isPending ? (
                  <Skeleton className="h-16 w-full" />
                ) : loyalty.isError ? (
                  <Notice tone="warning">Loyalty could not be loaded for this customer.</Notice>
                ) : (
                  <>
                    <div className="grid grid-cols-2 gap-3">
                      <Figure label="Points" value={count(loyalty.data.points_balance)} />
                      <Figure label="Lifetime" value={count(loyalty.data.lifetime_points)} />
                    </div>
                    <p className="mt-2 text-xs text-ink-3">
                      One point per {money(loyalty.data.rupees_per_point)} spent, worth{" "}
                      {money(loyalty.data.point_value)} at the counter. The balance is the sum of
                      the ledger, never edited on its own.
                    </p>
                  </>
                )}
              </section>

              <section>
                <h3 className="mb-2 text-[11px] font-semibold tracking-wider text-ink-3 uppercase">
                  Recent bills
                </h3>
                {bills.isPending ? (
                  <Skeleton className="h-20 w-full" />
                ) : bills.data && bills.data.items.length > 0 ? (
                  <ul className="divide-y divide-line rounded-lg border border-line">
                    {bills.data.items.map((bill) => (
                      <li key={bill.id} className="flex items-center gap-3 px-3 py-2">
                        <span className="min-w-0 flex-1">
                          <span className="block font-mono text-xs text-ink">{bill.invoice_no}</span>
                          <span className="block text-[11px] text-ink-3">
                            {formatDateTime(bill.created_at)}
                          </span>
                        </span>
                        <span className="tnum text-sm font-medium text-ink">
                          {money(bill.total)}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-ink-3">
                    This customer has not bought anything yet.
                  </p>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </dialog>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-ink-3">{label}</dt>
      <dd className="mt-0.5 truncate text-ink">{children}</dd>
    </div>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface-2/60 px-3 py-2">
      <p className="text-[11px] text-ink-3">{label}</p>
      <p className="tnum font-display text-lg font-semibold text-ink">{value}</p>
    </div>
  );
}
