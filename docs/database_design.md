# Database Design

PostgreSQL is the production database. SQLAlchemy is the ORM layer and Alembic
owns schema migrations. SQLite is allowed for offline cache and automated
migration smoke tests.

## Platform Foundation Tables

The Phase 1 migrations create platform tables for tenancy, identity, settings,
audit, sync foundations, and licensing:

- `companies`
- `users`
- `roles`
- `permissions`
- `role_permissions`
- `user_roles`
- `auth_sessions`
- `settings`
- `audit_logs`
- `external_resource_map`
- `sync_outbox`
- `sync_inbox_logs`
- `sync_conflicts`
- `sync_run_logs`
- `licenses`

These tables support tenant separation, RBAC, audit logging, settings, sync,
and licensing without committing to advanced business workflows.

## Catalog And Customer Foundation

The V1 catalog/customer slice adds tenant-scoped business foundation tables:

- `categories`
- `brands`
- `products`
- `product_variants`
- `product_images`
- `customers`
- `customer_addresses`
- `customer_notes`
- `customer_tags`

Catalog and customer deletes are soft deletes: products and customers move to
`archived`, while categories and brands are marked inactive. This preserves
auditability and keeps future orders, inventory, and sync mappings stable.

Every table has a non-null `company_id` foreign key. API services always filter
reads and writes by the authenticated user's company.

Products support simple and variable product types, SKU/barcode fields, SEO
metadata, product images, and variant attributes. Stock is intentionally not
stored on products.

Customers support profile data, addresses, notes, tags, and credit limit fields.
Accounting ledgers, receivables, and order history remain future modules.

## Inventory Foundation

The V1 inventory slice adds:

- `warehouses`
- `stock_movements`

Inventory is derived by summing `stock_movements.quantity_delta` by company,
warehouse, product, and variant. There is no editable stock balance column on
products or variants. This keeps future order, purchase, return, and sync logic
auditable.

Supported V1 movement types are `opening`, `stock_in`, `stock_out`, `damaged`,
and `adjustment`. Negative stock is blocked by the service layer. Transfers are
not a full workflow yet, but `transfer_group_id` exists so a future transfer can
record paired source/destination movement rows.

## Orders Foundation

The V1 orders slice adds:

- `orders`
- `order_items`
- `order_status_history`
- `payments`

Orders are tenant scoped and reference existing customers, products, and
variants. Order items store name, SKU, unit price, and line-total snapshots so
historic orders do not change when catalog records are edited later.

Supported statuses are `pending`, `confirmed`, `packing`, `ready`,
`dispatched`, `delivered`, `returned`, `cancelled`, and `refunded`. Status
changes are written to `order_status_history`.

Payments are recorded against orders and update `paid_minor` plus
`payment_status`. This is not full accounting; ledgers, receivables, refunds,
and settlement workflows remain future modules.

V1 orders do not automatically reserve or deduct inventory. Stock remains an
explicit inventory movement until order fulfillment rules, backorder policy, and
returns policy are defined and tested.

## WhatsApp Notification Foundation

The V1 WhatsApp slice adds:

- `notification_templates`
- `notification_queue`
- `notification_delivery_logs`

The ERP stores templates and queues rendered WhatsApp messages. Delivery is
logged separately so future adapters can report success/failure without
rewriting the original queued message. The current implementation uses a mock
local adapter only; it does not automate real WhatsApp sending.

## Sync, Backup, And Licensing Foundation

The WooCommerce foundation uses the platform sync tables:

- `external_resource_map`
- `sync_outbox`
- `sync_inbox_logs`
- `sync_conflicts`
- `sync_run_logs`

These tables support idempotent mapping, webhook deduplication, retryable
outbox records, conflict tracking, and sync run diagnostics. The current
connector is a foundation implementation; production ownership rules,
rate-limit handling, and operator conflict UI still need hardening.

The backup foundation does not add a database table in V1. SQLite/dev backups
write a database copy plus JSON metadata to `runtime_data/backups` and record an
audit log entry. Production PostgreSQL backup/restore is handled by operator-run
`pg_dump`/`pg_restore` scripts and the production runbook.

Licensing uses `licenses`. V1 stores local mock activation state and an
HMAC-hashed license key only; raw submitted license keys are never persisted.

## Future Business Tables

Future migrations will add vendors, accounting, delivery, and reporting tables.

Business tables should include company scoping, audit-friendly timestamps, and
stable external mapping support where sync is required.
