# Module System

Each module is represented by a folder under `erp/packages/modules` and a
`module.json` manifest. The manifest is the contract used by the registry,
desktop shell, API, tests, and future installers.

## Manifest Fields

- `id`: stable module id and folder name.
- `name`: display name.
- `version`: module version.
- `description`: module purpose.
- `status`: `implemented`, `scaffold`, or `disabled`.
- `enabled_by_default`: whether the module is enabled for new installations.
- `dependencies`: required module ids.
- `permissions`: permission keys introduced by the module.
- `api_routes`: routes exposed by implemented module code.
- `migrations`: migration ids owned by the module.
- `desktop_pages`: desktop page ids.
- `events`: event names published or consumed by the module.

## Current Module Status

Implemented: `core`, `identity`, `settings`, `audit`, `catalog`, `customers`,
`inventory`, `orders`, `woocommerce`, `whatsapp`, `reports`, `licensing`, and
`backup`.

Scaffolded: `tenancy`.

The catalog, customers, inventory, orders, and settings manifests now declare
basic desktop page ids. The WooCommerce module is implemented as API/service
foundation only and remains disabled by default. The WhatsApp module is
implemented as queue/template/mock-adapter foundation only and remains disabled
by default. Reports are API foundations with a CSV export for orders. Licensing
is a local mock activation/status foundation, not a production license server.
Backup is a SQLite/dev backup and restore-plan foundation, not production
PostgreSQL restore automation. The desktop shell consumes the backend API
directly; it does not query or mutate the database.

Future work may add install/enable controls, module-specific migrations, event
hooks, and desktop navigation registration.
