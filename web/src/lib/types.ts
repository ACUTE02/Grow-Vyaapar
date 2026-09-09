/**
 * Zod schemas for everything crossing the API boundary.
 *
 * Money and quantities arrive as JSON numbers from Pydantic Decimals, so every
 * one of them is coerced rather than trusted - a Decimal that serialises as a
 * string would otherwise silently become NaN halfway down a table.
 */
import { z } from "zod";

const decimal = z.coerce.number();
const isoDate = z.string();

export const storeSummary = z.object({
  id: z.number(),
  name: z.string(),
  city: z.string(),
  vertical_code: z.string(),
  vertical_name: z.string(),
});
export type StoreSummary = z.infer<typeof storeSummary>;

export const storeContext = z.object({
  store_id: z.number(),
  store_name: z.string(),
  city: z.string(),
  address: z.string().nullable().optional(),
  language: z.string(),
  gstin: z.string().nullable().optional(),
  google_review_url: z.string().nullable().optional(),
  whatsapp_number: z.string().nullable().optional(),
  vertical_id: z.number(),
  vertical_code: z.string(),
  vertical_name: z.string(),
  config: z.record(z.string(), z.unknown()),
  feature_flags: z.record(z.string(), z.boolean()),
  unit_labels: z.object({ default: z.string() }).catchall(z.unknown()),
  product_schema: z.record(z.string(), z.unknown()),
  prompt_profile: z.record(z.string(), z.unknown()),
});
export type StoreContext = z.infer<typeof storeContext>;

export const user = z.object({
  id: z.number(),
  name: z.string(),
  email: z.string(),
  role: z.enum(["owner", "manager", "cashier"]),
  store_id: z.number().nullable(),
  is_active: z.boolean(),
});
export type User = z.infer<typeof user>;

export const loginResponse = z.object({
  access_token: z.string(),
  token_type: z.string(),
  expires_in_minutes: z.number(),
  user,
});

export const customerListItem = z.object({
  id: z.number(),
  store_id: z.number(),
  name: z.string(),
  phone: z.string(),
  dob: isoDate.nullable().optional(),
  anniversary: isoDate.nullable().optional(),
  family_head_id: z.number().nullable().optional(),
  notes: z.string().nullable().optional(),
  marketing_opt_in: z.boolean(),
  created_at: z.string(),
  segment: z.string().nullable().optional(),
  recency_days: z.number().nullable().optional(),
  total_spend: decimal.nullable().optional(),
  visits: z.number().nullable().optional(),
});
export type CustomerListItem = z.infer<typeof customerListItem>;

export const customer = customerListItem.partial({
  segment: true,
  recency_days: true,
  total_spend: true,
  visits: true,
});
export type Customer = z.infer<typeof customer>;

export const product = z.object({
  id: z.number(),
  store_id: z.number(),
  sku: z.string(),
  name: z.string(),
  category_id: z.number().nullable().optional(),
  category_name: z.string().nullable().optional(),
  hsn_code: z.string().nullable().optional(),
  cost_price: decimal,
  sell_price: decimal,
  gst_rate: decimal,
  attributes: z.record(z.string(), z.unknown()),
  image_url: z.string().nullable().optional(),
  is_active: z.boolean(),
  qty_on_hand: decimal,
  reorder_point: decimal,
  unit_label: z.string(),
});
export type Product = z.infer<typeof product>;

export const category = z.object({
  id: z.number(),
  store_id: z.number(),
  name: z.string(),
  parent_id: z.number().nullable().optional(),
});
export type Category = z.infer<typeof category>;

export const stockRow = z.object({
  product_id: z.number(),
  sku: z.string(),
  name: z.string(),
  qty_on_hand: decimal,
  reorder_point: decimal,
  unit_label: z.string(),
  days_since_sold: z.number().nullable().optional(),
  sell_price: decimal,
});
export type StockRow = z.infer<typeof stockRow>;

