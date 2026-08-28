import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const managerPermissions = [
  "catalog.view", "catalog.manage", "customers.view", "customers.manage",
  "inventory.view", "inventory.manage", "inventory.transfer", "orders.view",
  "orders.manage", "orders.change_status", "delivery.manage", "reports.view", "reports.export",
];

test.beforeEach(async ({ page }) => {
  await page.route("**/api/backend/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) {
      await route.fulfill({ json: { user: { id: "manager", username: "manager", account_status: "active", must_change_password: false, role_names: ["Manager"] }, company: { id: "company", name: "ChoiceOye", slug: "choiceoye" }, permissions: managerPermissions } });
      return;
    }
    if (path.endsWith("/commerce/dashboard")) {
      await route.fulfill({ json: { sales_minor_total: 125000, shop_sales_minor: 75000, online_sales_minor: 50000, order_count: 12, pending_orders: 3, low_stock_count: 2, product_count: 18, reserved_line_count: 4 } });
      return;
    }
    await route.fulfill({ json: [] });
  });
});

test("manager navigation is responsive and permission-filtered", async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: /good to see you/i })).toBeVisible();

  const width = page.viewportSize()?.width || 1440;
  if (width <= 767) {
    const mobileNavigation = page.getByRole("navigation", { name: "Mobile primary navigation" });
    await expect(mobileNavigation).toBeVisible();
    await expect(mobileNavigation.getByText("Orders", { exact: true })).toBeVisible();
    await mobileNavigation.getByRole("button", { name: "Open more navigation options" }).click();
  } else if (width <= 899) {
    await page.getByRole("button", { name: "Open navigation" }).click();
  }

  await expect(page.getByRole("link", { name: "Customers" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Accounting" })).toHaveCount(0);
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact || ""))).toEqual([]);
  await expect(page.locator("[data-nextjs-dialog], .vite-error-overlay, #webpack-dev-server-client-overlay")).toHaveCount(0);
  expect(consoleErrors).toEqual([]);
  if (width === 320 || width === 1920) await page.screenshot({ path: testInfo.outputPath("workspace.png"), fullPage: true });
});

test("unauthorized direct route renders a safe access-denied state", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  await page.goto("/admin/accounting");
  await expect(page.getByRole("heading", { name: /don’t have access/i })).toBeVisible();
  await expect(page.getByRole("link", { name: "Return to your workspace" })).toHaveAttribute("href", "/admin");
  await expect(page.locator("[data-nextjs-dialog], .vite-error-overlay, #webpack-dev-server-client-overlay")).toHaveCount(0);
  expect(consoleErrors).toEqual([]);
});

test("administrator can navigate the responsive identity workspace by keyboard", async ({ page }) => {
  await page.unroute("**/api/backend/**");
  await page.route("**/api/backend/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) {
      await route.fulfill({
        json: {
          user: { id: "administrator", username: "admin", account_status: "active", must_change_password: false, role_names: ["Administrator"] },
          company: { id: "company", name: "ChoiceOye", slug: "choiceoye" },
          permissions: ["identity.manage_users", "identity.manage_roles"],
        },
      });
      return;
    }
    if (path.endsWith("/identity/users")) {
      await route.fulfill({ json: [{ id: "admin", username: "admin", email: "admin@example.com", full_name: "Administrator", account_status: "active", must_change_password: false, role_ids: ["administrator"], role_names: ["Administrator"], company_id: "company" }] });
      return;
    }
    if (path.endsWith("/identity/roles")) {
      await route.fulfill({ json: [{ id: "administrator", name: "Administrator", is_custom: false, permissions: ["*"] }, { id: "manager", name: "Manager", is_custom: false, permissions: managerPermissions }] });
      return;
    }
    if (path.endsWith("/identity/permissions")) {
      await route.fulfill({ json: [{ id: "catalog.view", name: "View catalog", description: "View products and catalog references" }] });
      return;
    }
    await route.fulfill({ json: [] });
  });

  await page.goto("/admin/identity");
  const usersTab = page.getByRole("tab", { name: "Users" });
  const rolesTab = page.getByRole("tab", { name: "Roles" });
  await expect(usersTab).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("cell", { name: "admin", exact: true })).toBeVisible();

  await usersTab.focus();
  await page.keyboard.press("ArrowRight");
  await expect(rolesTab).toBeFocused();
  await expect(rolesTab).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("cell", { name: "Administrator", exact: true })).toBeVisible();

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations.filter((violation) => ["serious", "critical"].includes(violation.impact || ""))).toEqual([]);
});
