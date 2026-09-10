# AI Assistance Reference

This document is designed to be supplied to an AI assistant together with a
user's question. It gives the assistant a safe vocabulary for the ERP and a
repeatable way to answer “where do I click?” questions.

## 1. Assistant operating rules

Before giving a mutation instruction, identify:

1. The user's role: Administrator, Manager, custom staff, Vendor, or Rider.
2. The workspace slug/company.
3. The interface: browser or Windows desktop.
4. The screen or record involved.
5. The current status of that record.
6. The required permission and whether that permission is visible in the
   user's menu.
7. Whether the module is enabled and whether the capability is web, desktop,
   API-only, mocked, or foundation-only.

If any of these facts are unknown and they change the action, ask for that
fact. Do not assume that an Administrator-looking URL grants access.

Never ask the user to paste a password, refresh token, license key,
WooCommerce secret, private diagnostic payload, or customer data into the AI
conversation. Use placeholders such as `<workspace-slug>` and `<order-id>`.

For destructive or financial actions, tell the user what will change and ask
them to verify the record/status before selecting the control. Prefer archive,
reversal, or reconciliation workflows over deletion or editing history.

## 2. Standard knowledge record

Represent each answer internally with this shape:

```text
intent: what the user wants to accomplish
user_role: Administrator | Manager | Custom staff | Vendor | Rider
workspace: admin | vendor | rider
interface: browser | desktop | API
screen_or_route: visible page or API path
desktop_location: sidebar item and tab, if applicable
required_permissions: exact permission keys
prerequisites: account, module, status, data, or worker requirements
visible_controls: exact button/link/tab labels
required_inputs: fields and validation
allowed_values: statuses, types, methods, or enums
step_sequence: ordered actions
success_result: expected message, status, or next page
common_errors: likely failures
recovery_action: safe next step
related_routes: related browser/API paths
feature_status: available | disabled | API-only | desktop-only | foundation-only
```

## 3. Navigation records

| User intent | Navigate to | Required capability |
| --- | --- | --- |
| See company operations | Admin → Overview (`/admin`) | `reports.view` for the full summary |
| Review orders | Admin → Operations → Orders (`/admin/orders`) | `orders.view`; `orders.change_status` to modify |
| Manage catalog | Admin → Operations → Products (`/admin/products`) | `catalog.view`; `catalog.manage` to modify |
| Manage customers | Admin → Operations → Customers (`/admin/customers`) | `customers.view`; `customers.manage` to modify |
| Manage stock | Admin → Operations → Inventory (`/admin/inventory`) | `inventory.view`; `inventory.manage` to modify |
| Dispatch deliveries | Admin → Operations → Delivery (`/admin/delivery`) | `delivery.manage` |
| Approve vendors | Admin → Commerce → Marketplace (`/admin/marketplace`) | marketplace/vendor permissions |
| Reconcile finance | Admin → Finance → Accounting (`/admin/accounting`) | accounting/finance permissions |
| Manage accounts | Admin → Administration → Users & Roles (`/admin/identity`) | identity permissions |
| Configure WooCommerce | Admin → Commerce → WooCommerce (`/admin/woocommerce`) | `woocommerce.view`, `woocommerce.configure`, `woocommerce.sync` |
| Manage own products | Vendor → Catalog → Products (`/vendor/products`) | `vendor.products.view`, `vendor.products.manage` |
| Make a shop sale | Vendor → Selling → Shop POS (`/vendor/pos`) | `vendor.orders.manage` |
| Process vendor order items | Vendor → Selling → Online orders (`/vendor/orders`) | `vendor.orders.view`, `vendor.orders.manage` |
| Adjust own stock | Vendor → Catalog → Stock (`/vendor/stock`) | `vendor.stock.view`, `vendor.stock.manage` |
| See vendor payable | Vendor → Finance → Ledger (`/vendor/ledger`) | `vendor.ledger.view` |
| Update a delivery | Rider → Active work → Assigned deliveries (`/rider/deliveries`) | `delivery.view_assigned`, `delivery.update_assigned` |
| Submit COD/remittance | Rider → Account → Cash & earnings (`/rider/finance`) | `rider.finance.view`, `rider.finance.submit` |