export const saleLine = z.object({
  id: z.number(),
  product_id: z.number(),
  sku: z.string().nullable().optional(),
  name: z.string().nullable().optional(),
  qty: decimal,
  unit_price: decimal,
  line_discount: decimal,
  line_total: decimal,
});

export const transaction = z.object({
  id: z.number(),
  store_id: z.number(),
  customer_id: z.number().nullable().optional(),
  customer_name: z.string().nullable().optional(),
  invoice_no: z.string(),
  subtotal: decimal,
  discount: decimal,
  gst_amount: decimal,
  total: decimal,
  payment_mode: z.string(),
  status: z.string(),
  created_at: z.string(),
  unit_label: z.string().default("piece"),
  lines: z.array(saleLine).default([]),
});
export type Transaction = z.infer<typeof transaction>;

export const transactionListItem = z.object({
  id: z.number(),
  invoice_no: z.string(),
  customer_name: z.string().nullable().optional(),
  total: decimal,
  payment_mode: z.string(),
  status: z.string(),
  created_at: z.string(),
  item_count: z.number(),
});
export type TransactionListItem = z.infer<typeof transactionListItem>;

export const REMINDER_STATUSES = ["queued", "failed", "sent", "dismissed"] as const;
export type ReminderStatus = (typeof REMINDER_STATUSES)[number];

export const reminder = z.object({
  id: z.number(),
  customer_id: z.number(),
  customer_name: z.string().nullable().optional(),
  phone: z.string().nullable().optional(),
  kind: z.string(),
  channel: z.string(),
  message: z.string(),
  status: z.string(),
  scheduled_for: z.string().nullable().optional(),
  sent_at: z.string().nullable().optional(),
  provider_response: z.string().nullable().optional(),
  created_at: z.string(),
});
export type Reminder = z.infer<typeof reminder>;

export const deliveryStatus = z.object({
  store_id: z.number(),
  adapter: z.string(),
  daily_cap: z.number(),
  sent_today: z.number(),
  cap_remaining: z.number(),
  rate_limit_per_minute: z.number(),
});
export type DeliveryStatus = z.infer<typeof deliveryStatus>;

export const sendBatchResult = z.object({
  store_id: z.number(),
  adapter: z.string(),
  sent: z.number(),
  failed: z.number(),
  skipped: z.number(),
  cap_remaining: z.number(),
  results: z.array(
    z.object({
      reminder_id: z.number(),
      status: z.string(),
      detail: z.string().nullable().optional(),
    }),
  ),
});

export const suggestion = z.object({
  title: z.string(),
  detail: z.string(),
  figure: z.string().nullable().optional(),
  action: z.string().nullable().optional(),
});

export const insight = z.object({
  store_id: z.number(),
  period: z.string(),
  generated_at: z.string(),
  metrics: z.record(z.string(), z.unknown()),
  suggestions: z.array(suggestion),
  source: z.string(),
});
export type Insight = z.infer<typeof insight>;

export const campaign = z.object({
  id: z.number(),
  store_id: z.number(),
  occasion: z.string(),
  /** The promo printed onto the poster, kept so the history list can show
   *  which past poster carried which deal without opening each image. */
  offer_text: z.string().nullable().optional(),
  prompt: z.string().nullable().optional(),
  caption: z.string().nullable().optional(),
  hashtags: z.array(z.string()).default([]),
  image_url: z.string().nullable().optional(),
  status: z.string(),
  created_at: z.string(),
});
export type Campaign = z.infer<typeof campaign>;

export const analyticsSummary = z.object({
  store_id: z.number(),
  store_name: z.string(),
  vertical_name: z.string(),
  unit_label: z.string(),
  days: z.number(),
  net_total: decimal,
  invoices: z.number(),
  average_bill: decimal,
  series: z.array(
    z.object({
      date: z.string(),
      net: decimal,
      gross: decimal,
      invoices: z.number(),
      unique_customers: z.number(),
      new_customers: z.number(),
    }),
  ),
});
export type AnalyticsSummary = z.infer<typeof analyticsSummary>;

