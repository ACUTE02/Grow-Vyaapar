/**
 * The one place this app talks to FastAPI.
 *
 * The backend returns list bodies as plain arrays and puts pagination in
 * headers (X-Total-Count, X-Limit, X-Offset, X-Has-More). Changing that to an
 * envelope would have broken every existing caller and test for no functional
 * gain, so the normalisation happens here instead: `getPage` hands the rest of
 * the app the {items, page, pageSize, total, totalPages, hasNext, hasPrevious}
 * shape the UI actually wants.
 */

export const API_BASE = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

const TOKEN_KEY = "localai.token";

export function readToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function writeToken(token: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (token === null) window.localStorage.removeItem(TOKEN_KEY);
    else window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* private mode: the session simply does not survive a reload */
  }
}

/** Thrown for every non-2xx response, carrying enough for the UI to react. */
export class ApiError extends Error {
  readonly status: number;
  readonly requestId?: string;

  constructor(status: number, message: string, requestId?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.requestId = requestId;
  }

  /** A signed-out session: the shell redirects rather than showing an error. */
  get isUnauthenticated() {
    return this.status === 401;
  }

  /** Another store's data, or a role that is not allowed to do this. */
  get isForbidden() {
    return this.status === 403;
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function buildUrl(path: string, query?: Query) {
  const url = new URL(`${API_BASE}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === null || value === undefined || value === "") continue;
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function toError(response: Response) {
  let detail = response.statusText || `Request failed (${response.status})`;
  let requestId: string | undefined;
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") detail = body.detail;
    else if (Array.isArray(body?.detail)) {
      // FastAPI's own validation errors arrive as a list of objects.
      detail = body.detail
        .map((item: { loc?: unknown[]; msg?: string }) =>
          [item.loc?.slice(1).join("."), item.msg].filter(Boolean).join(": "),
        )
        .join("; ");
    }
    if (Array.isArray(body?.errors) && body.errors.length > 0) {
      detail = `${detail}: ${body.errors.join(", ")}`;
    }
    if (typeof body?.request_id === "string") requestId = body.request_id;
  } catch {
    /* a non-JSON error body; the status text will have to do */
  }
  return new ApiError(response.status, detail, requestId);
}

async function request<T>(
  method: string,
  path: string,
  options: {
    query?: Query;
    body?: unknown;
    signal?: AbortSignal;
    /** Extra request headers. Used for Idempotency-Key on checkout. */
    headers?: Record<string, string>;
  } = {},
): Promise<{ data: T; headers: Headers }> {
  const token = readToken();
  const response = await fetch(buildUrl(path, options.query), {
    method,
    signal: options.signal,
    headers: {
      ...(options.body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  if (!response.ok) throw await toError(response);

  if (response.status === 204) return { data: undefined as T, headers: response.headers };
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    return { data: undefined as T, headers: response.headers };
  }
  return { data: (await response.json()) as T, headers: response.headers };
}

export async function apiGet<T>(path: string, query?: Query, signal?: AbortSignal) {
  const { data } = await request<T>("GET", path, { query, signal });
  return data;
}

export async function apiPost<T>(
  path: string,
  query?: Query,
  body?: unknown,
  headers?: Record<string, string>,
) {
  const { data } = await request<T>("POST", path, { query, body, headers });
  return data;
}

export async function apiPatch<T>(path: string, query?: Query, body?: unknown) {
  const { data } = await request<T>("PATCH", path, { query, body });
  return data;
}

export async function apiPut<T>(path: string, query?: Query, body?: unknown) {
  const { data } = await request<T>("PUT", path, { query, body });
  return data;
}

/** Fetch a binary response (an invoice PDF) with the signed-in user's token. */
export async function apiBlob(path: string, query?: Query) {
  const token = readToken();
  const response = await fetch(buildUrl(path, query), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) throw await toError(response);
  return {
    blob: await response.blob(),
    contentType: response.headers.get("content-type") ?? "application/octet-stream",
  };
}

/**
 * Absolute URL for something the API serves.
 *
 * A composed poster is stored as `/static/campaigns/<hash>.jpg` rather than a
 * full URL, so moving the API to another host does not strand every poster
 * already on file. A generated background is still an absolute third-party
 * URL, and passes through untouched.
 */
export function assetUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  return url.startsWith("/") ? `${API_BASE}${url}` : url;
}

export type Page<T> = {
  items: T[];
  page: number;
  pageSize: number;
  /** null for the endpoints that do not run a count query. */
  total: number | null;
  totalPages: number | null;
  hasNext: boolean;
  hasPrevious: boolean;
  offset: number;
};

function headerInt(headers: Headers, name: string): number | null {
  const raw = headers.get(name);
  if (raw === null) return null;
  const value = Number.parseInt(raw, 10);
  return Number.isNaN(value) ? null : value;
}

/**
 * A page of a list endpoint, with the header pagination folded into the body.
 *
 * The offset goes to the server, so a search covers every row in the store and
 * not merely the page already on screen - which is the whole point of doing it
 * this way rather than filtering client-side.
 */
export async function getPage<T>(
  path: string,
  query: Query & { limit: number; offset: number },
  signal?: AbortSignal,
): Promise<Page<T>> {
  const { data, headers } = await request<T[]>("GET", path, { query, signal });
  const limit = headerInt(headers, "X-Limit") ?? query.limit;
  const offset = headerInt(headers, "X-Offset") ?? query.offset;
  const total = headerInt(headers, "X-Total-Count");
  const items = data ?? [];

  return {
    items,
    page: Math.floor(offset / Math.max(1, limit)) + 1,
    pageSize: limit,
    total,
    totalPages: total === null ? null : Math.max(1, Math.ceil(total / Math.max(1, limit))),
    hasNext: headers.get("X-Has-More") === "true",
    hasPrevious: offset > 0,
    offset,
  };
}
