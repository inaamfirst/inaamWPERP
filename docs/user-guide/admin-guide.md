# Administrator Guide

## Administrator workspace

Sign in with the company workspace slug. The browser home is `/admin`. On wide
screens use the sidebar. On phones use the bottom bar and **More**. Admin
navigation is grouped as Overview, Operations, Commerce, Finance, and
Administration.

## Recommended setup order

1. Confirm **Admin → Administration → System diagnostics** is healthy.
2. Confirm the company and workspace slug with the deployment operator.
3. Review **Admin → Administration → Users & Roles** and ensure a second active
   Administrator exists before changing the first Administrator.
4. Create or approve staff and vendor accounts.
5. Create warehouses, categories, brands, and products.
6. Configure support contacts and browser notifications.
7. Configure WooCommerce only when its module and worker are approved.
8. Verify delivery riders, rider fees, finance accounts, and reconciliation.

## Dashboard — `Admin → Overview`

The dashboard provides the workspace selector **Combined**, **Shop / POS**, and
**Online Store**. It shows sales, orders, pending fulfilment, low stock,
reserved lines, products, attention counts, and channel performance. Quick
links are permission-filtered:

- **Manage vendors** → `/admin/vendors`
- **Review orders** → `/admin/orders`
- **Manage catalog** → `/admin/products`
- **Manage inventory** → `/admin/inventory`
- **Delivery dispatch** → `/admin/delivery`
- **Accounting** → `/admin/accounting`
- **Users & roles** → `/admin/identity`
- **Support directory** → `/admin/support`

The WooCommerce sync panel may show **Sync Products** and **Sync All Content**
actions when configured. A failure message should be investigated in
WooCommerce sync runs and worker diagnostics.

## Users & Roles — `Admin → Administration → Users & Roles`

The page has **Users** and **Roles** tabs. Use keyboard Left/Right arrows or
Home/End to move between tabs.

### Create a user

1. Choose **Add Vendor User** or **Add Staff User**.
2. Complete username, password, email, full name, and account status.
3. Select one or more roles. Vendor users also have a vendor profile section:
   business/legal name, contact name, vendor email, phone, vendor status, and
   commission in BPS.
4. If required, select **Require password change on next login**.
5. Choose **Create User**.

Vendor creation can use an activation link or a temporary password. Never put
temporary passwords or activation tokens in a shared support ticket.

### Edit, activate, pause, and reset

- **Edit** opens the selected user's detail form.
- **Activate** changes a non-active account to active.
- **Pause** temporarily disables an active account and revokes its active
  sessions.
- **Reset Password** is available in the desktop admin control center and the
  backend identity API. Require a password change for temporary credentials.
- **Cancel** closes the editor without saving.
- **Save Changes** writes the user and role changes.

Allowed account states are `active`, `pending`, `paused`, and `stopped`.

### Approve public registrations

The **Pending registrations** queue shows type, applicant, vendor details,
assignable roles, and actions.

1. Review username, email, full name, and vendor information.
2. For staff, select at least one role.
3. Vendor requests always retain the restricted Vendor role.
4. Choose **Approve** or **Reject**.

Approval activates the account; vendor approval also activates the vendor
profile. Rejection stops the account and revokes sessions.

### Manage roles

In the **Roles** tab, choose **Create Custom Role** or **Edit Permissions**.
Enter a role name for a new custom role, review the permission descriptions,
and choose **Save Role**. Choose **Cancel** to discard edits.

Editing a system role displays a warning because all assigned accounts are
affected. The backend remains authoritative if a permission is removed from
the UI or if a caller submits an untrusted role payload.

## Vendors and marketplace

### Vendor control — `Admin → Commerce → Vendors`

Use the vendor table to review contact, status, and commission. Available
buttons depend on status:

- Pending: **Approve**
- Active: **Pause**
- Paused: **Reactivate**

### Marketplace — `Admin → Commerce → Marketplace`

Use **Onboard vendor** to enter Business name, Contact name, Email, Phone, and
Commission (BPS). Choose **Create vendor**; new vendors begin as `pending`.

The vendor account table also provides **Refresh**, **Approve**, **Pause**,
**Reactivate**, and **Stop**. A commission of 500 BPS is 5.00%. The allowed
commission range is 0–10000 BPS.

