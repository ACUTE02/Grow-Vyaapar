"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { LogOut, Menu, Store, X } from "lucide-react";
import { NAV_ITEMS } from "./nav";
import { StoreSwitcher } from "./store-switcher";
import { useSession, canManage } from "@/lib/session";
import { useActiveStore } from "@/lib/active-store";
import { initials } from "@/lib/format";
import { cn } from "@/lib/cn";

/**
 * The frame every page sits in: a sidebar that becomes a drawer on a phone, a
 * top bar carrying the active store, and the content column.
 */
export function AppShell({ storeId, children }: { storeId: number; children: ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[16rem_1fr]">
      {/* Backdrop only exists while the drawer is open, on small screens. */}
      {drawerOpen ? (
        <div
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={() => setDrawerOpen(false)}
          aria-hidden
        />
      ) : null}

      <Sidebar
        storeId={storeId}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />

      <div className="flex min-w-0 flex-col">
        <TopBar storeId={storeId} onOpenMenu={() => setDrawerOpen(true)} />
        <main id="main" className="min-w-0 flex-1 px-4 py-5 sm:px-6 sm:py-6">
          {children}
        </main>
      </div>
    </div>
  );
}

function Sidebar({
  storeId,
  open,
  onClose,
}: {
  storeId: number;
  open: boolean;
  onClose: () => void;
}) {
  const pathname = usePathname();
  const session = useSession();
  const store = useActiveStore();
  const manager = canManage(session.user);

  const items = NAV_ITEMS.filter((item) => {
    if (item.managerOnly && !manager) return false;
    if (item.feature && !store.feature_flags[item.feature]) return false;
    return true;
  });

  return (
    <aside
      className={cn(
        "fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-line bg-surface",
        "transition-transform duration-200 lg:static lg:translate-x-0",
        open ? "translate-x-0" : "-translate-x-full",
      )}
      aria-label="Main navigation"
    >
      <div className="flex h-14 items-center gap-2.5 border-b border-line px-4">
        <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-ink">
          <Store className="size-4" aria-hidden />
        </span>
        <span className="font-display text-[15px] font-semibold tracking-tight">Grow Vyaapar</span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close navigation"
          className="ml-auto rounded-lg p-1.5 text-ink-3 hover:bg-surface-2 hover:text-ink lg:hidden"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>

      {/* Closing on the navigation event rather than watching the pathname:
          one handler covers every link, and a keyboard Enter dispatches a
          click too, so nothing needs an effect to notice the route changed. */}
      <nav className="flex-1 overflow-y-auto p-3" onClick={onClose}>
        <ul className="space-y-0.5">
          {items.map((item) => {
            const href = `/s/${storeId}/${item.href}`;
            const active = pathname === href || pathname.startsWith(`${href}/`);
            const Icon = item.icon;
            return (
              <li key={item.href}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                    active
                      ? "bg-primary-soft font-medium text-primary"
                      : "text-ink-2 hover:bg-surface-2 hover:text-ink",
                  )}
                >
                  <Icon className="size-4 shrink-0" />
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="border-t border-line p-3">
        <div className="flex items-center gap-2.5 rounded-lg px-2 py-1.5">
          <span className="grid size-8 shrink-0 place-items-center rounded-full bg-surface-2 text-[11px] font-semibold text-ink-2">
            {initials(session.user?.name ?? "?")}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm text-ink">
              {session.user?.name ?? "Signed out"}
            </span>
            <span className="block truncate text-[11px] text-ink-3 capitalize">
              {session.user?.role ?? ""}
            </span>
          </span>
          <button
            type="button"
            onClick={session.signOut}
            aria-label="Sign out"
            title="Sign out"
            className="rounded-lg p-1.5 text-ink-3 hover:bg-surface-2 hover:text-danger"
          >
            <LogOut className="size-4" aria-hidden />
          </button>
        </div>
      </div>
    </aside>
  );
}

function TopBar({ storeId, onOpenMenu }: { storeId: number; onOpenMenu: () => void }) {
  const store = useActiveStore();

  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-line bg-paper/85 px-4 backdrop-blur sm:px-6">
      <button
        type="button"
        onClick={onOpenMenu}
        aria-label="Open navigation"
        className="rounded-lg p-1.5 text-ink-2 hover:bg-surface-2 lg:hidden"
      >
        <Menu className="size-5" aria-hidden />
      </button>

      <div className="w-full max-w-72">
        <StoreSwitcher storeId={storeId} />
      </div>

      <p className="ml-auto hidden text-xs text-ink-3 md:block">
        Prices, thresholds and reminder rules come from the{" "}
        <span className="text-ink-2">{store.vertical_name}</span> profile.
      </p>
    </header>
  );
}
