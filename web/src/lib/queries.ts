"use client";

import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { apiGet, apiPatch, apiPost, getPage, type Page } from "./api";
import * as T from "./types";

/**
 * Query keys are built from a single factory so an invalidation can never miss
 * a cache entry through a typo. Every key starts with the store id: switching
 * stores therefore cannot show the previous store's rows, because it is a
 * different key, not the same key with different data.
 */
export const keys = {
  stores: ["stores"] as const,
  context: (storeId: number) => ["store", storeId, "context"] as const,
  customers: (storeId: number, params: unknown) =>
    ["store", storeId, "customers", params] as const,
  customer: (storeId: number, id: number) => ["store", storeId, "customer", id] as const,
  loyalty: (storeId: number, id: number) => ["store", storeId, "loyalty", id] as const,
  products: (storeId: number, params: unknown) =>
    ["store", storeId, "products", params] as const,
  categories: (storeId: number) => ["store", storeId, "categories"] as const,
  lowStock: (storeId: number) => ["store", storeId, "low-stock"] as const,
  deadStock: (storeId: number) => ["store", storeId, "dead-stock"] as const,
  transactions: (storeId: number, params: unknown) =>
    ["store", storeId, "transactions", params] as const,
  reminders: (storeId: number, params: unknown) =>
    ["store", storeId, "reminders", params] as const,
  reminderRules: (storeId: number) => ["store", storeId, "reminder-rules"] as const,
  delivery: (storeId: number) => ["store", storeId, "delivery"] as const,
  insights: (storeId: number) => ["store", storeId, "insights"] as const,
  campaigns: (storeId: number) => ["store", storeId, "campaigns"] as const,
  summary: (storeId: number, days: number) => ["store", storeId, "summary", days] as const,
  topProducts: (storeId: number, days: number) =>
    ["store", storeId, "top-products", days] as const,
  segments: (storeId: number) => ["store", storeId, "segments-summary"] as const,
};

/* -- config ---------------------------------------------------------------- */

export function useStores() {
  return useQuery({
    queryKey: keys.stores,
    queryFn: async () => T.parseList(T.storeSummary, await apiGet<unknown[]>("/config/stores")),
    staleTime: 5 * 60_000,
  });
}

export function useStoreContext(storeId: number) {
  return useQuery({
    queryKey: keys.context(storeId),
    queryFn: async () =>
      T.storeContext.parse(await apiGet<unknown>(`/config/stores/${storeId}/context`)),
    staleTime: 5 * 60_000,
    enabled: Number.isFinite(storeId),
  });
}

/* -- customers ------------------------------------------------------------- */

export type CustomerQuery = {
  q: string;
  segment: string;
  limit: number;
  offset: number;
};

export function useCustomers(storeId: number, params: CustomerQuery) {
  return useQuery<Page<T.CustomerListItem>>({
    queryKey: keys.customers(storeId, params),
    queryFn: async ({ signal }) => {
      const page = await getPage<unknown>(
        "/customers",
        {
          store_id: storeId,
          q: params.q || undefined,
          segment: params.segment === "All" ? undefined : params.segment,
          limit: params.limit,
          offset: params.offset,
        },
        signal,
      );
      return { ...page, items: T.parseList(T.customerListItem, page.items) };
    },
    // The table keeps the previous page on screen while the next one loads,
    // so paging does not flash an empty table between clicks.
    placeholderData: keepPreviousData,
  });
}

export function useCustomer(storeId: number, customerId: number | null) {
  return useQuery({
    queryKey: keys.customer(storeId, customerId ?? 0),
    queryFn: async () =>
      T.customer.parse(await apiGet<unknown>(`/customers/${customerId}`, { store_id: storeId })),
    enabled: customerId !== null,
  });
}

export function useLoyalty(storeId: number, customerId: number | null) {
  return useQuery({
    queryKey: keys.loyalty(storeId, customerId ?? 0),
    queryFn: async () =>
      T.loyaltyAccount.parse(
        await apiGet<unknown>(`/loyalty/customers/${customerId}`, { store_id: storeId }),
      ),
    enabled: customerId !== null,
  });
}

export function useCreateCustomer(storeId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      T.customer.parse(await apiPost<unknown>("/customers", { store_id: storeId }, body)),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["store", storeId, "customers"] });
    },
  });
}

