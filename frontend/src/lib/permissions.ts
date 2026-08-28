export const VENDOR_SELF_PERMISSIONS = [
  "vendor.profile.view",
  "vendor.products.view",
  "vendor.products.manage",
  "vendor.orders.view",
  "vendor.orders.manage",
  "vendor.settlements.view",
  "vendor.ledger.view",
  "vendor.stock.view",
  "vendor.stock.manage",
  "vendor.reports.view",
];

export type WorkspaceRole = "administrator" | "vendor" | "rider" | "staff";

type RoleUser = { role_names?: string[] } | null | undefined;

/** Resolve the mobile workspace profile from the authenticated role set.
 * Administrator wins when a user has multiple roles so privileged users are
 * never accidentally placed in a limited self-service workspace.
 */
export function getWorkspaceRole(user: RoleUser): WorkspaceRole {
  const roles = user?.role_names || [];
  if (roles.includes("Administrator")) return "administrator";
  if (roles.includes("Vendor")) return "vendor";
  if (roles.includes("Rider")) return "rider";
  return "staff";
}

export function hasPermission(granted: readonly string[], required: readonly string[]): boolean {
  if (required.length === 0) return true;
  return required.some((req) => granted.includes(req));
}

export function hasAllPermissions(granted: readonly string[], required: readonly string[]): boolean {
  return required.every((permission) => granted.includes(permission));
}

type PermissionUser = RoleUser;

export function getRoleNames(user: PermissionUser, permissions: string[]): string[] {
  if (user?.role_names && user.role_names.length > 0) return user.role_names;
  const adminMarkers = [
    "identity.manage_users",
    "identity.manage_roles",
    "tenancy.manage_companies",
    "vendors.manage",
  ];
  const isAdmin = adminMarkers.every(m => permissions.includes(m));
  if (isAdmin) return ["Administrator"];
  const isVendor = VENDOR_SELF_PERMISSIONS.some(p => permissions.includes(p));
  if (isVendor) return ["Vendor"];
  return permissions.length > 0 ? ["Custom staff"] : [];
}
