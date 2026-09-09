"use client";

import { useRouter, usePathname } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { Check, ChevronsUpDown, Store } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useStores } from "@/lib/queries";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/cn";

/**
 * The active store, made impossible to miss.
 *
 * Switching rewrites the current path with the new store id and drops the old
 * store's cached queries, so no panel can render store A's rows under store
 * B's name for even one frame. The API refuses cross-store access anyway - this
 * is the UI half of the same promise.
 */
export function StoreSwitcher({ storeId }: { storeId: number }) {
  const router = useRouter();
  const pathname = usePathname();
  const client = useQueryClient();
  const session = useSession();
  const stores = useStores();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on an outside click or Escape. One listener, removed on unmount.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const list = stores.data ?? [];
  const active = list.find((store) => store.id === storeId);

  // A user tied to one store has nothing to switch to; show the store as a
  // label rather than a control that cannot do anything.
  const canSwitch = session.user?.store_id === null && list.length > 1;

  function switchTo(nextId: number) {
    setOpen(false);
    if (nextId === storeId) return;
    client.removeQueries({ queryKey: ["store", storeId] });
    router.push(pathname.replace(`/s/${storeId}/`, `/s/${nextId}/`));
  }

  const face = (
    <>
      <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
        <Store className="size-4" aria-hidden />
      </span>
      <span className="min-w-0 text-left">
        <span className="block truncate text-sm font-semibold text-ink">
          {active?.name ?? (stores.isLoading ? "Loading…" : `Store ${storeId}`)}
        </span>
        <span className="block truncate text-[11px] text-ink-3">
          {active ? `${active.city} · ${active.vertical_name}` : " "}
        </span>
      </span>
    </>
  );

  if (!canSwitch) {
    return (
      <div className="flex items-center gap-2.5 rounded-lg border border-line bg-surface px-2.5 py-1.5">
        {face}
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Active store: ${active?.name ?? storeId}. Change store`}
        className={cn(
          "flex w-full items-center gap-2.5 rounded-lg border bg-surface px-2.5 py-1.5 transition-colors",
          open ? "border-accent" : "border-line hover:border-line-strong",
        )}
      >
        {face}
        <ChevronsUpDown className="ml-auto size-4 shrink-0 text-ink-3" aria-hidden />
      </button>

      {open ? (
        <ul
          role="listbox"
          aria-label="Stores"
          className="absolute top-full right-0 left-0 z-40 mt-1.5 min-w-64 overflow-hidden rounded-lg border border-line bg-surface py-1 shadow-pop"
        >
          {list.map((store) => (
            <li key={store.id}>
              <button
                type="button"
                role="option"
                aria-selected={store.id === storeId}
                onClick={() => switchTo(store.id)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-2"
              >
                <Check
                  className={cn(
                    "size-4 shrink-0",
                    store.id === storeId ? "text-primary" : "text-transparent",
                  )}
                  aria-hidden
                />
                <span className="min-w-0">
                  <span className="block truncate text-ink">{store.name}</span>
                  <span className="block truncate text-[11px] text-ink-3">
                    {store.city} · {store.vertical_name}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
