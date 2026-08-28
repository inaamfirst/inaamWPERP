import type { WorkspaceRole } from "./permissions";

export type WorkspaceId = "admin" | "vendor" | "rider";

export type NavigationGroup =
  | "Overview"
  | "Operations"
  | "Commerce"
  | "Finance"
  | "Administration"
  | "Selling"
  | "Catalog"
  | "Help"
  | "Active work"
  | "History"
  | "Account";

export type IconName =
  | "home"
  | "orders"
  | "products"
  | "customers"
  | "inventory"
  | "delivery"
  | "vendors"
  | "marketplace"
  | "accounting"
  | "woocommerce"
  | "support"
  | "identity"
  | "settings"
  | "system"
  | "pos"
  | "ledger"
  | "reports"
  | "history"
  | "profile";

export type AccessPolicy = {
  id: string;
  title: string;
  shortTitle?: string;
  path: string;
  workspace: WorkspaceId;
  group: NavigationGroup;
  icon: IconName;
  anyOf?: readonly string[];
  allOf?: readonly string[];
  primary?: boolean;
  navigation?: boolean;
};

const ADMIN_IDENTITY_PERMISSIONS = [
  "identity.view_users",
  "identity.manage_users",
  "identity.manage_roles",
  "tenancy.view_companies",
  "tenancy.manage_companies",
] as const;

export const ACCESS_POLICIES: readonly AccessPolicy[] = [
  { id: "admin-home", title: "Overview", path: "/admin", workspace: "admin", group: "Overview", icon: "home", anyOf: ["reports.view"], primary: true },
  { id: "admin-product-new", title: "Add product", path: "/admin/products/new", workspace: "admin", group: "Operations", icon: "products", anyOf: ["catalog.manage"], navigation: false },
  { id: "admin-orders", title: "Orders", path: "/admin/orders", workspace: "admin", group: "Operations", icon: "orders", anyOf: ["orders.view"], primary: true },
  { id: "admin-products", title: "Products", path: "/admin/products", workspace: "admin", group: "Operations", icon: "products", anyOf: ["catalog.view"], primary: true },
  { id: "admin-customers", title: "Customers", path: "/admin/customers", workspace: "admin", group: "Operations", icon: "customers", anyOf: ["customers.view"] },
  { id: "admin-inventory", title: "Inventory", path: "/admin/inventory", workspace: "admin", group: "Operations", icon: "inventory", anyOf: ["inventory.view"] },
  { id: "admin-delivery", title: "Delivery dispatch", shortTitle: "Delivery", path: "/admin/delivery", workspace: "admin", group: "Operations", icon: "delivery", anyOf: ["delivery.manage"], primary: true },
  { id: "admin-vendors", title: "Vendors", path: "/admin/vendors", workspace: "admin", group: "Commerce", icon: "vendors", anyOf: ["vendors.view"] },
  { id: "admin-marketplace", title: "Marketplace", path: "/admin/marketplace", workspace: "admin", group: "Commerce", icon: "marketplace", anyOf: ["vendors.view"] },
  { id: "admin-woocommerce", title: "WooCommerce", path: "/admin/woocommerce", workspace: "admin", group: "Commerce", icon: "woocommerce", anyOf: ["woocommerce.view"] },
  { id: "admin-accounting", title: "Accounting", path: "/admin/accounting", workspace: "admin", group: "Finance", icon: "accounting", anyOf: ["accounting.view"] },
  { id: "admin-support", title: "Support contacts", shortTitle: "Support", path: "/admin/support", workspace: "admin", group: "Administration", icon: "support", anyOf: ["settings.manage"] },
  { id: "admin-identity", title: "Users & roles", path: "/admin/identity", workspace: "admin", group: "Administration", icon: "identity", anyOf: ADMIN_IDENTITY_PERMISSIONS },
  { id: "admin-settings", title: "Settings", path: "/admin/settings", workspace: "admin", group: "Administration", icon: "settings", anyOf: ["settings.view"] },
  { id: "admin-system", title: "System diagnostics", shortTitle: "System", path: "/admin/system", workspace: "admin", group: "Administration", icon: "system", anyOf: ["core.view_health"] },

  { id: "vendor-home", title: "Overview", path: "/vendor", workspace: "vendor", group: "Overview", icon: "home", anyOf: ["vendor.profile.view", "vendor.products.view"], primary: true },
  { id: "vendor-pos", title: "Shop POS", shortTitle: "POS", path: "/vendor/pos", workspace: "vendor", group: "Selling", icon: "pos", anyOf: ["vendor.orders.manage"], primary: true },
  { id: "vendor-orders", title: "Online orders", shortTitle: "Orders", path: "/vendor/orders", workspace: "vendor", group: "Selling", icon: "orders", anyOf: ["vendor.orders.view"], primary: true },
  { id: "vendor-products", title: "Products & publishing", shortTitle: "Products", path: "/vendor/products", workspace: "vendor", group: "Catalog", icon: "products", anyOf: ["vendor.products.view"], primary: true },
  { id: "vendor-stock", title: "Stock", path: "/vendor/stock", workspace: "vendor", group: "Catalog", icon: "inventory", anyOf: ["vendor.stock.view"] },
  { id: "vendor-ledger", title: "Ledger", path: "/vendor/ledger", workspace: "vendor", group: "Finance", icon: "ledger", anyOf: ["vendor.ledger.view"] },
  { id: "vendor-reports", title: "Reports", path: "/vendor/reports", workspace: "vendor", group: "Finance", icon: "reports", anyOf: ["vendor.reports.view"] },
  { id: "vendor-support", title: "Support", path: "/vendor/support", workspace: "vendor", group: "Help", icon: "support", anyOf: ["vendor.profile.view"] },

  { id: "rider-home", title: "Overview", path: "/rider", workspace: "rider", group: "Overview", icon: "home", anyOf: ["delivery.view_assigned"], primary: true },
  { id: "rider-assigned", title: "Assigned deliveries", shortTitle: "Assigned", path: "/rider/deliveries", workspace: "rider", group: "Active work", icon: "delivery", anyOf: ["delivery.view_assigned"], primary: true },
  { id: "rider-today", title: "Today’s deliveries", shortTitle: "Today", path: "/rider/today", workspace: "rider", group: "Active work", icon: "orders", anyOf: ["delivery.view_assigned"], primary: true },
  { id: "rider-history", title: "Delivery history", shortTitle: "History", path: "/rider/history", workspace: "rider", group: "History", icon: "history", anyOf: ["delivery.view_assigned"], primary: true },
] as const;