export const topProduct = z.object({
  sku: z.string(),
  name: z.string(),
  category: z.string().nullable().optional(),
  qty: decimal,
  revenue: decimal,
  unit_label: z.string(),
});
export type TopProduct = z.infer<typeof topProduct>;

export const reminderRule = z.object({
  id: z.number(),
  kind: z.string(),
  signal: z.string(),
  template_key: z.string(),
  channel: z.string(),
  enabled: z.boolean(),
});
export type ReminderRule = z.infer<typeof reminderRule>;

export const loyaltyAccount = z.object({
  customer_id: z.number(),
  points_balance: z.number(),
  lifetime_points: z.number(),
  rupees_per_point: decimal,
  point_value: decimal,
  ledger: z
    .array(
      z.object({
        id: z.number(),
        points_delta: z.number(),
        reason: z.string(),
        transaction_id: z.number().nullable().optional(),
        created_at: z.string(),
      }),
    )
    .default([]),
});
export type LoyaltyAccount = z.infer<typeof loyaltyAccount>;

/**
 * Parse a list, dropping nothing silently: if the API shape drifts, the error
 * surfaces in the page's error state rather than as `undefined` in a cell.
 */
export function parseList<T>(schema: z.ZodType<T>, rows: unknown[]): T[] {
  return z.array(schema).parse(rows);
}

export const churnScore = z.object({
  customer_id: z.number(),
  name: z.string(),
  phone: z.string().nullable().optional(),
  probability: z.number(),
  risk_level: z.string(),
  segment: z.string().nullable().optional(),
  recency_days: z.number().nullable().optional(),
  total_spend: decimal.nullable().optional(),
  model_version: z.string().nullable().optional(),
  scored_at: z.string().nullable().optional(),
});
export type ChurnScore = z.infer<typeof churnScore>;

export const stockForecast = z.object({
  product_id: z.number(),
  sku: z.string(),
  name: z.string(),
  qty_on_hand: decimal,
  unit_label: z.string(),
  predicted_daily_velocity: decimal,
  days_to_stockout: decimal.nullable().optional(),
  suggested_reorder_qty: decimal,
  is_dead_stock_risk: z.boolean(),
  reason: z.string(),
  /** "model" when a trained model produced the row, "estimate" otherwise. */
  source: z.string().default("estimate"),
  computed_at: z.string().nullable().optional(),
});
export type StockForecast = z.infer<typeof stockForecast>;

export const modelRun = z.object({
  id: z.number(),
  model_name: z.string(),
  model_version: z.string(),
  trained_at: z.string(),
  rows_trained: z.number(),
  metrics: z.record(z.string(), z.unknown()),
  params: z.record(z.string(), z.unknown()),
});
export type ModelRun = z.infer<typeof modelRun>;

/**
 * Whether a trained regressor is actually behind the reorder numbers.
 *
 * "SQL estimate" on a forecast row has two very different causes - no model
 * exists, or one exists and lost to a no-feature baseline so it is deliberately
 * not served. `explanation` is the backend's own words for which.
 */
export const stockForecastStatus = z.object({
  trained: z.boolean(),
  in_use: z.boolean(),
  explanation: z.string(),
  model_name: z.string().nullish(),
  model_version: z.string().nullish(),
  /** Which estimator won the validation round: ridge, a forest, a booster. */
  estimator: z.string().nullish(),
  trained_at: z.string().nullish(),
  rows_trained: z.number().nullish(),
  mae: z.number().nullish(),
  rmse: z.number().nullish(),
  baseline_mae: z.number().nullish(),
  r2: z.number().nullish(),
  improvement_vs_baseline_pct: z.number().nullish(),
  holdout_rows: z.number().nullish(),
  evaluation: z.string().nullish(),
});
export type StockForecastStatus = z.infer<typeof stockForecastStatus>;

