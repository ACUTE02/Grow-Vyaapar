"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { count } from "@/lib/format";
import { cn } from "@/lib/cn";

export const PAGE_SIZES = [25, 50, 100, 200] as const;

/**
 * Page numbers to render, with `null` standing in for an ellipsis.
 *
 * Pure and exported so it can be unit tested without a DOM - the boundary cases
 * (fewer than eight pages, first page, last page) are exactly where a
 * paginator usually goes wrong.
 */
export function pageNumbers(current: number, last: number, window = 2): (number | null)[] {
  if (last <= 7) return Array.from({ length: last }, (_, index) => index + 1);

  const pages: (number | null)[] = [1];
  const low = Math.max(2, current - window);
  const high = Math.min(last - 1, current + window);

  if (low > 2) pages.push(null);
  for (let page = low; page <= high; page += 1) pages.push(page);
  if (high < last - 1) pages.push(null);
  pages.push(last);

  return pages;
}

export function Pagination({
  page,
  pageSize,
  total,
  totalPages,
  returned,
  hasNext,
  noun = "rows",
  onPageChange,
  onPageSizeChange,
}: {
  page: number;
  pageSize: number;
  /** null when the endpoint runs no count query; the UI degrades gracefully. */
  total: number | null;
  totalPages: number | null;
  returned: number;
  hasNext: boolean;
  noun?: string;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
}) {
  const first = (page - 1) * pageSize + 1;
  const lastOnPage = (page - 1) * pageSize + returned;
  const last = totalPages ?? (hasNext ? page + 1 : page);

  if (total === 0) return null;

  return (
    <nav
      aria-label={`${noun} pagination`}
      className="flex flex-wrap items-center justify-between gap-3"
    >
      <p className="tnum text-xs text-ink-2" aria-live="polite">
        {total === null
          ? `Showing ${count(first)}–${count(lastOnPage)} ${noun}`
          : `Showing ${count(first)}–${count(Math.min(lastOnPage, total))} of ${count(total)} ${noun}`}
      </p>

      {/* Both rows wrap. Only the outer nav did, so on a 375px screen the page
          buttons ran off the right edge - and because nothing scrolls
          sideways, "Next" was not merely awkward to reach, it was unreachable.
          A phone is the likeliest screen a shopkeeper has. */}
      <div className="flex flex-wrap items-center justify-end gap-3">
        {onPageSizeChange ? (
          <label className="flex items-center gap-1.5 text-xs text-ink-2">
            <span className="hidden sm:inline">Per page</span>
            <select
              value={pageSize}
              onChange={(event) => onPageSizeChange(Number(event.currentTarget.value))}
              className="h-8 rounded-lg border border-line bg-surface px-2 text-xs text-ink hover:border-line-strong"
            >
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        <div className="flex flex-wrap items-center justify-end gap-1">
          <PageButton
            label="Previous page"
            disabled={page <= 1}
            onClick={() => onPageChange(page - 1)}
          >
            <ChevronLeft className="size-4" aria-hidden />
            <span className="hidden sm:inline">Previous</span>
          </PageButton>

          {pageNumbers(page, Math.max(1, last)).map((number, index) =>
            number === null ? (
              <span
                key={`gap-${index}`}
                aria-hidden
                className="px-1 text-xs text-ink-3 select-none"
              >
                …
              </span>
            ) : (
              <button
                key={number}
                type="button"
                onClick={() => onPageChange(number)}
                aria-label={`Page ${number}`}
                aria-current={number === page ? "page" : undefined}
                className={cn(
                  "tnum h-8 min-w-8 rounded-lg border px-2 text-xs font-medium transition-colors",
                  number === page
                    ? "border-primary bg-primary text-primary-ink"
                    : "border-line bg-surface text-ink-2 hover:border-line-strong hover:text-ink",
                )}
              >
                {number}
              </button>
            ),
          )}

          <PageButton
            label="Next page"
            disabled={!hasNext}
            onClick={() => onPageChange(page + 1)}
          >
            <span className="hidden sm:inline">Next</span>
            <ChevronRight className="size-4" aria-hidden />
          </PageButton>
        </div>
      </div>
    </nav>
  );
}

function PageButton({
  children,
  label,
  disabled,
  onClick,
}: {
  children: React.ReactNode;
  label: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className={cn(
        "inline-flex h-8 items-center gap-1 rounded-lg border border-line bg-surface px-2 text-xs font-medium text-ink-2",
        "transition-colors hover:border-line-strong hover:text-ink",
        "disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-line",
      )}
    >
      {children}
    </button>
  );
}
