# Technical Reference

## 1. Source and runtime map

The current implementation is a FastAPI backend, Next.js browser frontend,
PySide6 desktop client, PostgreSQL production database, SQLite local/offline
cache/test profile, and optional worker for durable integration jobs.

| Surface | Location/pattern | Notes |
| --- | --- | --- |
| Browser application | Next.js `frontend/src/app` | Canonical homes are `/admin`, `/vendor`, `/rider` |
| Browser backend proxy | `/api/backend/*` | Frontend proxy to the configured backend |
| API | `/api/v1/*` | FastAPI routes; bearer/session authentication as applicable |
| Server-rendered public fallback | `/login`, `/register`, `/account`, `/store/...` | FastAPI web routes |
| Desktop | `erp-desktop` / PySide6 | API-backed; no direct database access |
| Worker | `erp-worker` | WooCommerce and other durable background operations |
| License service | `erp-license-server` | Lightweight foundation shell |

The browser source uses `fetchApi()` against `/api/backend`; it does not expose
the database URL or use database credentials in the browser.

## 2. Browser routes and links

### Authentication and public routes

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/` | Next.js: redirect to login/password-change/canonical workspace; FastAPI fallback: redirect to `/marketplace` |
| GET/POST | `/login` | Server-rendered fallback sign-in |
| GET/POST | `/register` | Server-rendered fallback registration |
| GET | `/register/success` | Registration success page |
| GET | `/account` | Authenticated account/session view |
| GET/POST | `/session/refresh` | Continue a refresh-token session |
| GET/POST | `/logout` | Confirm and perform logout |
| GET/POST | `/activate` | Set a password from an activation token |
| GET/POST | `/forgot-password` | Request a password reset |
| GET/POST | `/reset-password` | Set a password from a reset token |
| GET | `/marketplace` | Public marketplace landing page |
| GET | `/store/{workspace_slug}` | Company storefront |
| GET | `/store/{workspace_slug}/vendors/{vendor_slug}` | Vendor storefront |

Browser application routes:

```text
/login
/register
/forgot-password
/reset-password
/change-password
/admin
/admin/orders
/admin/products
/admin/products/new
/admin/customers
/admin/inventory
/admin/delivery
/admin/vendors
/admin/marketplace
/admin/accounting
/admin/woocommerce
/admin/support
/admin/identity
/admin/settings
/admin/system
/vendor
/vendor/pos
/vendor/products
/vendor/orders
/vendor/stock
/vendor/ledger
/vendor/reports
/vendor/support
/rider
/rider/deliveries
/rider/today
/rider/history
/rider/finance
```

Legacy `/products` and `/products/new` redirect to the canonical Admin product
routes. Legacy `/orders` redirects to Admin orders. The current user area
links to `/change-password`; **Return to your workspace** links to the user's
canonical role home. The Next.js registration page currently posts its public
request to the `staging` workspace; the server-rendered fallback accepts the
workspace value supplied in its form/query string. Public storefront routes
are catalog display pages only and do not provide a cart or checkout.

## 3. API conventions

The API prefix is normally `/api/v1`. The following tables list route paths
relative to that prefix. All protected routes require the authenticated session
and tenant/company scope. Exact backend permission checks remain authoritative.

`GET` routes generally list or inspect records. `POST` creates or performs an
action. `PATCH` and `PUT` update a record. `DELETE` archives/removes a record.
Use the response's `detail`, request ID, and current record status when
diagnosing an error.

### System, identity, tenancy, and settings

| Method | Path | Capability |
| --- | --- | --- |
| GET | `/health` | API/database/migration health |
| GET | `/modules` | Enabled module list |
| GET/POST | `/setup/status`, `/setup/first-use` | First-use bootstrap |
| POST | `/auth/login` | Login |
| GET | `/auth/me` | Current user, company, roles, permissions |
| POST | `/auth/refresh` | Rotate/refresh session |
| POST | `/auth/logout` | Revoke session |
| POST | `/auth/change-password` | Change current password |
| POST | `/auth/password-reset/request` | Request reset email |
| POST | `/auth/password-reset/confirm` | Confirm reset token |
| POST | `/auth/activate` | Confirm activation token |
| POST | `/auth/register/vendor` | Public vendor registration |
| POST | `/auth/register/user` | Public staff registration |
| GET | `/identity/permissions` | Declared permissions |
| GET | `/identity/roles` | Company roles |
| POST/PATCH | `/identity/roles`, `/identity/roles/{role_id}` | Create/update roles |
| GET | `/identity/users` | Company users |
| GET | `/identity/registrations/pending` | Approval queue |
| POST | `/identity/registrations/{user_id}/approve` | Approve registration |
| POST | `/identity/registrations/{user_id}/reject` | Reject registration |
| GET | `/identity/users/{user_id}` | User detail |
| POST | `/identity/users` | Create user |
| PATCH | `/identity/users/{user_id}` | Update user |
| POST | `/identity/users/{user_id}/reset-password` | Admin reset |
| GET/POST | `/tenancy/companies` | List/create companies |
| PATCH | `/tenancy/companies/{company_id}` | Update company |
| GET | `/settings` | Persisted company settings |
| PUT | `/settings/{key}` | Update a JSON setting |
| GET | `/audit-logs` | Tenant-scoped audit history |

### Catalog, inventory, customers, and orders

| Method | Path | Capability |
| --- | --- | --- |
| GET/POST | `/catalog/categories` | List/create categories |
| GET/PATCH/DELETE | `/catalog/categories/{category_id}` | Inspect/update/archive category |
| GET/POST | `/catalog/brands` | List/create brands |
| GET/PATCH/DELETE | `/catalog/brands/{brand_id}` | Inspect/update/archive brand |
| GET/POST | `/catalog/products` | List/create products |
| GET | `/catalog/products/code-suggestion` | Generate product code suggestion |
| GET/PATCH | `/catalog/products/{product_id}` | Inspect/update product |
| POST | `/catalog/products/{product_id}/images/upload` | Upload product image |
| POST | `/catalog/products/{product_id}/videos/upload` | Upload product MP4 video; syncs when the optional WordPress plugin is configured |
| DELETE | `/catalog/products/{product_id}` | Archive product |
| DELETE | `/catalog/products/{product_id}/permanent` | Permanent product deletion |
| GET/POST | `/inventory/warehouses` | List/create warehouses |
| GET/PATCH/DELETE | `/inventory/warehouses/{warehouse_id}` | Inspect/update/archive warehouse |
| GET/POST | `/inventory/stock-movements` | List/create stock movements |
| GET | `/inventory/stock` | Derived stock levels |
| GET/POST | `/customers` | List/create customers |
| GET/PATCH/DELETE | `/customers/{customer_id}` | Inspect/update/archive customer |
| POST | `/customers/{customer_id}/addresses` | Add customer address |
| POST | `/customers/{customer_id}/notes` | Add customer note |
| GET/POST | `/orders` | List/create orders |
| GET | `/orders/{order_id}` | Order detail |
| POST | `/orders/{order_id}/status` | Controlled order status change |
| POST | `/orders/{order_id}/payments` | Add order payment |

### Commerce, vendor portal, and support

| Method | Path | Capability |
| --- | --- | --- |
| GET | `/commerce/dashboard` | Admin/staff commerce dashboard |
| GET | `/commerce/vendor/dashboard` | Vendor commerce dashboard |
| GET/PUT | `/commerce/vendor/products/channels`, `/commerce/vendor/products/{product_id}/channel` | Vendor channel listings |
| GET/PUT | `/commerce/admin/products/channels`, `/commerce/admin/products/{product_id}/channel` | Admin channel listings |
| GET | `/commerce/vendor/stock` | Vendor stock view |
| GET | `/commerce/vendor/ledger/overview` | Vendor commerce ledger summary |
| GET | `/commerce/vendor/warehouses` | Vendor warehouses |
| POST | `/commerce/vendor/stock/movements` | Vendor stock movement |
| POST | `/commerce/vendor/pos/sales` | Vendor POS sale |
| POST | `/commerce/admin/pos/sales` | Admin POS sale |
| POST | `/commerce/stock/reservations` | Stock reservation |
| GET | `/commerce/support/contacts` | Vendor support contacts |
| GET/POST/PUT | `/commerce/admin/support/contacts`, `/commerce/admin/support/contacts/{contact_id}` | Admin support directory |
| GET/POST | `/marketplace/vendors` | List/create vendors |
| POST | `/marketplace/vendors/with-account` | Create vendor and linked account |
| GET/PUT | `/marketplace/vendors/{vendor_id}` | Vendor detail/update |
| POST/PATCH | `/marketplace/vendors/{vendor_id}/approve`, `/marketplace/vendors/{vendor_id}/status` | Vendor lifecycle |
| POST | `/marketplace/vendors/{vendor_id}/pause` | Pause vendor |
| POST | `/marketplace/vendors/{vendor_id}/reactivate` | Reactivate vendor |
| POST | `/marketplace/vendors/{vendor_id}/stop` | Stop vendor |
| GET/POST | `/marketplace/vendors/{vendor_id}/users` | Linked vendor users |
| GET | `/marketplace/vendors/{vendor_id}/products` | Admin vendor products |
| POST | `/marketplace/vendor-products/assign` | Assign product to vendor |
| POST | `/marketplace/vendors/{vendor_id}/products/{product_id}/approve` | Approve vendor product |
| GET/POST/PUT | `/marketplace/commission-rules`, `/marketplace/commission-rules/{rule_id}` | Commission rules |
| GET | `/marketplace/vendors/{vendor_id}/order-items` | Admin vendor order items |
| GET | `/marketplace/vendor/orders`, `/vendor/orders` | Current vendor order items |
| GET | `/marketplace/vendors/{vendor_id}/settlements` | Admin vendor settlements |
| GET | `/marketplace/vendor/settlements`, `/vendor/settlements` | Current vendor settlements |
| POST | `/marketplace/settlements` | Create vendor settlement |
| GET | `/marketplace/vendors/{vendor_id}/notifications` | Vendor notifications |
| GET | `/marketplace/vendor/me`, `/vendor/me` | Current vendor profile |
| GET | `/marketplace/vendor/dashboard`, `/vendor/dashboard` | Current vendor dashboard |
| GET | `/marketplace/vendor/products`, `/vendor/products` | Current vendor's product list |
| GET/POST | `/vendor/catalog/categories`, `/vendor/catalog/brands`, `/vendor/catalog/products` | Vendor self-service catalog |
| GET | `/vendor/catalog/products/{product_id}` | Vendor product detail |
| POST | `/vendor/catalog/products/{product_id}/images/upload` | Vendor image upload |
| POST | `/vendor/catalog/products/{product_id}/videos/upload` | Vendor product MP4 upload; syncs when the optional WordPress plugin is configured |
| PATCH/DELETE | `/vendor/catalog/products/{product_id}` | Vendor update/archive |
| DELETE | `/vendor/catalog/products/{product_id}/permanent` | Vendor permanent delete |
| POST | `/vendor/order-items/{vendor_order_item_id}/status` | Vendor order item status |
| GET | `/vendor/order-items/{vendor_order_item_id}/history` | Vendor item status history |
| GET | `/vendor/sales`, `/vendor/reports/sales` | Vendor sales report |
| GET | `/vendor/stock/overview`, `/vendor/reports/stock` | Vendor stock report |
| GET | `/vendor/stock/movements` | Vendor stock movement history |
| POST | `/vendor/stock/movements` | Vendor stock movement create |
| GET | `/vendor/reports/settlements` | Vendor settlement report |

### Delivery and finance

| Method | Path | Capability |
| --- | --- | --- |
| GET | `/delivery/admin/summary` | Dispatch metrics |
| GET | `/delivery/admin/riders` | Active riders |
| GET | `/delivery/admin/unassigned` | Ready unassigned orders |
| GET | `/delivery/admin/assignments` | All assignments |
| POST | `/delivery/admin/assignments` | Assign order to rider |
| PUT | `/delivery/admin/assignments/{assignment_id}` | Reassign delivery |
| GET | `/delivery/rider/dashboard` | Rider delivery dashboard |
| GET | `/delivery/rider/assignments` | Rider's assignments |
| POST | `/delivery/rider/assignments/{assignment_id}/status` | Rider status update |
| GET | `/finance/dashboard` | Finance dashboard |
| GET | `/finance/cod-collections` | Pending COD collections |
| POST | `/finance/cod-collections/{collection_id}/reconcile` | Accept/reject COD |
| GET | `/finance/remittances` | Pending rider remittances |
| POST | `/finance/remittances/{remittance_id}/reconcile` | Accept/reject remittance |
| GET/PUT | `/finance/riders/profiles`, `/finance/riders/{rider_user_id}/profile` | Rider fee profiles |
| GET | `/finance/riders/{rider_user_id}/summary` | Rider finance summary |
| GET | `/finance/riders/{rider_user_id}/ledger` | Rider ledger |
| POST | `/finance/riders/{rider_user_id}/adjustments` | Rider adjustment |
| GET/POST | `/finance/riders/{rider_user_id}/payouts` | Rider payout history/create |
| POST | `/finance/vendor-order-items/{vendor_order_item_id}/decision` | Approve/reject vendor sale |
| GET | `/finance/vendor-sales` | Eligible vendor sales |
| GET | `/rider/finance/summary` | Current rider finance summary |
| GET/POST | `/rider/finance/cod-collections` | Rider COD history/create |
| GET/POST | `/rider/finance/remittances` | Rider remittance history/create |
| GET | `/rider/finance/ledger` | Rider earnings ledger |
| GET | `/rider/finance/payouts` | Rider payout history |

### Accounting and authoritative ledger

| Method | Path | Capability |
| --- | --- | --- |
| GET/POST/PUT | `/accounting/accounts`, `/accounting/accounts/{account_id}` | Legacy/accounting chart entries |
| GET/POST/PUT | `/accounting/periods`, `/accounting/periods/{period_id}` | Accounting periods |
| GET | `/accounting/journal-entries`, `/accounting/journal-entries/{entry_id}` | Journal projections |
| POST | `/accounting/journal-entries` | Create journal entry |
| GET | `/accounting/vendor-ledger` | Vendor ledger projection |
| GET/POST | `/accounting/cash-books` | Cash books |
| GET/POST | `/accounting/bank-accounts` | Bank accounts |
| GET/POST | `/accounting/expenses` | Expenses |
| GET | `/ledger/overview` | Ledger control summary |
| GET | `/ledger/accounts` | Ledger accounts |
| GET/POST/PATCH | `/ledger/periods`, `/ledger/periods/{period_id}` | Ledger periods/status |
| GET | `/ledger/journals`, `/ledger/journals/{journal_id}` | Journal list/detail |
| POST | `/ledger/journals` | Post journal |
| POST | `/ledger/journals/{journal_id}/reverse` | Reverse journal |
| GET | `/ledger/trial-balance` | Trial balance |
| GET | `/ledger/reports/profit-loss` | Profit and loss |
| GET | `/ledger/reports/balance-sheet` | Balance sheet |
| GET | `/ledger/reports/cash-flow` | Cash flow |
| GET | `/ledger/reports/vendor-payables` | Vendor payables/aging |
| GET | `/ledger/reports/inventory` | Inventory ledger report |
| GET | `/ledger/reconciliation` | Reconciliation issues |
| POST | `/ledger/vendor-inventory/movements` | Admin vendor inventory movement |
| GET | `/ledger/vendors/{vendor_id}/overview` | Admin vendor overview |
| GET | `/ledger/vendors/{vendor_id}/ledger` | Admin vendor ledger |
| GET | `/ledger/vendors/{vendor_id}/stock` | Admin vendor stock |
| GET | `/ledger/vendors/{vendor_id}/stock/movements` | Admin vendor stock history |
| GET | `/ledger/vendors/{vendor_id}/orders` | Admin vendor orders |
| GET | `/ledger/vendors/{vendor_id}/sales`, `/ledger/vendors/{vendor_id}/reports/sales` | Admin vendor sales |
| GET | `/ledger/vendors/{vendor_id}/settlements`, `/ledger/vendors/{vendor_id}/reports/settlements` | Admin vendor settlements |
| GET | `/ledger/vendors/{vendor_id}/reports/stock` | Admin vendor stock report |
| GET | `/ledger/vendors/{vendor_id}/audit` | Admin vendor audit |
| GET | `/vendor/ledger/overview` | Current vendor ledger overview |
| GET | `/vendor/ledger/entries` | Current vendor ledger entries |
| GET | `/ledger/export/journals.csv` | CSV journal export |

### Reports, connectors, backup, licensing, and notifications

| Method | Path | Capability |
| --- | --- | --- |
| GET | `/reports/dashboard-summary` | Summary metrics |
| GET | `/reports/sales` | Sales report |
| GET | `/reports/inventory` | Inventory report |
| GET | `/reports/customers` | Customer report |
| GET | `/reports/orders` | Order report |
| GET | `/reports/orders.csv` | Order CSV export |
| GET/PUT | `/woocommerce/config` | WooCommerce settings |
| POST | `/woocommerce/test-connection` | Connector test |
| POST | `/woocommerce/sync` | Queue sync |
| GET | `/woocommerce/sync-runs` | Sync history |
| GET | `/woocommerce/conflicts` | Open conflicts |
| POST | `/woocommerce/conflicts/{conflict_id}/resolve` | Resolve conflict |
| POST | `/woocommerce/webhooks` | WooCommerce webhook receiver |
| GET/POST | `/whatsapp/templates` | Template list/create |
| GET/POST | `/whatsapp/messages` | Message queue/list/create |
| POST | `/whatsapp/messages/{message_id}/mock-send` | Mock send |
| GET | `/whatsapp/messages/{message_id}/delivery-logs` | Delivery logs |
| POST | `/backup/sqlite` | SQLite/dev backup |
| POST | `/backup/restore-plan` | Non-destructive restore plan |
| GET | `/licensing/status` | License status |
| POST | `/licensing/activate` | License activation |
| POST | `/licensing/validate` | License validation |
| POST | `/licensing/revoke` | License revocation |
| GET | `/support/diagnostics` | Redacted diagnostics |
| GET | `/support/diagnostics.zip` | Redacted diagnostics archive |
| GET | `/push/config` | Browser push configuration |
| GET | `/push/subscriptions` | Current push subscriptions |
| POST | `/push/subscriptions` | Register browser subscription |
| DELETE | `/push/subscriptions/{subscription_id}` | Remove subscription |
| POST | `/push/test` | Send test push |

### Separate license-service API

The repository also contains a small license server application. It runs as a
separate process (`scripts/run_license_server.ps1`) and is not part of the
normal ERP browser sidebar or `/api/v1` API. Its URL is the configured license
server base URL. Interactive API documentation is available at `/docs` only
when documentation is enabled.

| Method | Path | Authentication and purpose |
| --- | --- | --- |
| GET | `/license/v1/health` | License database and migration health; no ERP session |
| POST | `/license/v1/licenses/activate` | Create or return a device-bound license; JSON requires `license_key`, `company_id`, `company_name`, `device_id`, and optional `plan` |
| POST | `/license/v1/licenses/validate` | Validate by `license_id` or `license_key_hash` plus `device_id` |
| POST | `/license/v1/licenses/revoke` | Revoke a license; requires `x-license-admin-key` and `license_id` or `license_key`, with optional `reason` |
| POST | `/license/v1/licenses/renew` | Extend a license; requires `x-license-admin-key` and `license_id` or `license_key`, with optional `reason` and `extend_days` (1–3650) |

The license service returns the license identifier, hashed key, status, plan,
device binding, expiry/grace dates, and signed payload fields. Never place a
raw license key or admin key in documentation, tickets, prompts, logs, or
client-side code. The in-repository service is a lightweight foundation; use
the deployment's protected database and secret management before treating it
as a production licensing authority.

## 4. Permission families

| Module | Permission keys |
| --- | --- |
| Core | `core.view_health`, `core.view_modules` |
| Identity | `identity.view_users`, `identity.manage_users`, `identity.manage_roles`, `identity.manage_sessions` |
| Tenancy | `tenancy.view_companies`, `tenancy.manage_companies` |
| Catalog | `catalog.view`, `catalog.manage` |
| Customers | `customers.view`, `customers.manage` |
| Inventory | `inventory.view`, `inventory.manage`, `inventory.transfer` |
| Orders/delivery | `orders.view`, `orders.manage`, `orders.change_status`, `delivery.manage`, `delivery.view_assigned`, `delivery.update_assigned`, `rider.finance.view`, `rider.finance.submit` |
| Reports | `reports.view`, `reports.export` |
| Marketplace admin | `vendors.view`, `vendors.manage`, `vendors.users.manage`, `vendors.products.manage`, `vendors.orders.view`, `vendors.assign_orders`, `vendors.settle`, `vendors.commissions.manage` |
| Vendor self-service | `vendor.profile.view`, `vendor.products.view`, `vendor.products.manage`, `vendor.orders.view`, `vendor.orders.manage`, `vendor.settlements.view`, `vendor.ledger.view`, `vendor.stock.view`, `vendor.stock.manage`, `vendor.reports.view` |
| Accounting | `accounting.view`, `accounting.post`, `accounting.reconcile`, `accounting.reports`, `accounting.manage_accounts` |
| Ledger | `ledger.view`, `ledger.post`, `ledger.reverse`, `ledger.manage_periods`, `ledger.export` |
| WooCommerce | `woocommerce.view`, `woocommerce.configure`, `woocommerce.sync` |
| WhatsApp | `whatsapp.view`, `whatsapp.configure`, `whatsapp.send` |
| Settings/support | `settings.view`, `settings.manage`, `support.view_diagnostics` |
| Backup/licensing/audit | `backup.view`, `backup.create`, `backup.restore`, `licensing.view`, `licensing.manage`, `audit.view` |

The default Manager and Vendor permission sets are defined in
`erp/packages/core/services.py`; do not infer a user's actual grants from role
name alone. Use `/auth/me` or the UI's visible navigation.

## 5. Status and validation rules

### Accounts and vendors

```text
Account: active | pending | paused | stopped
Vendor: active | pending | paused | stopped
Legacy vendor aliases: approved → active, suspended → paused, rejected → stopped
```

Vendor access requires both the user and vendor business to be active.

### Orders and deliveries

```text
General order: pending, confirmed, processing, ready, dispatched,
               delivered, cancelled, returned, refunded
