# Sync Architecture

Sync is designed around idempotency, queues, mapping tables, retries, logs, and
conflict visibility.

## Phase 1 Foundation

- `external_resource_map`: links ERP records to WooCommerce, WhatsApp, or future
  external systems.
- `sync_outbox`: stores outbound work with idempotency keys and retry state.
- `sync_inbox_logs`: records inbound webhooks or external events.
- `sync_conflicts`: stores unresolved ownership or data conflicts.
- `sync_run_logs`: records sync run status and summary statistics.

## WooCommerce Connector Foundation

The V1 connector foundation provides encrypted storage for the WooCommerce site
URL, consumer key, and consumer secret in the existing settings table. API
responses return only the site URL and a short consumer-key hint; the secret is
never returned.

The foundation exposes:

- `PUT /api/v1/woocommerce/config`
- `GET /api/v1/woocommerce/config`
- `POST /api/v1/woocommerce/test-connection`
- `POST /api/v1/woocommerce/sync`
- `GET /api/v1/woocommerce/sync-runs`
- `GET /api/v1/woocommerce/conflicts`
- `POST /api/v1/woocommerce/conflicts/{conflict_id}/resolve`
- `POST /api/v1/woocommerce/webhooks`

The desktop exposes a `WooCommerce` page for saving credentials, testing the
connection, running manual sync, reviewing recent tenant-scoped sync runs, and
viewing open conflicts.

Connection tests make small read requests against WooCommerce products,
categories, brands, customers, and orders with the stored credentials. They do
not depend on WooCommerce `system_status`, because some stores restrict that
endpoint even when catalog and order sync can work. Automated tests mock HTTP
success, authentication failure, network failure, and bad URL validation. No
test requires a live WooCommerce store.

Helper functions now exist for:

- Mapping WooCommerce product, customer, and order ids through
  `external_resource_map`.
- Enqueueing idempotent outbound work into `sync_outbox`.
- Pulling products, customers, and orders from WooCommerce.
- Pushing product, stock, and order-status changes from `sync_outbox`.
- Recording webhook deliveries in `sync_inbox_logs` to prevent duplicate
  processing.
- Recording tenant-scoped sync runs and conflicts.

Dashboard sync jobs are also vendor-scoped. Administrator jobs retain the
company-wide active key and checkpoints. Vendor jobs store their vendor scope
in the durable run stats, use a separate active key, filter inbound products by
the existing `erp_vendor_id` metadata or local ownership mapping, and process
only that vendor's product/media/stock outbox records.

Inbound product and order pulls are incremental after their first successful
run. WooCommerce 5.8 or later is required because that release added the
`modified_after` and `modified_before` collection filters used by those
endpoints. The connector stores `last_products_sync` and `last_orders_sync` in
the existing company-scoped WooCommerce settings value, records the UTC start
time before page 1, and uses the previous checkpoint and captured start time as
a bounded UTC window. WooCommerce applies both date bounds exclusively and
stores modification times at whole-second precision. The lower bound overlaps
the previous checkpoint by one second, while the upper bound is the captured
start rounded down to a whole second. This keeps records modified after the run
starts out of its offset-paginated result set. The deferred current second is
retrieved by the next run's lower overlap; boundary records can be imported
twice, and the existing mapping/upsert logic makes those duplicates safe. Pages
are processed and committed individually.
The new checkpoint is saved only after all pages for that resource succeed, so
a retry after failure reuses the prior checkpoint. Checkpoint updates lock and
refresh the settings row before merging so unrelated connector values are
preserved.

The standard WooCommerce `wc/v3/customers` collection does not support
`modified_after`. Customer pulls therefore remain full synchronizations and do
not store or advertise an incremental checkpoint. A successful customer pull
removes the legacy `last_customers_sync` key written by earlier versions; it
does not remove any other WooCommerce setting. This intentionally avoids local
post-filtering, which could miss changed customer records.

Deletion detection is a separate `reconcile_products` mode. It requests only
WooCommerce product IDs with `_fields=id`, never uses `modified_after`, and
archives mapped local products whose remote IDs are absent. It does not delete
products, invoices, or historical references. The `products` mode publishes
local brands, categories, products, and media before an administrator pulls the
WooCommerce product catalog back; vendor jobs are publish-only and vendor
scoped. The `full_products` mode remains a manual full product import without
`modified_after`. The default `incremental` mode retains the existing
two-way `sync_outbox` flow and now publishes local taxonomy terms before queued
product updates.

The current connector is still a foundation implementation. Live-store rollout
requires field ownership review, rate-limit tuning, credential rotation,
operator conflict UI, and customer-specific acceptance tests.

## Ownership Policy

V1 must explicitly define field ownership before implementing WooCommerce sync.
Recommended default:

- ERP owns stock, internal order workflow, audit, and local operational status.
- WooCommerce owns online checkout, online payment event intake, and storefront
  customer entry until imported.
- Conflicting updates become visible conflicts rather than silent overwrites.

## WhatsApp Adapter Strategy

Phase 0 and Prompt 6 discovery found the existing WhatsApp automation under
`C:\Users\User\Documents\Whatsapp Fro` and reusable runtime/dashboard patterns
in `Mobile shop software/Inaam Warehouse`. The safe integration boundary is:

- ERP owns notification templates, queue rows, delivery logs, permissions, and
  audit.
- A future local adapter may communicate with the existing WhatsApp dashboard or
  runtime folder.
- The ERP must not import the old automation code directly, store `.wwebjs_auth`
  data, or automate live sending without explicit approval.
- Tests use the mock-local adapter only.

Current API surface:

- `POST /api/v1/whatsapp/templates`
- `GET /api/v1/whatsapp/templates`
- `POST /api/v1/whatsapp/messages`
- `GET /api/v1/whatsapp/messages`
- `POST /api/v1/whatsapp/messages/{message_id}/mock-send`
- `GET /api/v1/whatsapp/messages/{message_id}/delivery-logs`

WhatsApp integration must remain adapter-based. The ERP queues messages and
records status. The existing local WhatsApp automation remains an external
sender.