export function useUpdateCustomer(storeId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, changes }: { id: number; changes: Record<string, unknown> }) =>
      T.customer.parse(
        await apiPatch<unknown>(`/customers/${id}`, { store_id: storeId }, changes),
      ),
    onSuccess: (updated) => {
      void client.invalidateQueries({ queryKey: ["store", storeId, "customers"] });
      client.setQueryData(keys.customer(storeId, updated.id), updated);
    },
  });
}

/* -- products -------------------------------------------------------------- */

export type ProductQuery = {
  q: string;
  categoryId: number | null;
  includeInactive: boolean;
  limit: number;
  offset: number;
};

export function useProducts(storeId: number, params: ProductQuery) {
  return useQuery<Page<T.Product>>({
    queryKey: keys.products(storeId, params),
    queryFn: async ({ signal }) => {
      const page = await getPage<unknown>(
        "/products",
        {
          store_id: storeId,
          q: params.q || undefined,
          category_id: params.categoryId ?? undefined,
          include_inactive: params.includeInactive || undefined,
          limit: params.limit,
          offset: params.offset,
        },
        signal,
      );
      return { ...page, items: T.parseList(T.product, page.items) };
    },
    placeholderData: keepPreviousData,
  });
}

export function useCategories(storeId: number) {
  return useQuery({
    queryKey: keys.categories(storeId),
    queryFn: async () =>
      T.parseList(T.category, await apiGet<unknown[]>("/products/categories", { store_id: storeId })),
    staleTime: 5 * 60_000,
  });
}

export function useCreateProduct(storeId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      T.product.parse(await apiPost<unknown>("/products", { store_id: storeId }, body)),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["store", storeId, "products"] });
      void client.invalidateQueries({ queryKey: keys.lowStock(storeId) });
    },
  });
}

export function useUpdateProduct(storeId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, changes }: { id: number; changes: Record<string, unknown> }) =>
      T.product.parse(await apiPatch<unknown>(`/products/${id}`, { store_id: storeId }, changes)),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["store", storeId, "products"] });
      void client.invalidateQueries({ queryKey: keys.lowStock(storeId) });
      void client.invalidateQueries({ queryKey: keys.deadStock(storeId) });
    },
  });
}

/* -- inventory ------------------------------------------------------------- */

export function useLowStock(storeId: number) {
  return useQuery({
    queryKey: keys.lowStock(storeId),
    queryFn: async () =>
      T.parseList(T.stockRow, await apiGet<unknown[]>("/products/low-stock", { store_id: storeId })),
  });
}

/**
 * Correct a count on purpose.
 *
 * Invalidates the whole store afterwards: a corrected shelf changes the low
 * stock list, the dead stock list, the dashboard tiles and the reorder
 * forecast, and enumerating those is how one of them gets forgotten.
 */
export function useAdjustStock(storeId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (params: {
      productId: number;
      quantity_delta: string;
      reason: string;
      note?: string | null;
    }) =>
      T.stockAdjustment.parse(
        await apiPost<unknown>(
          `/products/${params.productId}/adjustments`,
          { store_id: storeId },
          {
            quantity_delta: params.quantity_delta,
            reason: params.reason,
            note: params.note || null,
          },
        ),
      ),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["store", storeId] });
    },
  });
}

export function useDeadStock(storeId: number) {
  return useQuery({
    queryKey: keys.deadStock(storeId),
    queryFn: async () =>
      T.parseList(T.stockRow, await apiGet<unknown[]>("/products/dead-stock", { store_id: storeId })),
  });
}

/* -- billing --------------------------------------------------------------- */

export function useTransactions(
  storeId: number,
  params: { customerId?: number | null; limit: number; offset: number },
) {
  return useQuery<Page<T.TransactionListItem>>({
    queryKey: keys.transactions(storeId, params),
    queryFn: async ({ signal }) => {
      const page = await getPage<unknown>(
        "/billing/transactions",
        {
          store_id: storeId,
          customer_id: params.customerId ?? undefined,
          limit: params.limit,
          offset: params.offset,
        },
        signal,
      );
      return { ...page, items: T.parseList(T.transactionListItem, page.items) };
    },
    placeholderData: keepPreviousData,
  });
}

/**
 * Complete a sale.
 *
 * The caller passes the key alongside the body, because the key belongs to the
 * checkout rather than to the request: every retry of one cart has to carry
 * the same one, or the retry becomes a second bill. The server treats a
 * repeat as a replay and returns the original.
 */