Vendor item: pending → accepted → packing → dispatched → delivered
             pending → rejected
Delivery: assigned → picked_up → out_for_delivery → delivered
          active delivery → failed
```

Status transitions are recorded in history. Delivery failure requires a reason.

### Payments and finance

Payment statuses are `pending`, `paid`, `failed`, and `refunded`. COD collection
and remittance records remain pending until finance reconciliation. A delivered
vendor sale must have reconciled payment and finance approval before it enters
a vendor payable/settlement. Rider payouts use reconciled eligible earnings.

### Product and stock

Product types include `simple`, `variable`, `digital`, and `service`. Product
visibility values are `visible`, `catalog`, `search`, and `hidden`; backorders
are `no`, `notify`, or `yes`; stock status is `instock`, `outofstock`, or
`onbackorder`.

Stock movement types exposed in the vendor UI are `stock_in`, `stock_out`, and
`damaged`. Backend movement records may also support reservations, releases,
returns, transfers, opening balances, and count corrections.

### Money and idempotency

Money is integer minor units with a three-letter currency, normally PKR. For
example, `500` means `PKR 5.00`. Finance and commerce create operations use
idempotency keys where defined; callers should reuse the same key when safely
retrying an operation and inspect the existing result before making a new key.

## 6. Module status

| Module | Manifest status | Enabled by default | User-facing boundary |
| --- | --- | --- | --- |
| Core | Implemented | Yes | Health, modules, setup |
| Identity | Implemented | Yes | Authentication, users, roles |
| Tenancy | Implemented | Yes | Company API/desktop administration |
| Catalog | Implemented | Yes | Products and catalog |
| Customers | Implemented | Yes | Customer directory |
| Inventory | Implemented | Yes | Warehouses and stock |
| Orders | Implemented | Yes | Orders, delivery permissions, rider finance permissions |
| Reports | Implemented | Yes | Operational summaries and CSV export |
| Settings | Implemented | Yes | Company settings |
| Audit | Implemented | Yes | API audit logs |
| Support | Implemented | Yes | Diagnostics and redacted archive |
| Backup | Implemented | Yes | SQLite/dev backup and restore plan |
| Accounting | Implemented | No | Accounting/ledger foundation; enable deliberately |
| Marketplace | Implemented | No | Vendor portal/settlements; enable deliberately |
| WooCommerce | Implemented | No | Connector foundation; worker/live-store approval required |
| WhatsApp | Implemented | No | Queue/template/mock adapter foundation |
| Licensing | Implemented | Yes | Activation/status foundation, not full hosted licensing |

“Implemented” in the manifest means routes/services exist. It does not imply
that a module is enabled in a deployment, that its browser page exposes every
API operation, or that its integration is production-certified.

## 7. Key request contracts

The backend schemas are the final validation authority. The following are the
important user-operation payloads; optional metadata fields are omitted unless
they affect the workflow.

| Operation | Required fields | Important allowed values/validation |
| --- | --- | --- |
| First-use setup | `company_name`, `username`, `password` | Company name ≥2; username 3–120 matching `A-Za-z0-9_.-`; password 8–128 |
| Login | `username`, `password`; optional `workspace_slug`/`company_id` | Workspace slug is normalized; account must be active |
| Password change/reset | Current/new password, or token/new password | New password 8–128; confirmation is a frontend check |
| Vendor registration | `workspace_slug`, `business_name`, `username`, `email`, `password` | Vendor request starts pending; optional contact/phone |
| Staff registration | `workspace_slug`, `username`, `email`, `password` | Staff request starts pending and receives no public-selected roles |
| User create/update | Username/password for create; email/full name/role IDs/status | Status `active`, `pending`, `paused`, `stopped`; username pattern above |
| Role create/update | Role name and selected permission IDs | Name ≥2; permission set is backend-checked |
| Product create/update | `name`; optional slug/SKU/barcode/type/status/prices/catalog/media/variants | `videos` supports up to 10 HTTPS direct-MP4, YouTube, or Vimeo URLs; MP4 uploads are limited to 100 MB. With the optional ChoiceOye plugin, videos synchronize separately through `choiceoye_erp_product_videos`, never WooCommerce's `images` array. |
| Warehouse create/update | Code and name | Code uses letters, numbers, `_`, `-`; name ≥2 |
| Stock movement | Movement type, warehouse, product, quantity/reason as applicable | General API quantity is positive; browser adjustment uses a signed non-zero delta |
| Customer create/update | Full name for create; email/phone/status/source optional | Source values include `manual`, `pos`, `woocommerce`, `legacy` |
| Order status | `status`; optional `reason` | Status must pass the controlled order transition rules |
| Order payment | Amount/currency/method/status | Payment status `pending`, `paid`, `failed`, `refunded` |
| Delivery assignment | `order_id`, `rider_user_id` | Rider must be active; reassign uses assignment ID |
| Delivery status | `status`; reason for failed delivery | `assigned`, `picked_up`, `out_for_delivery`, `delivered`, `failed`, `cancelled` |
| COD collection | Assignment ID, positive collected amount, receipt reference, proof reference, idempotency key | Only the assigned rider submits; delivered COD is required |
| Cash remittance | Positive amount, reference, proof reference, idempotency key | Finance reconciliation is a separate admin action |
| Rider profile | Non-negative delivery fee and currency | Default currency PKR |
| Vendor payout | Positive amount, payment reference, idempotency key | Use only reconciled eligible earnings |
| Vendor settlement | Vendor/period/settlement details | Only approved, unsettled vendor items are eligible |
| Ledger journal | Memo and at least two lines with account/debit/credit fields | Each line is debit or credit; totals must balance; use idempotency key |
| Expense | Account, positive amount, currency, status | Cash book or bank account may identify payment source |
| WooCommerce config | Site URL, consumer key, consumer secret | Optional webhook and WordPress media credentials. Product-video diagnostics report plugin detection, WordPress's upload limit, and pending/failed video pushes; secrets are not returned. |
| WhatsApp template | Name, language, body | Name uses `A-Za-z0-9_.-`; body is required |
| WhatsApp message | Recipient phone plus template/body as applicable | Queue/mock foundation only |
| Push subscription | Endpoint, `p256dh`, `auth` | Browser-generated subscription data; do not hand-edit |
| Setting update | JSON object under `value` | Browser editor rejects invalid JSON |
| License activation | License key and plan | Raw key is not stored; hosted service requirements apply |

Responses are typed projections such as `ProductOut`, `OrderOut`,
`DeliveryAssignmentOut`, `VendorOrderItemOut`, `FinanceDashboardOut`,
`LedgerJournalOut`, or `DiagnosticsSummaryOut`; they return identifiers,
statuses, timestamps, scoped business values, and validation errors rather than
passwords or raw secrets.

## 8. Common API error handling

| Code/state | Meaning and safe action |
| --- | --- |
| 400/422 | Invalid field, status, or business rule; correct the payload |
| 401 | Missing/expired/revoked session; sign in again or refresh safely |
| 403 | Permission, role, tenant, or vendor-scope failure; do not bypass it |
| 404 | Record/storefront/route not found; verify identifier and company |
| 409 | Duplicate, conflicting state, idempotency, or locked-period conflict; inspect current record |
| 429 | Authentication/registration/reset throttling; wait and retry later |
| 503 | Operational dependency unavailable, such as SMTP or a production service |

Keep the response's request/correlation ID with the error report. Do not paste
authorization headers, cookies, password-reset links, or secret-bearing
diagnostics into a support or AI conversation.

## 9. Deployment and operations

### Local PC

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\scripts\migrate.ps1
.\scripts\run_pc_local.ps1
```

