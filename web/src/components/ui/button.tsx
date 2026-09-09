import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * One button, four named intents.
 *
 * `variant` is a closed union rather than a pile of booleans (isPrimary,
 * isDanger, isGhost) - the composition rules call that out specifically, and it
 * is also the difference between one legible signature and sixteen impossible
 * combinations.
 */
type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-primary text-primary-ink hover:bg-primary-hover border-transparent shadow-xs disabled:bg-ink-3",
  secondary:
    "bg-surface text-ink border-line hover:bg-surface-2 hover:border-line-strong",
  ghost: "bg-transparent text-ink-2 border-transparent hover:bg-surface-2 hover:text-ink",
  danger: "bg-danger text-white border-transparent hover:brightness-110",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-[13px] gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  lg: "h-12 px-6 text-base gap-2",
};

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  /** Shows a spinner and blocks the click, without changing the width. */
  busy?: boolean;
  children?: ReactNode;
};

export function Button({
  variant = "secondary",
  size = "md",
  busy = false,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cn(
        "inline-flex items-center justify-center rounded-lg border font-medium",
        "transition-colors duration-150 select-none",
        "disabled:cursor-not-allowed disabled:opacity-60",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
    >
      {busy ? <Spinner /> : null}
      {children}
    </button>
  );
}

function Spinner() {
  return (
    <span
      aria-hidden
      className="size-3.5 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent"
    />
  );
}

/** A link that looks like a button. A real <a>, because it navigates - an <a>
 *  inside a <button> is invalid, and a button that navigates loses the
 *  middle-click, the context menu and the status bar. */
export function linkButtonClass(variant: Variant = "secondary", size: Size = "md") {
  return cn(
    "inline-flex items-center justify-center rounded-lg border font-medium",
    "transition-colors duration-150 select-none",
    VARIANTS[variant],
    SIZES[size],
  );
}

/** An icon-only button still needs a name for a screen reader, so the label is
 *  required rather than optional - that is enforced by the type, not a lint. */
export function IconButton({
  label,
  children,
  variant = "ghost",
  size = "md",
  className,
  ...rest
}: Omit<ButtonProps, "children"> & { label: string; children: ReactNode }) {
  return (
    <button
      {...rest}
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex items-center justify-center rounded-lg border transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-60",
        VARIANTS[variant],
        size === "sm" ? "size-8" : size === "lg" ? "size-12" : "size-10",
        className,
      )}
    >
      {children}
    </button>
  );
}
