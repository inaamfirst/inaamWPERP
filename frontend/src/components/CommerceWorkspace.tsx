"use client";

import Link from "next/link";
import { usePathname, useSearchParams, useRouter } from "next/navigation";
import styles from "./commerce.module.css";

export type Workspace = "combined" | "shop" | "online";

function QuickLinkIcon({ label }: { label: string }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, viewBox: "0 0 24 24", "aria-hidden": true };
  const normalized = label.toLowerCase();
  if (normalized.includes("pos")) return <svg {...common}><rect x="5" y="3" width="14" height="18" rx="2" /><path d="M8 7h8M8 11h.01M12 11h.01M16 11h.01M8 15h.01M12 15h.01M16 15h.01" /></svg>;
  if (normalized.includes("stock") || normalized.includes("inventory")) return <svg {...common}><path d="m4 7 8-4 8 4-8 4-8-4Z" /><path d="M4 12l8 4 8-4M4 17l8 4 8-4" /></svg>;
  if (normalized.includes("ledger") || normalized.includes("account") || normalized.includes("report")) return <svg {...common}><path d="M5 4h14v16H5z" /><path d="M8 8h8M8 12h8M8 16h5" /></svg>;
  if (normalized.includes("order")) return <svg {...common}><path d="M6 3h12v18H6z" /><path d="M9 7h6M9 11h6M9 15h4" /></svg>;
  if (normalized.includes("product") || normalized.includes("catalog")) return <svg {...common}><path d="m4 7 8-4 8 4-8 4-8-4Z" /><path d="M4 12l8 4 8-4M4 17l8 4 8-4" /></svg>;
  if (normalized.includes("delivery")) return <svg {...common}><path d="M3 6h11v10H3zM14 9h4l3 3v4h-7z" /><path d="M7 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4ZM18 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z" /></svg>;
  if (normalized.includes("vendor")) return <svg {...common}><path d="M4 10h16M6 10V7l6-4 6 4v3M6 10v10h12V10M9 20v-5h6v5" /></svg>;
  if (normalized.includes("user") || normalized.includes("role")) return <svg {...common}><circle cx="12" cy="8" r="3" /><path d="M5 20a7 7 0 0 1 14 0" /></svg>;
  if (normalized.includes("support")) return <svg {...common}><path d="M4 5h16v11H8l-4 4z" /><path d="M8 9h8M8 12h5" /></svg>;
  return <svg {...common}><path d="M12 3a9 9 0 1 0 9 9" /><path d="M12 7v5l3 2M16 3h5v5" /></svg>;
}

export function WorkspaceSwitcher({ value }: { value: Workspace }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  function change(next: Workspace) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("workspace", next);
    router.push(`${pathname}?${params.toString()}`);
  }

  return (
    <div className={styles.workspaceBar} aria-label="Workspace selector">
      <span className={styles.workspaceLabel}>View</span>
      {(["combined", "shop", "online"] as Workspace[]).map((item) => (
        <button
          key={item}
          type="button"
          className={`${styles.workspaceButton} ${value === item ? styles.workspaceButtonActive : ""}`}
          onClick={() => change(item)}
        >
          {item === "combined" ? "Combined" : item === "shop" ? "Shop / POS" : "Online Store"}
        </button>
      ))}
    </div>
  );
}

export type QuickLinksMode = "vendor" | "admin" | "staff" | "rider";

type QuickLink = {
  label: string;
  href: string;
  permission?: string;
};

const roleLinks: Record<QuickLinksMode, QuickLink[]> = {
  vendor: [
    { label: "Open POS", href: "/vendor/pos", permission: "vendor.orders.manage" },
    { label: "Manage products", href: "/vendor/products", permission: "vendor.products.view" },
    { label: "Manage stock", href: "/vendor/stock", permission: "vendor.stock.view" },
    { label: "View orders", href: "/vendor/orders", permission: "vendor.orders.view" },
    { label: "View ledger", href: "/vendor/ledger", permission: "vendor.ledger.view" },
    { label: "Purchases & cash", href: "/vendor/shop", permission: "vendor.shop.purchases.manage" },
    { label: "View reports", href: "/vendor/reports", permission: "vendor.reports.view" },
    { label: "Get support", href: "/vendor/support", permission: "vendor.profile.view" },
  ],
  admin: [
    { label: "Manage vendors", href: "/admin/vendors", permission: "vendors.view" },
    { label: "Review orders", href: "/admin/orders", permission: "orders.view" },
    { label: "Manage catalog", href: "/admin/products", permission: "catalog.view" },
    { label: "Manage inventory", href: "/admin/inventory", permission: "inventory.view" },
    { label: "Delivery dispatch", href: "/admin/delivery", permission: "delivery.manage" },
    { label: "Accounting", href: "/admin/accounting", permission: "accounting.view" },
    { label: "Users & roles", href: "/admin/identity", permission: "identity.view_users" },
    { label: "Support directory", href: "/admin/support", permission: "settings.manage" },
  ],
  staff: [
    { label: "Review orders", href: "/admin/orders", permission: "orders.view" },
    { label: "Manage catalog", href: "/admin/products", permission: "catalog.view" },
    { label: "Manage inventory", href: "/admin/inventory", permission: "inventory.view" },
    { label: "Delivery dispatch", href: "/admin/delivery", permission: "delivery.manage" },
    { label: "Reports", href: "/admin", permission: "reports.view" },
    { label: "Support directory", href: "/admin/support", permission: "settings.manage" },
  ],
  rider: [
    { label: "Assigned deliveries", href: "/rider/deliveries", permission: "delivery.view_assigned" },
    { label: "Today's deliveries", href: "/rider/today", permission: "delivery.view_assigned" },
    { label: "Delivery history", href: "/rider/history", permission: "delivery.view_assigned" },
    { label: "Profile & password", href: "/change-password" },
  ],
};

export function QuickLinks({ mode, permissions = [] }: { mode: QuickLinksMode; permissions?: string[] }) {
  const links = roleLinks[mode].filter((link) => !link.permission || permissions.includes(link.permission));
  return (
    <div className={styles.quickLinks}>
      {links.length === 0 ? <div className={styles.empty}>No actions are assigned to this account.</div> : links.map((link) => (
        <Link key={link.href} href={link.href} className={styles.quickLink}>
          <span className={styles.quickLinkIcon}><QuickLinkIcon label={link.label} /></span>
          <span className={styles.quickLinkText}>{link.label}</span>
          <span className={styles.quickLinkArrow} aria-hidden="true">›</span>
        </Link>
      ))}
    </div>
  );
}