Responsive directions:

```text
<768px: bottom navigation → More for secondary destinations
768–899px portrait: top bar → Open navigation → drawer
768–1199px landscape or 900px+: compact navigation rail
1200px+: persistent full sidebar
```

## 4. High-value task records

### Create a product

```text
intent: create product
user_role: Administrator or Vendor
screen_or_route: /admin/products/new or /vendor/products
required_permissions: catalog.manage or vendor.products.manage
prerequisites: active account; vendor must be active; marketplace module when vendor publishing is enabled
visible_controls: Add product/New product, Create product/Save product, Publish product, Save as draft
required_inputs: name; optional slug/SKU/barcode; product type; non-negative PKR price; status
allowed_values: simple, variable, digital, service; active, draft; visible, catalog, search, hidden
step_sequence: open page → choose add/new → complete Basic → save → add inventory/media/variants → publish only when ready
success_result: product appears in the product list and may become an active online listing
common_errors: missing permission; duplicate slug/SKU; upload before first save; invalid price or JSON
recovery_action: correct field, save first, refresh, and verify listing status
feature_status: available in browser and desktop with different editor depth
```

### Complete a vendor POS sale

```text
intent: record an in-store sale
user_role: Vendor
screen_or_route: /vendor/pos
required_permissions: vendor.orders.manage
prerequisites: active vendor; at least one warehouse/product; stock and payment method available
visible_controls: Warehouse, Customer / walk-in name, Payment method, Search products, Add, Review sale, Remove, Clear, Complete sale
required_inputs: warehouse; cart; payment method
allowed_values: cash, bank, card, cod
step_sequence: select warehouse → identify customer → choose payment → search/add items → review → complete
success_result: paid commerce sale/order and stock operation are recorded
common_errors: empty cart; insufficient stock; invalid warehouse; network timeout
recovery_action: check sale/order history before retrying to avoid duplication
feature_status: available in browser; desktop has related commerce controls
```

### Process an order to delivery

```text
intent: dispatch and deliver an order
user_role: Manager, custom staff with delivery.manage, and Rider
screen_or_route: /admin/delivery and /rider/deliveries
required_permissions: delivery.manage; rider requires delivery.view_assigned and delivery.update_assigned
prerequisites: order is ready for dispatch; active rider exists
visible_controls: Assign; Save for reassign; Mark picked up; Mark out for delivery; Mark delivered; Mark failed
allowed_values: assigned → picked_up → out_for_delivery → delivered; failed with required reason
step_sequence: admin selects rider → Assign → rider updates each next status → rider records failure reason if needed
success_result: assignment/status timestamps and history update
common_errors: no rider selected; terminal assignment; missing failure reason; assignment belongs to another rider
recovery_action: refresh, verify assignment/status, and ask dispatch for reassignment
feature_status: available in browser/API
```

### Reconcile COD and pay a vendor

```text
intent: move a delivered COD sale into a vendor payable
user_role: Rider then Administrator/Finance
screen_or_route: /rider/finance and /admin/accounting
required_permissions: rider.finance.submit; finance reconciliation/vendor settlement permissions
prerequisites: delivery delivered; rider has receipt/proof; collection submitted
visible_controls: Submit COD, Submit remittance, Accept, Reject, Approve, Reject, Create vendor payout batch
step_sequence: rider submits collection → admin accepts/rejects COD → admin reviews vendor sale → approve → create payout batch
success_result: accepted payment and approved vendor payable/settlement
common_errors: collection pending; proof missing; payment not reconciled; sale not delivered; finance status not eligible
recovery_action: correct the evidence or status first; never create a second payout just because a list is stale
feature_status: available when finance/marketplace modules are enabled
```

### Change a user's access

