# WooCommerce Sync Setup

This guide connects a WooCommerce store to the ERP desktop app.

## WordPress Setup

1. In WordPress admin, open the WooCommerce REST API key screen.
2. Create a key for the ERP integration user.
3. Set permissions to `Read/Write`.
4. Copy the generated consumer key and consumer secret immediately.

Do not paste WooCommerce secrets into chat, documentation, screenshots, or source
code. Store them only through the ERP desktop WooCommerce screen or a secure
production secret manager.

## ERP Desktop Setup

1. Start the local ERP stack from `RUN_ON_PC_OFFLINE`.
2. Log in to the desktop app.
3. Open `WooCommerce` from the left navigation.
4. Enter the store URL, for example `https://choiceoye.com`.
5. Paste the consumer key and consumer secret.
6. Click `Save Config`.
7. Click `Test Connection`.
8. If the test succeeds, click `Run Sync`.
9. Review `Recent Sync Runs` and `Open Conflicts`.

The Dashboard also provides `Sync Products` and `Sync All Content` actions. The
administrator `Sync Products` action publishes the ERP catalog and then pulls
WooCommerce products back for a two-way product sync. A vendor sees the same
action, but the server makes it publish-only and limits it to that vendor's
products, product media, brands, and categories. Vendor jobs use the existing
`erp_vendor_id` WooCommerce metadata when present and never advance the
company's shared product/order checkpoints.

`Test Connection` validates WooCommerce products, categories, brands,
customers, and orders with small read requests. It does not depend on
WooCommerce `system_status`, because some stores restrict that endpoint even
when catalog/order sync can work.

## Current Sync Behavior

The first successful connector run fully pulls WooCommerce products, customers,
and orders. With WooCommerce 5.8 or later, later product and order pulls request
only records changed within the prior successful checkpoint window. The
standard `wc/v3/customers` endpoint has no supported `modified_after` filter, so
customer pulls always remain full synchronizations. Product and order windows
overlap the previous checkpoint by one second because WooCommerce's date
filters are exclusive. The upper bound is the captured start rounded down to a
whole second, keeping later changes out of the paginated window; the next run
retrieves that deferred second. Duplicate boundary records are safely handled
by the existing mapping/upsert logic. Each page is processed before the next
page is downloaded, and a failed product or order pull keeps its old checkpoint
for a safe retry. The existing outbound product, stock, and order-status queue
continues to run on the default sync mode.

The durable sync endpoint also supports two manual maintenance modes:

- `POST /api/v1/woocommerce/sync?mode=products` publishes the scoped ERP
  product catalog. Administrator jobs then pull the WooCommerce product catalog
  back; vendor jobs remain publish-only.
- `POST /api/v1/woocommerce/sync?mode=full_products` fully imports products and
  ignores the saved product checkpoint for that request.
- `POST /api/v1/woocommerce/sync?mode=reconcile_products` fetches every remote
  product ID and archives mapped ERP products that no longer exist online.

Reconciliation is intentionally separate from normal incremental sync. It does
not delete local products or their historical references and can be scheduled
nightly by calling the reconciliation mode through the existing authenticated
API and worker queue.

Live-store rollout still requires field ownership review, rate-limit tuning,
credential rotation policy, and store-specific acceptance tests before enabling
automatic production sync.

## Troubleshooting

- If `https://your-store.example/wp-json` returns `404`, WordPress permalink or
  rewrite rules are not serving the pretty REST entry point correctly.
- If `https://your-store.example/?rest_route=/` works, the ERP connector can
  usually fall back to query-string REST mode and continue working.
- The recommended production fix is still to repair WordPress permalinks and
  rewrite rules so pretty REST routes work normally.
- WooCommerce API secrets should never be pasted into docs, tickets, chat, or
  screenshots. Save them only in the ERP connector settings or a secure secret
  store.