Vendor states are `pending`, `active`, `paused`, and `stopped`. Legacy aliases
`approved`, `suspended`, and `rejected` are accepted for compatibility but
canonical output uses `active`, `paused`, and `stopped`.

## Catalog and customers

### Products — `Admin → Operations → Products`

Use **Add product** to create the core record. The short Admin editor supports
Name, SKU, Price (PKR), and Status (`active`, `draft`, `archived`). Use
**Refresh**, **Edit**, **Close**, **Save changes**, and **Archive** as needed.

**Archive** removes the product from active sales channels but preserves
history. Use the full vendor editor for variants, images, tax, shipping, SEO,
metadata, relationships, and publishing.

### Customers — `Admin → Operations → Customers`

Use **Add customer** and enter Full name, Email, Phone, Source, and—when
editing—Status. Source values are Manual, POS, WooCommerce, and Legacy. Use
**Refresh**, **Edit**, **New**, **Save customer**, and **Archive**. Archiving
does not delete historical orders.

## Inventory and delivery

### Inventory — `Admin → Operations → Inventory`

Use **Refresh**, **Add warehouse**, and **Record movement**. Warehouse Code
must contain only letters, numbers, `_`, or `-`. Stock movement requires a
warehouse, product, non-zero integer quantity, and audit reason.

### Delivery dispatch — `Admin → Operations → Delivery dispatch`

The metrics show Unassigned, Assigned, Out for delivery, Delivered, Failed,
and Active riders. In **Unassigned orders**, select a rider and choose
**Assign**. In **Assignments**, select another rider and choose **Save** to
reassign a non-delivered/non-cancelled assignment.

Do not reassign a terminal `delivered` or `cancelled` assignment through the
browser control. Inspect the order and delivery history instead.

## Orders and accounting

### Orders — `Admin → Operations → Orders`

Choose **Refresh**, select an order number, choose a new status, optionally
enter a reason, and choose **Save status**. The save button is disabled when
the selected status is unchanged. Read-only accounts see the order but no
mutation controls.

### Accounting — `Admin → Finance → Accounting`

Use **From**, **To**, **Clear dates**, and **Apply period** to control the
reporting period. Metric cards jump to COD, remittance, vendor, rider, or
profit sections.

Finance actions:

- **Accept / Reject** COD collections after reviewing expected, collected,
  receipt, and proof values.
- **Accept / Reject** rider cash remittances.
- **Approve / Reject** vendor sales. Approval creates a vendor payable.
- **Create vendor payout batch** after eligible sales are approved.
- **Fee** sets a rider's flat delivery fee.
- **Adjust** posts a rider ledger adjustment with a memo.
- **Payout** creates a rider payout from reconciled earnings.
- **Create account** adds a chart-of-accounts entry.

The visible chart-of-accounts form accepts Code, Name, and Account type:
Asset, Liability, Equity, Income, or Expense. The backend ledger additionally
supports Contra accounts and enforces balanced journals and locked periods.

## Support, settings, and diagnostics

### Support directory — `Admin → Administration → Support contacts`

Use **Add support contact** with Label, Role, WhatsApp number, Working hours, and
Default message. Contacts appear as vendor-facing WhatsApp options. Use
international phone format such as `+92...`.

### Settings — `Admin → Administration → Settings`

Use **Refresh**, select a setting key, edit its **JSON value**, choose **Save
setting**, or choose **Close**. The JSON must be valid. Infrastructure secrets
remain in the protected environment file, not in this screen.

For browser notifications use **Enable this browser**, **Send test**, and
**Disable this browser**. **Send test** and **Disable this browser** remain
disabled when no subscription exists.

### System diagnostics — `Admin → Administration → System diagnostics`

Use **Refresh** and review API, database, version, migration revision, module
release status, and redacted runtime diagnostics. A database marked degraded or
an unexpected migration revision should be handed to the deployment operator.

## Admin safety rules

- Confirm destructive actions in the dialog and prefer archive/reversal over
  permanent deletion or editing posted financial history.
- Do not expose passwords, refresh tokens, license keys, WooCommerce secrets,
  or raw diagnostic secrets.
- Check both account and vendor status before diagnosing a vendor login.
- Check the worker heartbeat before diagnosing queued WooCommerce work.
- Back up PostgreSQL before production migrations or restore operations.