export const WORKSPACE_GROUPS: Record<WorkspaceId, readonly NavigationGroup[]> = {
  admin: ["Overview", "Operations", "Commerce", "Finance", "Administration"],
  vendor: ["Overview", "Selling", "Catalog", "Finance", "Help"],
  rider: ["Overview", "Active work", "History", "Account"],
};

export function workspaceForRole(role: WorkspaceRole): WorkspaceId {
  return role === "vendor" ? "vendor" : role === "rider" ? "rider" : "admin";
}

export function canAccessPolicy(policy: AccessPolicy, granted: readonly string[]): boolean {
  const anyAllowed = !policy.anyOf?.length || policy.anyOf.some((permission) => granted.includes(permission));
  const allAllowed = !policy.allOf?.length || policy.allOf.every((permission) => granted.includes(permission));
  return anyAllowed && allAllowed;
}

export function getWorkspacePolicies(workspace: WorkspaceId, granted: readonly string[]): AccessPolicy[] {
  return ACCESS_POLICIES.filter(
    (policy) => policy.workspace === workspace && policy.navigation !== false && canAccessPolicy(policy, granted),
  );
}

export function getPolicyForPath(pathname: string): AccessPolicy | undefined {
  return [...ACCESS_POLICIES]
    .sort((left, right) => right.path.length - left.path.length)
    .find((policy) => pathname === policy.path || pathname.startsWith(`${policy.path}/`));
}

export function isPolicyActive(policy: AccessPolicy, pathname: string): boolean {
  return pathname === policy.path || pathname.startsWith(`${policy.path}/`);
}

export function getCanonicalHome(role: WorkspaceRole, granted: readonly string[]): string {
  const workspace = workspaceForRole(role);
  return getWorkspacePolicies(workspace, granted)[0]?.path ?? `/${workspace}`;
}