```text
intent: create, approve, pause, activate, or assign roles
user_role: Administrator
screen_or_route: /admin/identity
required_permissions: identity.view_users, identity.manage_users, identity.manage_roles as applicable
prerequisites: keep another active Administrator before changing the last admin
visible_controls: Add Vendor User, Add Staff User, Edit, Activate, Pause, Approve, Reject, Users, Roles, Edit Permissions, Save Changes, Save Role
allowed_values: account active, pending, paused, stopped; vendor role; custom permission sets
step_sequence: open Users → create/edit/approve → choose roles → save → require password change for temporary credentials
success_result: user/roles/status update and changed navigation after next auth refresh
common_errors: no role for staff approval; vendor relationship ambiguous; last admin protection; permission denied
recovery_action: assign a valid role, resolve vendor relationship, or ask another admin
feature_status: available in browser and desktop with different control depth
```

## 5. Exact control vocabulary

Use exact control names when answering. Common controls are grouped below.

| Area | Controls |
| --- | --- |
| Global | Open navigation, Close navigation, More, Profile and password, Sign out, Refresh, Close, Cancel, Dismiss notification, Return to your workspace |
| Auth | Sign In, Forgot password?, Request an account, Vendor, Staff, Request vendor account, Request staff account, Send reset link, Reset password, Save password, Return to sign in, Submit another request |
| Admin catalog | Add product, Create product, Edit, Save changes, Archive, Archive product |
| Admin customer | Add customer, Refresh, Edit, New, Save customer, Archive, Archive customer |
| Admin inventory | Create warehouse, Record movement, Refresh |
| Admin delivery | Assign, Save |
| Admin vendor | Create vendor, Refresh, Approve, Pause, Reactivate, Stop |
| Admin finance | Clear dates, Apply period, Accept, Reject, Approve, Create vendor payout batch, Fee, Adjust, Payout, Create account |
| Admin settings | Save setting, Enable this browser, Send test, Disable this browser |
| Admin WooCommerce | Save configuration, Test connection, Queue sync |
| Vendor POS | Add, Review sale, Remove, Close, Complete sale, Clear |
| Vendor products | New product, Refresh, Edit, Keep private, Publish, Close, Save product, Restore, Move to trash, Save as draft, Publish product, Delete permanently, New category, New brand, Add image URL, Upload image, Remove image, Add video URL, Upload MP4, Open selected video, Remove selected video, Add variant, Remove |
| Vendor stock | Adjust stock, Receive stock, Remove stock, Record damage, Save movement, Close |
| Vendor ledger | Refresh, Export CSV |
| Rider | Mark picked up, Mark out for delivery, Mark delivered, Mark failed, Submit COD, Submit remittance |

Some controls are conditional. If an AI answer names a button that is not
visible, first check role, permission, record status, module flag, and whether
the user is on browser versus desktop.

## 6. API lookup aliases

When the user asks for a technical operation, map it to the API prefix
`/api/v1` and the route family in the technical reference:

```text
login → POST /api/v1/auth/login
current user/permissions → GET /api/v1/auth/me
products → /api/v1/catalog/products or /api/v1/vendor/catalog/products
orders → /api/v1/orders or /api/v1/vendor/orders
vendor POS → POST /api/v1/commerce/vendor/pos/sales
dispatch → /api/v1/delivery/admin/assignments
rider status → POST /api/v1/delivery/rider/assignments/{id}/status
COD → /api/v1/rider/finance/cod-collections and /api/v1/finance/cod-collections/{id}/reconcile
vendor finance → /api/v1/finance/vendor-sales and /api/v1/marketplace/settlements
health → GET /api/v1/health
```

Do not instruct a normal user to call an API when the same action has a visible
screen. Use API directions for developers, integrations, and operators only.

## 7. Clarifying questions an AI should ask

Ask only questions that change the answer:

- “Are you using the browser or the Windows desktop?”
- “Which workspace slug are you signed into?”
- “What role is shown for your account?”
- “What is the current status of the order/product/vendor/delivery?”
- “Do you see the named menu item or is it hidden?”
- “Is the WooCommerce/Marketplace/Accounting module enabled in this deployment?”
- “Has the worker processed the queued sync?”

If the user reports an error, request the screen name, route, action, record
status, time, and non-sensitive error message—not credentials or raw tokens.
