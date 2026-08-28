import { describe, expect, it } from "vitest";
import { canAccessPolicy, getCanonicalHome, getPolicyForPath, getWorkspacePolicies } from "./access-policy";

const managerPermissions = [
  "catalog.view", "catalog.manage", "customers.view", "customers.manage",
  "inventory.view", "inventory.manage", "inventory.transfer", "orders.view",
  "orders.manage", "orders.change_status", "delivery.manage", "reports.view", "reports.export",
];

describe("access policy", () => {
  it("shows managers only their core operations workspace", () => {
    const ids = getWorkspacePolicies("admin", managerPermissions).map((policy) => policy.id);
    expect(ids).toEqual([
      "admin-home", "admin-orders", "admin-products", "admin-customers",
      "admin-inventory", "admin-delivery",
    ]);
    expect(getCanonicalHome("staff", managerPermissions)).toBe("/admin");
  });

  it("keeps hidden mutation routes out of navigation but protects direct access", () => {
    expect(getWorkspacePolicies("admin", ["catalog.manage"]).some((policy) => policy.id === "admin-product-new")).toBe(false);
    const policy = getPolicyForPath("/admin/products/new");
    expect(policy?.id).toBe("admin-product-new");
    expect(canAccessPolicy(policy!, ["catalog.view"])).toBe(false);
    expect(canAccessPolicy(policy!, ["catalog.manage"])).toBe(true);
  });

  it("exposes the vendor ledger only with its canonical permission", () => {
    const withoutLedger = getWorkspacePolicies("vendor", ["vendor.profile.view", "vendor.products.view"]);
    expect(withoutLedger.some((policy) => policy.id === "vendor-ledger")).toBe(false);
    const withLedger = getWorkspacePolicies("vendor", ["vendor.profile.view", "vendor.ledger.view"]);
    expect(withLedger.some((policy) => policy.id === "vendor-ledger")).toBe(true);
  });
});
