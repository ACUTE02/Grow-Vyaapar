/**
 * Indian formatting, in one place.
 *
 * Intl formatters are expensive to construct, so they are built once at module
 * level rather than per render - a table of 200 rows would otherwise create 200
 * of them.
 */

const RUPEES = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
});

const RUPEES_COMPACT = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  notation: "compact",
  maximumFractionDigits: 1,
});

const COUNT = new Intl.NumberFormat("en-IN");

const DAY = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit",
  month: "short",
  year: "numeric",
});

const DAY_SHORT = new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short" });

const DAY_TIME = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

export function money(value: number | string | null | undefined): string {
  const amount = typeof value === "string" ? Number.parseFloat(value) : value;
  if (amount === null || amount === undefined || Number.isNaN(amount)) return "₹0.00";
  return RUPEES.format(amount);
}

/** For chart axes and tiles, where ₹1,24,500 is too wide: ₹1.2L. */
export function moneyCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "₹0";
  return RUPEES_COMPACT.format(value);
}

export function count(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "0";
  return COUNT.format(value);
}

export function quantity(value: number | null | undefined, unit?: string): string {
  const amount = value ?? 0;
  // 2.5 kg keeps its decimal; 3 kg does not gain a spurious ".0".
  const text = Number.isInteger(amount) ? String(amount) : amount.toFixed(2);
  return unit ? `${text} ${unit}` : text;
}

function toDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(value: string | Date | null | undefined): string {
  const date = toDate(value);
  return date ? DAY.format(date) : "—";
}

export function formatDayShort(value: string | Date | null | undefined): string {
  const date = toDate(value);
  return date ? DAY_SHORT.format(date) : "—";
}

export function formatDateTime(value: string | Date | null | undefined): string {
  const date = toDate(value);
  return date ? DAY_TIME.format(date) : "—";
}

/** "3 days ago" for recency columns, where the exact timestamp is noise. */
export function relativeDays(days: number | null | undefined): string {
  if (days === null || days === undefined) return "—";
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  return `${count(days)} days ago`;
}

/** The API's rule, mirrored so the form can refuse before the round trip. */
export function normaliseMobile(input: string): string | null {
  const digits = input.replace(/\D/g, "").slice(-10);
  return digits.length === 10 && "6789".includes(digits[0]) ? digits : null;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0]?.toUpperCase() ?? "").join("") || "?";
}
