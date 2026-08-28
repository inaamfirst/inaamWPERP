# Offline-First Architecture

The Windows desktop app must continue to support selected local operations
during internet outage. Offline-first does not mean every workflow is safe
offline.

## Direction

- The API remains the authoritative local/server boundary.
- SQLite is used for local cache and local outbox.
- The desktop must show clear warnings when API or internet connectivity is
  unavailable.
- Offline work must be queued with idempotency keys and synced later.
- Conflicts must be recorded and shown to the user.

## Phase 1 Status

V1 implements an offline warning in the desktop shell and database foundations
for outbox, inbox/webhook logs, sync run logs, external resource mapping, and
conflict handling. The WooCommerce connector can enqueue and process foundation
outbox records while online.

V1 does not yet implement offline business CRUD workflows. Desktop product,
customer, inventory, order, backup, and licensing operations still require the
local API to be reachable.