/* -- jobs, expiry and purchasing ------------------------------------------- */

export const JOB_COLUMNS = ["pending", "in_progress", "ready", "delivered"] as const;
export type JobColumn = (typeof JOB_COLUMNS)[number];

export const job = z.object({
  id: z.number(),
  customer_id: z.number(),
  customer_name: z.string().nullable().optional(),
  phone: z.string().nullable().optional(),
  type: z.string(),
  status: z.string(),
  promised_date: isoDate.nullable().optional(),
  ready_at: z.string().nullable().optional(),
  delivered_at: z.string().nullable().optional(),
  is_overdue: z.boolean().default(false),
  /** The API owns the status graph; the board never hard-codes transitions. */
  next_statuses: z.array(z.string()).default([]),
});
export type Job = z.infer<typeof job>;

export const jobsBoard = z.object({
  store_id: z.number(),
  takes_jobs: z.boolean(),
  job_types: z.array(z.string()).default([]),
  counts: z.record(z.string(), z.number()).default({}),
  statuses: z.array(z.string()).default([]),
});
export type JobsBoard = z.infer<typeof jobsBoard>;

export const jobStatusResult = z.object({
  job,
  reminders_queued: z.number().default(0),
});

export const expiringBatch = z.object({
  batch_id: z.number(),
  product_id: z.number(),
  sku: z.string(),
  name: z.string(),
  batch_no: z.string().nullable().optional(),
  expiry_date: isoDate,
  days_left: z.number(),
  qty: decimal,
  unit_label: z.string(),
  value: decimal,
  is_expired: z.boolean(),
});
export type ExpiringBatch = z.infer<typeof expiringBatch>;

export const expiringResponse = z.object({
  store_id: z.number(),
  tracks_expiry: z.boolean(),
  near_expiry_days: z.number().nullable().optional(),
  window_days: z.number().nullable().optional(),
  alert_count: z.number().default(0),
  expired_count: z.number().default(0),
  batches: z.array(expiringBatch).default([]),
});
export type ExpiringResponse = z.infer<typeof expiringResponse>;

export const supplier = z.object({
  id: z.number(),
  name: z.string(),
  phone: z.string().nullable().optional(),
  gstin: z.string().nullable().optional(),
  address: z.string().nullable().optional(),
  rating: decimal.nullable().optional(),
  notes: z.string().nullable().optional(),
  orders: z.number().default(0),
  total_ordered: decimal.default(0),
});
export type Supplier = z.infer<typeof supplier>;

export const purchaseOrder = z.object({
  id: z.number(),
  supplier_id: z.number(),
  supplier_name: z.string().nullable().optional(),
  status: z.string(),
  ordered_at: z.string().nullable().optional(),
  received_at: z.string().nullable().optional(),
  total: decimal,
  is_paid: z.boolean().default(false),
  lines: z.number().default(0),
});
export type PurchaseOrder = z.infer<typeof purchaseOrder>;

export const receiveResult = z.object({
  purchase_order_id: z.number(),
  lines_received: z.number(),
  batches_created: z.number(),
  received_at: z.string(),
});

export const pendingPayments = z.object({
  orders: z.number().default(0),
  amount: decimal.default(0),
});

export const auditEntry = z.object({
  id: z.number(),
  action: z.string(),
  entity: z.string().nullable().optional(),
  // String(48) in the model, not an integer: one column carries the id of
  // whatever entity the row is about, so it is stored as text on purpose.
  entity_id: z.string().nullable().optional(),
  user_id: z.number().nullable().optional(),
  before: z.unknown().nullable().optional(),
  after: z.unknown().nullable().optional(),
  created_at: z.string(),
});
export type AuditEntry = z.infer<typeof auditEntry>;
