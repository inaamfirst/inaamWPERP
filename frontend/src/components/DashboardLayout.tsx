"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BarChart3,
  Building2,
  Calculator,
  CircleDollarSign,
  ClipboardList,
  Gauge,
  Headphones,
  History,
  House,
  LogOut,
  Menu,
  Package,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  ShoppingBag,
  ShoppingCart,
  Store,
  Truck,
  UserRoundCog,
  Users,
  Warehouse,
  X,
  type LucideIcon,
} from "lucide-react";
import { LoadingState } from "@/components/ui/Feedback";
import { useAuth } from "@/contexts/AuthContext";
import {
  WORKSPACE_GROUPS,
  getPolicyForPath,
  getWorkspacePolicies,
  isPolicyActive,
  workspaceForRole,
  type IconName,
} from "@/lib/access-policy";
import { getWorkspaceRole } from "@/lib/permissions";
import styles from "./DashboardLayout.module.css";

const ICONS: Record<IconName, LucideIcon> = {
  home: House,
  orders: ShoppingBag,
  products: Package,
  customers: Users,
  inventory: Warehouse,
  delivery: Truck,
  vendors: Building2,
  marketplace: Store,
  accounting: Calculator,
  woocommerce: ShoppingCart,
  support: Headphones,
  identity: UserRoundCog,
  settings: Settings,
  system: Gauge,
  pos: ClipboardList,
  ledger: CircleDollarSign,
  reports: BarChart3,
  history: History,
  profile: UserRoundCog,
};

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, company, logout, isLoading, permissions } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [railExpanded, setRailExpanded] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isLoading && !user) router.replace("/login");
    if (!isLoading && user?.must_change_password) router.replace("/change-password");
  }, [isLoading, router, user]);

  useEffect(() => {
    if (!drawerOpen) return;
    const menuButton = menuButtonRef.current;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const focusableSelector = "a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex='-1'])";
    const focusable = drawerRef.current?.querySelectorAll<HTMLElement>(focusableSelector);
    focusable?.[0]?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDrawerOpen(false);
        return;
      }
      if (event.key !== "Tab" || !focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      menuButton?.focus();
    };
  }, [drawerOpen]);

  const workspaceRole = getWorkspaceRole(user);
  const workspace = workspaceForRole(workspaceRole);
  const policies = useMemo(
    () => getWorkspacePolicies(workspace, permissions),
    [permissions, workspace],
  );
  const activePolicy = getPolicyForPath(pathname);
  const primaryPolicies = policies.filter((policy) => policy.primary).slice(0, 4);
  const groups = WORKSPACE_GROUPS[workspace];
  const pageTitle = activePolicy?.title ?? "Workspace";
  const workspaceLabel = workspace === "admin" ? "Operations" : workspace === "vendor" ? "Vendor" : "Rider";

  if (isLoading || !user) return <LoadingState label="Loading your workspace" />;

  const handleLogout = async () => {
    await logout();
    router.replace("/login");
  };

  const groupedNavigation = groups.map((group) => ({
    group,
    items: policies.filter((policy) => policy.group === group),
  })).filter(({ items }) => items.length > 0);

  return (
    <div className={`${styles.layout} ${railExpanded ? styles.railExpanded : ""}`}>
      <button
        className={`${styles.overlay} ${drawerOpen ? styles.overlayVisible : ""}`}
        type="button"
        aria-label="Close navigation"
        tabIndex={drawerOpen ? 0 : -1}
        onClick={() => setDrawerOpen(false)}
      />

      <aside
        className={`${styles.sidebar} ${drawerOpen ? styles.drawerOpen : ""}`}
        aria-label={`${workspaceLabel} workspace navigation`}
        ref={drawerRef}
      >
        <div className={styles.sidebarHeader}>
          <span className={styles.brandMark} aria-hidden="true">{company?.name?.slice(0, 1).toUpperCase() || "E"}</span>
          <span className={styles.brandText}>
            <strong>{company?.name || "Platform ERP"}</strong>
            <small>{workspaceLabel} workspace</small>
          </span>
          <button className={styles.drawerClose} type="button" onClick={() => setDrawerOpen(false)} aria-label="Close navigation"><X aria-hidden="true" /></button>
        </div>

        <nav className={styles.sidebarNav} aria-label="Primary navigation">
          {groupedNavigation.map(({ group, items }) => (
            <div className={styles.navGroup} key={group}>
              <p className={styles.navGroupLabel}>{group}</p>
              {items.map((policy) => {
                const Icon = ICONS[policy.icon];
                const active = isPolicyActive(policy, pathname);
                return (
                  <Link
                    className={`${styles.navLink} ${active ? styles.navLinkActive : ""}`}
                    href={policy.path}
                    key={policy.id}
                    aria-current={active ? "page" : undefined}
                    title={!railExpanded ? policy.title : undefined}
                    onClick={() => setDrawerOpen(false)}
                  >
                    <Icon aria-hidden="true" />
                    <span className={styles.navLabel}>{policy.title}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <div className={styles.sidebarFooter}>
          <Link href="/change-password" className={styles.accountLink} title="Profile and password">
            <UserRoundCog aria-hidden="true" />
            <span className={styles.navLabel}><strong>{user.username}</strong><small>Profile & password</small></span>
          </Link>
          <button className={styles.logoutButton} type="button" onClick={handleLogout} title="Sign out">
            <LogOut aria-hidden="true" />
            <span className={styles.navLabel}>Sign out</span>
          </button>
        </div>
      </aside>

      <div className={styles.mainColumn}>
        <header className={styles.topbar}>
          <button
            className={styles.menuButton}
            type="button"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open navigation"
            aria-expanded={drawerOpen}
            ref={menuButtonRef}
          ><Menu aria-hidden="true" /></button>
          <button
            className={styles.railButton}
            type="button"
            onClick={() => setRailExpanded((current) => !current)}
            aria-label={railExpanded ? "Collapse navigation rail" : "Expand navigation rail"}
            aria-expanded={railExpanded}
          >{railExpanded ? <PanelLeftClose aria-hidden="true" /> : <PanelLeftOpen aria-hidden="true" />}</button>
          <div className={styles.topbarTitle}>
            <small>{company?.name || "Platform ERP"}</small>
            <strong>{pageTitle}</strong>
          </div>
          <div className={styles.topbarActions}>
            <span className={styles.userChip}>{user.username}</span>
            <button type="button" className={styles.topbarLogout} onClick={handleLogout}><LogOut aria-hidden="true" /><span>Sign out</span></button>
          </div>
        </header>

        <main className={styles.content} id="main-content" tabIndex={-1}>{children}</main>

        <nav className={styles.bottomNav} aria-label="Mobile primary navigation">
          {primaryPolicies.map((policy) => {
            const Icon = ICONS[policy.icon];
            const active = isPolicyActive(policy, pathname);
            return (
              <Link className={`${styles.bottomNavItem} ${active ? styles.bottomNavActive : ""}`} href={policy.path} key={policy.id} aria-current={active ? "page" : undefined}>
                <Icon aria-hidden="true" />
                <span>{policy.shortTitle || policy.title}</span>
              </Link>
            );
          })}
          <button className={`${styles.bottomNavItem} ${drawerOpen ? styles.bottomNavActive : ""}`} type="button" onClick={() => setDrawerOpen(true)} aria-label="Open more navigation options" aria-expanded={drawerOpen}>
            <Menu aria-hidden="true" />
            <span>More</span>
          </button>
        </nav>
      </div>
    </div>
  );
}