export function useCreateSale(storeId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({
      body,
      idempotencyKey,
    }: {
      body: Record<string, unknown>;
      idempotencyKey: string;
    }) =>
      T.transaction.parse(
        await apiPost<unknown>("/billing/transactions", { store_id: storeId }, body, {
          "Idempotency-Key": idempotencyKey,
        }),
      ),
    onSuccess: () => {
      // A sale moves stock, the customer's history, the day's totals and the
      // agent's queue. Invalidate the whole store rather than enumerate them.
      void client.invalidateQueries({ queryKey: ["store", storeId] });
    },
  });
}

/* -- marketing / outbox ---------------------------------------------------- */

export function useReminders(storeId: number, kind: string) {
  return useQuery({
    queryKey: keys.reminders(storeId, { kind }),
    queryFn: async () =>
      T.parseList(
        T.reminder,
        await apiGet<unknown[]>("/marketing/reminders", {
          store_id: storeId,
          kind: kind === "all" ? undefined : kind,
          limit: 500,
        }),
      ),
  });
}

export function useReminderRules(storeId: number) {
  return useQuery({
    queryKey: keys.reminderRules(storeId),
    queryFn: async () =>
      T.parseList(
        T.reminderRule,
        await apiGet<unknown[]>(`/config/stores/${storeId}/reminder-rules`),
      ),
    staleTime: 5 * 60_000,
  });
}

export function useDeliveryStatus(storeId: number) {
  return useQuery({
    queryKey: keys.delivery(storeId),
    queryFn: async () =>
      T.deliveryStatus.parse(
        await apiGet<unknown>("/marketing/delivery/status", { store_id: storeId }),
      ),
  });
}

/** Retry, send, dismiss and the batch send all invalidate the same list. */
export function useReminderAction(storeId: number) {
  const client = useQueryClient();
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: ["store", storeId, "reminders"] });
    void client.invalidateQueries({ queryKey: keys.delivery(storeId) });
  };

  const retry = useMutation({
    mutationFn: async (id: number) =>
      apiPost<unknown>(`/marketing/reminders/${id}/retry`, { store_id: storeId }),
    onSuccess: invalidate,
  });

  const send = useMutation({
    mutationFn: async (id: number) =>
      apiPost<unknown>(`/marketing/reminders/${id}/send`, { store_id: storeId }),
    onSuccess: invalidate,
  });

  const dismiss = useMutation({
    mutationFn: async (id: number) =>
      apiPost<unknown>(`/marketing/reminders/${id}/dismiss`, { store_id: storeId }),
    onSuccess: invalidate,
  });

  const sendBatch = useMutation({
    mutationFn: async (ids: number[]) =>
      T.sendBatchResult.parse(
        await apiPost<unknown>("/marketing/reminders/send", { store_id: storeId }, {
          reminder_ids: ids,
        }),
      ),
    onSuccess: invalidate,
  });

  const runCheck = useMutation({
    mutationFn: async () =>
      apiPost<{ total: number; created: Record<string, number> }>("/marketing/reminders/run", {
        store_id: storeId,
      }),
    onSuccess: invalidate,
  });

  return { retry, send, dismiss, sendBatch, runCheck };
}

export function useInsights(storeId: number, enabled: boolean) {
  return useQuery({
    queryKey: keys.insights(storeId),
    queryFn: async () =>
      T.insight.parse(await apiGet<unknown>("/marketing/insights", { store_id: storeId })),
    enabled,
    // The insight endpoint can call an LLM; do not re-fire it on every focus.
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

export function useCampaigns(storeId: number) {
  return useQuery({
    queryKey: keys.campaigns(storeId),
    queryFn: async () =>
      T.parseList(T.campaign, await apiGet<unknown[]>("/marketing/campaigns", { store_id: storeId })),
  });
}

export function useCampaignActions(storeId: number) {
  const client = useQueryClient();
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: keys.campaigns(storeId) });
  };

  const create = useMutation({
    mutationFn: async ({
      occasion,
      offer_text,
    }: {
      occasion: string;
      offer_text?: string | null;
    }) =>
      T.campaign.parse(
        await apiPost<unknown>(
          "/marketing/campaigns",
          { store_id: storeId },
          { occasion, offer_text: offer_text || null },
        ),
      ),
    onSuccess: invalidate,
  });

  /** Redraws the same row from its own occasion and offer, so a second attempt
   *  replaces the poster instead of adding a near-duplicate to the history. */
  const regenerate = useMutation({
    mutationFn: async (id: number) =>
      T.campaign.parse(
        await apiPost<unknown>(`/marketing/campaigns/${id}/regenerate`, {
          store_id: storeId,
        }),
      ),
    onSuccess: invalidate,
  });

  const setStatus = useMutation({
    mutationFn: async ({ id, status }: { id: number; status: string }) =>
      T.campaign.parse(
        await apiPatch<unknown>(`/marketing/campaigns/${id}`, { store_id: storeId }, { status }),
      ),
    onSuccess: invalidate,
  });

  return { create, regenerate, setStatus };
}

