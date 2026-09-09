import type { ReactNode, ThHTMLAttributes, TdHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

/**
 * A real <table>, not a grid of divs: screen readers announce row and column
 * position from the semantics, and that is not worth giving up for styling.
 *
 * The wrapper scrolls horizontally on its own so a wide table never makes the
 * page scroll sideways, and is focusable so a keyboard user can scroll it.
 */
export function Table({
  children,
  caption,
  className,
  minWidth = "46rem",
}: {
  children: ReactNode;
  /** Visually hidden, but it is what a screen reader reads first. */
  caption: string;
  className?: string;
  /** Below this the wrapper scrolls rather than the page. A table inside a
   *  narrow card wants a smaller floor than one filling the width. */
  minWidth?: string;
}) {
  return (
    <div
      tabIndex={0}
      role="region"
      aria-label={caption}
      className="overflow-x-auto focus-visible:outline-2 focus-visible:outline-primary"
    >
      <table
        style={{ minWidth }}
        className={cn("w-full border-collapse text-sm", className)}
      >
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}

export function THead({ children }: { children: ReactNode }) {
  return (
    <thead className="bg-surface-2/70 text-left">
      <tr className="border-b border-line">{children}</tr>
    </thead>
  );
}

export function TH({
  children,
  align = "left",
  className,
  ...rest
}: ThHTMLAttributes<HTMLTableCellElement> & {
  children: ReactNode;
  align?: "left" | "right" | "center";
}) {
  return (
    <th
      scope="col"
      {...rest}
      className={cn(
        "px-4 py-2.5 text-[11px] font-semibold tracking-wider text-ink-2 uppercase whitespace-nowrap",
        align === "right" && "text-right",
        align === "center" && "text-center",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function TBody({ children }: { children: ReactNode }) {
  return <tbody className="divide-y divide-line">{children}</tbody>;
}

export function TR({
  children,
  onClick,
  selected,
  className,
}: {
  children: ReactNode;
  onClick?: () => void;
  selected?: boolean;
  className?: string;
}) {
  // A clickable row is still not a button: the row carries the visual
  // affordance, and every row has a real focusable control inside it, so the
  // keyboard path does not depend on the row itself.
  return (
    <tr
      onClick={onClick}
      className={cn(
        "transition-colors",
        onClick && "cursor-pointer",
        selected ? "bg-primary-soft" : "hover:bg-surface-2/60",
        className,
      )}
    >
      {children}
    </tr>
  );
}

export function TD({
  children,
  align = "left",
  numeric = false,
  className,
  ...rest
}: TdHTMLAttributes<HTMLTableCellElement> & {
  children: ReactNode;
  align?: "left" | "right" | "center";
  /** Tabular figures, so a column of rupees lines up on the decimal point. */
  numeric?: boolean;
}) {
  return (
    <td
      {...rest}
      className={cn(
        "px-4 py-2.5 align-middle text-ink",
        align === "right" && "text-right",
        align === "center" && "text-center",
        numeric && "tnum",
        className,
      )}
    >
      {children}
    </td>
  );
}

/** A row header: the cell that names the row, marked up as such. */
export function TRowHeader({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <th
      scope="row"
      className={cn("px-4 py-2.5 text-left align-middle font-medium text-ink", className)}
    >
      {children}
    </th>
  );
}
