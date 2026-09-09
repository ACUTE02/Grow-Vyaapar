"use client";

import { createContext, use, type ReactNode } from "react";
import type { StoreContext as StoreContextPayload } from "./types";

/**
 * The resolved store context for the store in the URL.
 *
 * The store id lives in the path (/s/3/customers), not in a global variable or
 * localStorage. That is what makes cross-store leakage structurally impossible
 * here: switching stores is a navigation, every query key is prefixed with the
 * id, and a stale cache entry from another store is simply a different key.
 */
const ActiveStoreContext = createContext<StoreContextPayload | null>(null);

export function ActiveStoreProvider({
  value,
  children,
}: {
  value: StoreContextPayload;
  children: ReactNode;
}) {
  return <ActiveStoreContext value={value}>{children}</ActiveStoreContext>;
}

export function useActiveStore(): StoreContextPayload {
  const context = use(ActiveStoreContext);
  if (context === null) {
    throw new Error("useActiveStore must be used inside a /s/[storeId] route");
  }
  return context;
}

/** The store's own word for a unit - "kg" in a kirana, "piece" in a boutique.
 *  Read from configuration, never hard-coded per vertical. */
export function useUnitLabel(): string {
  return useActiveStore().unit_labels.default;
}

/** Feature flags come from the vertical row, so a page can hide what this kind
 *  of shop does not do (a kirana has no jobs board, a boutique has no expiry). */
export function useFeature(name: string): boolean {
  return Boolean(useActiveStore().feature_flags[name]);
}