/** Store identity - address, WhatsApp number, review link. Separate from the
 *  vertical thresholds next door, and it invalidates the resolved context so
 *  the poster picks up a new address without a reload. */
export function useUpdateStoreDetails(storeId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      T.storeContext.parse(
        await apiPatch<unknown>(`/config/stores/${storeId}`, undefined, body),
      ),
    onSuccess: (context) => {
      client.setQueryData(keys.context(storeId), context);
      void client.invalidateQueries({ queryKey: keys.stores });
    },
  });
}

export function useRebuildSegments(storeId: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      apiPost<{ distribution: Record<string, number> }>("/marketing/segments/rebuild", {
        store_id: storeId,
      }),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["store", storeId] });
    },
  });
}

/* -- analytics ------------------------------------------------------------- */

export function useSummary(storeId: number, days: number) {
  return useQuery({
    queryKey: keys.summary(storeId, days),
    queryFn: async () =>
      T.analyticsSummary.parse(
        await apiGet<unknown>("/analytics/summary", { store_id: storeId, days }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function useTopProducts(storeId: number, days: number) {
  return useQuery({
    queryKey: keys.topProducts(storeId, days),
    queryFn: async () =>
      T.parseList(
        T.topProduct,
        await apiGet<unknown[]>("/analytics/top-products", { store_id: storeId, days, limit: 10 }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function useSegmentSummary(storeId: number) {
  return useQuery({
    queryKey: keys.segments(storeId),
    queryFn: async () =>
      (await apiGet<Record<string, number>>("/marketing/segments/summary", {
        store_id: storeId,
      })) ?? {},
  });
}

/* -- the model layer ------------------------------------------------------- */

export function useAtRiskCustomers(storeId: number) {
  return useQuery({
    queryKey: ["store", storeId, "at-risk"],
    queryFn: async () =>
      T.parseList(
        T.churnScore,
        await apiGet<unknown[]>("/ml/churn/at-risk", { store_id: storeId, limit: 10 }),
      ),
    retry: false,
  });
}

export function useLatestChurnRun(storeId: number) {
  return useQuery({
    queryKey: ["store", storeId, "churn-run"],
    queryFn: async () =>
      T.modelRun.parse(await apiGet<unknown>("/ml/churn/latest-run", { store_id: storeId })),
    // A store with no trained model answers 404, which is information, not an
    // error worth retrying.
    retry: false,
  });
}

export function useStockForecastStatus(storeId: number) {
  return useQuery({
    queryKey: ["store", storeId, "forecast-status"],
    queryFn: async () =>
      T.stockForecastStatus.parse(
        await apiGet<unknown>("/ml/stock_forecast/status", { store_id: storeId }),
      ),
  });
}

export function useStockForecast(storeId: number) {
  return useQuery({
    queryKey: ["store", storeId, "forecast"],
    queryFn: async () =>
      T.parseList(
        T.stockForecast,
        await apiGet<unknown[]>("/ml/forecast/stock", {
          store_id: storeId,
          view: "reorder",
          limit: 10,
        }),
      ),
    retry: false,
  });
}

/* -- jobs ------------------------------------------------------------------ */

export function useJobsBoard(storeId: number) {
  return useQuery({
    queryKey: ["store", storeId, "jobs-board"],
    queryFn: async () =>
      T.jobsBoard.parse(await apiGet<unknown>("/jobs/board", { store_id: storeId })),
  });
}

export function useJobs(storeId: number, enabled: boolean) {
  return useQuery({
    queryKey: ["store", storeId, "jobs"],
    queryFn: async () =>
      T.parseList(
        T.job,
        await apiGet<unknown[]>("/jobs", { store_id: storeId, limit: 300 }),
      ),
    // A store whose vertical does not take jobs has no list to fetch.
    enabled,
  });
}

export function useJobActions(storeId: number) {
  const client = useQueryClient();
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: ["store", storeId, "jobs"] });
    void client.invalidateQueries({ queryKey: ["store", storeId, "jobs-board"] });
    // Marking a job ready can queue a pickup reminder.
    void client.invalidateQueries({ queryKey: ["store", storeId, "reminders"] });
  };

  const setStatus = useMutation({
    mutationFn: async ({ id, status }: { id: number; status: string }) =>
      T.jobStatusResult.parse(
        await apiPost<unknown>(`/jobs/${id}/status`, { store_id: storeId }, { status }),
      ),
    onSuccess: invalidate,
  });

  const book = useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      T.job.parse(await apiPost<unknown>("/jobs", { store_id: storeId }, body)),
    onSuccess: invalidate,
  });

  return { setStatus, book };
}

/* -- expiry ---------------------------------------------------------------- */

export function useExpiring(storeId: number, withinDays: number) {
  return useQuery({
    queryKey: ["store", storeId, "expiring", withinDays],
    queryFn: async () =>
      T.expiringResponse.parse(
        await apiGet<unknown>("/products/expiring", {
          store_id: storeId,
          within_days: withinDays,
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

/* -- purchasing ------------------------------------------------------------ */

export function useSuppliers(storeId: number) {
  return useQuery({
    queryKey: ["store", storeId, "suppliers"],
    queryFn: async () =>
      T.parseList(
        T.supplier,
        await apiGet<unknown[]>("/purchasing/suppliers", { store_id: storeId }),
      ),
  });
}

export function usePurchaseOrders(storeId: number) {
  return useQuery({
    queryKey: ["store", storeId, "purchase-orders"],
    queryFn: async () =>
      T.parseList(
        T.purchaseOrder,
        await apiGet<unknown[]>("/purchasing/orders", { store_id: storeId, limit: 100 }),
      ),
  });
}

export function usePendingPayments(storeId: number) {
  return useQuery({
    queryKey: ["store", storeId, "pending-payments"],
    queryFn: async () =>
      T.pendingPayments.parse(
        await apiGet<unknown>("/purchasing/pending-payments", { store_id: storeId }),
      ),
  });
}

export function usePurchasingAudit(storeId: number) {
  return useQuery({
    queryKey: ["store", storeId, "purchasing-audit"],
    queryFn: async () =>
      T.parseList(
        T.auditEntry,
        await apiGet<unknown[]>("/purchasing/audit", { store_id: storeId, limit: 200 }),
      ),
  });
}

export function useReorderForecast(storeId: number) {
  return useQuery({
    queryKey: ["store", storeId, "reorder-forecast"],
    queryFn: async () =>
      T.parseList(
        T.stockForecast,
        await apiGet<unknown[]>("/ml/forecast/stock", {
          store_id: storeId,
          view: "reorder",
          limit: 25,
        }),
      ),
    // No forecast computed yet is information, not an error worth retrying.
    retry: false,
  });
}

export function usePurchasingActions(storeId: number) {
  const client = useQueryClient();
  const invalidate = () => {
    // Receiving raises stock and can create batches, so this reaches well
    // beyond the purchasing tables.
    void client.invalidateQueries({ queryKey: ["store", storeId] });
  };

  const addSupplier = useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      T.supplier.parse(
        await apiPost<unknown>("/purchasing/suppliers", { store_id: storeId }, body),
      ),
    onSuccess: invalidate,
  });

  const createOrder = useMutation({
    mutationFn: async (body: Record<string, unknown>) =>
      T.purchaseOrder.parse(
        await apiPost<unknown>("/purchasing/orders", { store_id: storeId }, body),
      ),
    onSuccess: invalidate,
  });

  const receive = useMutation({
    mutationFn: async (orderId: number) =>
      T.receiveResult.parse(
        await apiPost<unknown>(`/purchasing/orders/${orderId}/receive`, {
          store_id: storeId,
        }),
      ),
    onSuccess: invalidate,
  });

  const markPaid = useMutation({
    mutationFn: async (orderId: number) =>
      T.purchaseOrder.parse(
        await apiPost<unknown>(`/purchasing/orders/${orderId}/pay`, { store_id: storeId }),
      ),
    onSuccess: invalidate,
  });

  return { addSupplier, createOrder, receive, markPaid };
}
