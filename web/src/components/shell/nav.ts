import {
  BarChart3,
  Boxes,
  ClipboardList,
  Hourglass,
  LayoutDashboard,
  Megaphone,
  Package,
  Receipt,
  Send,
  Settings,
  Sparkles,
  Truck,
  Users,
} from "lucide-react";
import type { ComponentType } from "react";

export type NavItem = {
  href: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
  /** Only shown for a role that could actually use the page. */
  managerOnly?: boolean;
  /** Only shown when the store's vertical enables this feature flag. */
  feature?: string;
};

/**
 * The sidebar, in the order the brief asked for. Hrefs are relative to
 * /s/[storeId] and joined by the shell, so a store switch rewrites every one
 * of them without any component knowing the current id.
 */
export const NAV_ITEMS: NavItem[] = [
  { href: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "pos", label: "POS / Billing", icon: Receipt },
  { href: "customers", label: "Customers", icon: Users },
  { href: "products", label: "Products", icon: Package },
  { href: "inventory", label: "Inventory", icon: Boxes },
  // Feature-flagged: the flag comes from the vertical row, and the shell reads
  // it from the same store context every other gate uses.
  { href: "jobs", label: "Jobs", icon: ClipboardList, feature: "jobs" },
  { href: "expiry", label: "Expiry", icon: Hourglass, feature: "expiry" },
  { href: "purchasing", label: "Purchasing", icon: Truck, managerOnly: true },
  { href: "marketing", label: "Marketing", icon: Megaphone },
  { href: "outbox", label: "Outbox", icon: Send },
  { href: "analytics", label: "Analytics", icon: BarChart3 },
  { href: "assistant", label: "AI Assistant", icon: Sparkles },
  { href: "settings", label: "Settings", icon: Settings },
];
