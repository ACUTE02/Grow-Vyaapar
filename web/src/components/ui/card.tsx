import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/**
 * Compound card: Card / Card.Header / Card.Body / Card.Footer.
 *
 * Composed with children rather than `title`/`action`/`footer` props, so a
 * header can hold anything - a filter row, a segmented control, a count - with
 * no new prop each time.
 */
export function Card({
  children,
  className,
  as: Element = "section",
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
}) {
  return (
    <Element
      className={cn(
        "rounded-card border border-line bg-surface shadow-card overflow-hidden",
        className,
      )}
    >
      {children}
    </Element>
  );
}

function Header({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3",
        className,
      )}
    >
      {children}
    </header>
  );
}

function Title({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="min-w-0">
      <h2 className="font-display text-[15px] font-semibold tracking-tight text-ink">
        {children}
      </h2>
      {hint === undefined ? null : (
        <p className="mt-0.5 text-xs text-ink-3">{hint}</p>
      )}
    </div>
  );
}

function Body({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("p-4", className)}>{children}</div>;
}

function Footer({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <footer
      className={cn(
        "flex flex-wrap items-center justify-between gap-3 border-t border-line bg-surface-2/60 px-4 py-3",
        className,
      )}
    >
      {children}
    </footer>
  );
}

Card.Header = Header;
Card.Title = Title;
Card.Body = Body;
Card.Footer = Footer;