`RUN_ERP.bat` supports local stack operation; `RUN_ERP_LAN.bat` or `RUN_ERP.bat
lan` exposes the API on the local network. Set `ERP_LAN_IP` only to override
the advertised address. Set `ERP_START_WORKER=0` only when deliberately
running without the background worker.

### Cloud API with Windows desktop

Run FastAPI, PostgreSQL, migrations, and the worker on the server. Configure
the desktop with:

```text
ERP_API_BASE_URL=https://YOURDOMAIN
```

The Windows desktop remains a separate client; PythonAnywhere does not run the
Windows UI inside a browser.

### Production requirements

Production requires PostgreSQL, HTTPS, non-default secrets, explicit trusted
hosts/proxies, protected environment files, `pg_dump`, writable runtime paths,
matching Alembic revision, and a fresh worker heartbeat. Back up PostgreSQL
before migrations and use the production runbook for restore operations.

## 10. Security and data boundaries

Passwords use PBKDF2-SHA256 and are never returned. Access tokens are opaque
and short-lived; refresh tokens rotate and reuse can revoke a token family.
Action tokens for activation/reset are one-time, hashed at rest, and expiring.

Tenant/company filters are mandatory. Vendor self-service endpoints derive the
vendor from the authenticated relationship and do not trust a caller-supplied
vendor ID. Diagnostics redact secrets. Never put passwords, API keys, license
keys, refresh tokens, or raw customer data into logs or AI prompts.
