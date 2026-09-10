# Manager and Staff Guide

## Access model

Managers normally use the Admin workspace at `/admin` with the default
operations permissions:

```text
catalog.view, catalog.manage
customers.view, customers.manage
inventory.view, inventory.manage, inventory.transfer
orders.view, orders.manage, orders.change_status
delivery.manage
reports.view, reports.export
```

Custom staff may have a smaller or different union of permissions. The menu is
therefore not identical for every staff member. If a destination is missing,
ask an administrator to review the role rather than attempting to bypass the
UI.

## Finding your work

Use:

- **Admin → Overview** for summary metrics and permitted quick actions.
- **Admin → Operations → Orders** for order review and controlled status
  changes.
- **Admin → Operations → Products** for catalog work.
- **Admin → Operations → Customers** for contact data.
- **Admin → Operations → Inventory** for warehouse and stock movements.
- **Admin → Operations → Delivery dispatch** for rider assignment.
- **Admin → Overview → Reports/summary** when `reports.view` is granted.

On mobile, the first four destinations appear in bottom navigation; choose
**More** for the rest.

## Common procedures

### Review an order

1. Open **Orders**.
2. Choose **Refresh**.
3. Select the order number.
4. Review total, payment, current status, and any operational history.
5. If `orders.change_status` is granted, select **New status**, enter an
   optional **Reason**, and choose **Save status**.

The save action is disabled if the new status equals the current status. If
the editor displays **This account has read-only order access**, ask for
permission rather than retrying.

### Create or edit a product

1. Open **Products & catalog**.
2. Choose **Add product** or **Edit**.
3. Enter Name, SKU, Price (PKR), and Status.
4. Choose **Create product** or **Save changes**.
5. Use **Archive** only when the product should leave active sales channels.

The complete multi-tab product editor is available in the vendor product
surface and desktop client. It includes pricing, inventory, shipping, images,
variants, SEO, and advanced metadata.

### Add a customer

1. Open **Customers**.
2. Choose **Add customer**.
3. Enter Full name; optionally enter Email and Phone.
4. Choose Source: Manual, POS, WooCommerce, or Legacy.
5. Choose **Save customer**.

Use **Edit** to update a record. Existing order history must be preserved, so
use **Archive** rather than deleting a customer when the person should no
longer appear in active searches.

### Record stock

1. Open **Inventory**.
2. Choose a warehouse and product.
3. Enter a non-zero integer quantity change and a reason.
4. Choose **Record movement**.
5. Choose **Refresh** to verify the resulting stock level.

Stock changes are auditable. Do not use a negative adjustment to conceal a
discrepancy; record the correct reason and escalate if the quantity is wrong.

### Dispatch a delivery

1. Open **Delivery dispatch**.
2. In **Unassigned orders**, select a rider.
3. Choose **Assign**.
4. Monitor **Assignments** and delivery status metrics.
5. For a non-terminal assignment, select a different rider and choose **Save**
   if reassignment is necessary.

Riders then progress `assigned → picked_up → out_for_delivery → delivered`.
Failed deliveries require a rider-entered reason.

## What managers and staff normally cannot do

The default Manager role does not grant identity administration, vendor
approval, accounting, settings, system diagnostics, licensing, or WooCommerce
configuration. A custom role may grant additional permissions, but each
permission should be assigned deliberately.

If you need a finance, vendor, or account action, give an administrator the
record identifier, current status, and business reason. Do not ask users to
share their passwords or tokens.

## Read-only and error states

- **No actions are assigned to this account** means the dashboard has no
  permitted quick link.
- A missing **Edit**, **Archive**, **Assign**, or **Save status** control means
  the relevant mutation permission is not granted.
- **You don't have access to this page** means the direct route is outside the
  workspace/permission contract.
- **Unable to load** messages should be retried with **Refresh** once; then
  report the page, time, workspace slug, and request/error text to an admin.
