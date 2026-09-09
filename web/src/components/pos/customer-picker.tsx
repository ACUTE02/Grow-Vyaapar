"use client";

import { useEffect, useMemo, useState } from "react";
import { Search, UserRound, X } from "lucide-react";
import { useCustomers } from "@/lib/queries";
import { Skeleton } from "@/components/ui/states";
import { cn } from "@/lib/cn";
import { count } from "@/lib/format";
import type { CustomerListItem } from "@/lib/types";

/** How many customers the quick list holds before you have to search. */
const QUICK_LIST = 300;

/**
 * The hybrid picker the brief specifies: a bounded quick list, and a search
 * that goes to the server.
 *
 * The distinction matters and is stated in the UI, because it is exactly what
 * confuses people: the dropdown is the first 300 by name, but typing searches
 * every customer this store has. Customer 4,000 is reachable; the browser just
 * never holds 4,000 rows.
 */
export function CustomerPicker({
  storeId,
  storeName,
  selected,
  onSelect,
}: {
  storeId: number;
  storeName: string;
  selected: CustomerListItem | null;
  onSelect: (customer: CustomerListItem | null) => void;
}) {
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const query = useMemo(
    () => ({ q: debounced, segment: "All", limit: QUICK_LIST, offset: 0 }),
    [debounced],
  );
  const customers = useCustomers(storeId, query);

  const rows = customers.data?.items ?? [];
  const total = customers.data?.total ?? null;

  if (selected !== null) {
    return (
      <div className="flex items-center gap-2.5 rounded-lg border border-primary/30 bg-primary-soft px-3 py-2">
        <UserRound className="size-4 shrink-0 text-primary" aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-ink">{selected.name}</span>
          <span className="tnum block font-mono text-[11px] text-ink-2">{selected.phone}</span>
        </span>
        <button
          type="button"
          onClick={() => onSelect(null)}
          aria-label="Remove customer from this bill"
          className="rounded p-1 text-ink-3 hover:text-danger"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="relative">
        <Search
          className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-3"
          aria-hidden
        />
        <input
          type="search"
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
          placeholder="Find a customer, or leave blank for walk-in"
          aria-label={`Search every customer in ${storeName}`}
          className="h-9 w-full rounded-lg border border-line bg-surface pr-3 pl-9 text-sm text-ink placeholder:text-ink-3 hover:border-line-strong"
        />
      </div>

      <p className="mt-1.5 text-[11px] text-ink-3" aria-live="polite">
        {debounced
          ? total === null
            ? "Searching the whole store…"
            : `${count(total)} match${total === 1 ? "" : "es"} in ${storeName}`
          : `First ${QUICK_LIST} by name. Type to search every customer in this store.`}
      </p>

      <div className="mt-2 max-h-56 overflow-y-auto rounded-lg border border-line">
        {customers.isPending ? (
          <div className="space-y-2 p-2">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </div>
        ) : rows.length === 0 ? (
          <p className="px-3 py-6 text-center text-sm text-ink-3">
            {debounced
              ? `No customer in ${storeName} matches that.`
              : "No customers in this store yet."}
          </p>
        ) : (
          <ul className="divide-y divide-line">
            {rows.map((customer) => (
              <li key={customer.id}>
                <button
                  type="button"
                  onClick={() => onSelect(customer)}
                  className={cn(
                    "flex w-full items-center gap-2 px-3 py-2 text-left transition-colors",
                    "hover:bg-surface-2",
                  )}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-ink">{customer.name}</span>
                    <span className="tnum block font-mono text-[11px] text-ink-3">
                      {customer.phone}
                    </span>
                  </span>
                  {customer.marketing_opt_in ? null : (
                    <span className="text-[10px] text-ink-3">opted out</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
