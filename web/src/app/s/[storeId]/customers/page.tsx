"use client";

import { use, useEffect, useMemo, useState } from "react";
import { Plus, Search, UserPlus, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { SegmentBadge } from "@/components/ui/badge";
import { EmptyState, ErrorState, SkeletonRows } from "@/components/ui/states";
import { Table, TBody, TD, TH, THead, TR, TRowHeader } from "@/components/ui/table";
import { Pagination } from "@/components/ui/pagination";
import { Modal } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { CustomerForm } from "@/components/customers/customer-form";
import { CustomerPanel } from "@/components/customers/customer-panel";
import { useCreateCustomer, useCustomers } from "@/lib/queries";
import { useActiveStore } from "@/lib/active-store";
import { money, count, relativeDays } from "@/lib/format";
import { ApiError } from "@/lib/api";

const SEGMENTS = ["All", "New", "Regular", "VIP", "Inactive"] as const;

export default function CustomersPage({ params }: { params: Promise<{ storeId: string }> }) {
  const { storeId: raw } = use(params);
  const storeId = Number(raw);
  const store = useActiveStore();
  const toast = useToast();

  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [segment, setSegment] = useState<string>("All");
  const [pageSize, setPageSize] = useState(50);
  const [page, setPage] = useState(1);
  const [openId, setOpenId] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  // Typing a name should not fire a request per keystroke. 250ms is short
  // enough that the list feels live and long enough to skip the intermediate
  // states of a word.
  //
  // The page reset rides along with each filter change - here when the debounce
  // fires, and in the onChange handlers below - rather than in an effect
  // watching the filters. Without it, a search with three matches made while
  // sitting on page nine comes back empty, which is the classic pagination bug.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(search.trim());
      setPage(1);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const query = useMemo(
    () => ({
      q: debounced,
      segment,
      limit: pageSize,
      offset: (page - 1) * pageSize,
    }),
    [debounced, segment, pageSize, page],
  );

  const customers = useCustomers(storeId, query);
  const create = useCreateCustomer(storeId);

  const data = customers.data;

  return (
    <>
      <PageHeader
        title="Customers"
        subtitle={
          <>
            Customers belong to <span className="text-ink">{store.store_name}</span> alone — one
            added here is not visible under any other store.
          </>
        }
        actions={
          <Button variant="primary" onClick={() => setAdding(true)}>
            <Plus className="size-4" aria-hidden />
            Add customer
          </Button>
        }
      />

      <Card>
        <Card.Header>
          <div className="flex flex-1 flex-wrap items-center gap-2">
            {/* One filter row above the table, as the guidance asks. */}
            <div className="relative min-w-56 flex-1">
              <Search
                className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3"
                aria-hidden
              />
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
                placeholder="Search name or phone across the whole store"
                aria-label="Search customers"
                className="h-9 w-full rounded-lg border border-line bg-surface pr-8 pl-9 text-sm text-ink placeholder:text-ink-3 hover:border-line-strong"
              />
              {search ? (
                <button
                  type="button"
                  onClick={() => setSearch("")}
                  aria-label="Clear search"
                  className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-1 text-ink-3 hover:text-ink"
                >
                  <X className="size-3.5" aria-hidden />
                </button>
              ) : null}
            </div>

            <label className="flex items-center gap-1.5 text-xs text-ink-2">
              <span className="sr-only sm:not-sr-only">Segment</span>
              <select
                value={segment}
                onChange={(event) => {
                  setSegment(event.currentTarget.value);
                  setPage(1);
                }}
                className="h-9 rounded-lg border border-line bg-surface px-2 text-sm text-ink hover:border-line-strong"
              >
                {SEGMENTS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {debounced ? (
            <p className="text-xs text-ink-3" aria-live="polite">
              {data?.total === null || data?.total === undefined
                ? "Searching…"
                : `${count(data.total)} match${data.total === 1 ? "" : "es"} in ${store.store_name}`}
            </p>
          ) : null}
        </Card.Header>

        {customers.isPending ? (
          <SkeletonRows rows={8} columns={6} />
        ) : customers.isError ? (
          <ErrorState
            title="Unable to load customers"
            detail={
              customers.error instanceof ApiError
                ? customers.error.message
                : "The API did not answer."
            }
            onRetry={() => void customers.refetch()}
          />
        ) : data === undefined ? null : data.items.length === 0 ? (
          <EmptyState
            icon={<UserPlus className="size-5" aria-hidden />}
            title={debounced ? "No customer matches that search" : "No customers yet"}
            hint={
              debounced
                ? `Nothing in ${store.store_name} matches “${debounced}”. The search covers every customer in this store, not just this page — so check the store selector if you expected someone added elsewhere.`
                : `The first customer you add to ${store.store_name} will appear here.`
            }
            action={
              debounced ? (
                <Button variant="secondary" onClick={() => setSearch("")}>
                  Clear search
                </Button>
              ) : (
                <Button variant="primary" onClick={() => setAdding(true)}>
                  <Plus className="size-4" aria-hidden />
                  Add customer
                </Button>
              )
            }
          />
        ) : (
          <>
            <Table caption="Customers in this store">
              <THead>
                <TH>Name</TH>
                <TH>Phone</TH>
                <TH>Segment</TH>
                <TH>Last visit</TH>
                <TH align="right">Visits</TH>
                <TH align="right">Lifetime spend</TH>
                <TH>Messages</TH>
              </THead>
              <TBody>
                {data.items.map((customer) => (
                  <TR
                    key={customer.id}
                    onClick={() => setOpenId(customer.id)}
                    selected={openId === customer.id}
                  >
                    <TRowHeader>
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setOpenId(customer.id);
                        }}
                        // -my-1 py-1 keeps the row height while giving the hit area 24px.
                        className="-my-1 py-1 text-left hover:text-primary hover:underline"
                      >
                        {customer.name}
                      </button>
                    </TRowHeader>
                    <TD numeric className="font-mono text-xs text-ink-2">
                      {customer.phone}
                    </TD>
                    <TD>
                      <SegmentBadge segment={customer.segment} />
                    </TD>
                    <TD className="text-ink-2">{relativeDays(customer.recency_days)}</TD>
                    <TD align="right" numeric>
                      {count(customer.visits ?? 0)}
                    </TD>
                    <TD align="right" numeric className="font-medium">
                      {money(customer.total_spend ?? 0)}
                    </TD>
                    <TD>
                      <span
                        className={
                          customer.marketing_opt_in ? "text-success text-xs" : "text-ink-3 text-xs"
                        }
                      >
                        {customer.marketing_opt_in ? "Opted in" : "Opted out"}
                      </span>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>

            <Card.Footer>
              <Pagination
                page={data.page}
                pageSize={data.pageSize}
                total={data.total}
                totalPages={data.totalPages}
                returned={data.items.length}
                hasNext={data.hasNext}
                noun="customers"
                onPageChange={setPage}
                onPageSizeChange={(size) => {
                  // A bigger page means the old offset points somewhere else.
                  setPageSize(size);
                  setPage(1);
                }}
              />
            </Card.Footer>
          </>
        )}
      </Card>

      <Modal
        open={adding}
        onClose={() => {
          setAdding(false);
          setAddError(null);
        }}
        title={`Add a customer to ${store.store_name}`}
        description="They will not be visible under any other store."
      >
        <CustomerForm
          busy={create.isPending}
          serverError={addError}
          submitLabel="Save customer"
          onCancel={() => {
            setAdding(false);
            setAddError(null);
          }}
          onSubmit={(body) => {
            setAddError(null);
            create.mutate(body, {
              onSuccess: (created) => {
                setAdding(false);
                setOpenId(created.id);
                // Point the list at the customer just saved: a stale search,
                // or simply page one of forty, is the usual reason a new
                // customer looks like it was not added.
                setSearch(created.phone);
                toast.success(`${created.name} was added to ${store.store_name}.`);
              },
              onError: (error) => setAddError(error.message),
            });
          }}
        />
      </Modal>

      <CustomerPanel
        storeId={storeId}
        customerId={openId}
        onClose={() => setOpenId(null)}
      />
    </>
  );
}
