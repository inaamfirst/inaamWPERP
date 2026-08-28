# Authentication, vendor portal, inventory, and ledger

This release adds an additive production authentication lifecycle and a new
authoritative double-entry ledger. Existing accounting, marketplace, product,
order, and stock tables remain available as compatibility projections.

## Access states

User account state and vendor business state are independent. Both must be
`active` for a vendor user to open protected vendor routes.

| State | User account meaning | Vendor business meaning | Protected access |
|---|---|---|---|
| `pending` | Registration awaits approval | Business awaits approval | None |
| `active` | Login is allowed | Vendor is approved | Allowed by role and tenant scope |
| `paused` | Temporarily disabled account | Temporarily suspended business | None; active sessions are revoked |
| `stopped` | Terminated account | Terminated business relationship | None; active sessions are revoked |

Legacy vendor values are migrated as `approved` to `active`, `suspended` to
`paused`, and `rejected` to `stopped`. API input accepts those aliases during
the compatibility window but output uses canonical values.

Public registrations use `/register` or `POST /api/v1/auth/register/vendor`.
They create a Vendor role, a pending user, a pending vendor, and a tenant-bound
`VendorUser` link in one transaction. Administrator-created vendor accounts are
active immediately. They use either a one-time activation link or a temporary
password that must be changed before protected features can be used.

## Sessions and password lifecycle

- Passwords use the existing PBKDF2-SHA256 implementation and are never returned
  by an API or rendered in the UI.
- Access tokens are short-lived opaque tokens. Refresh tokens rotate on every
  use and are grouped into token families.
- Reusing a rotated refresh token revokes the full family and every access
  session issued from it.
- API logout revokes the active access session and associated refresh family.
  Desktop logout also removes the refresh token from the OS credential vault.
- "Remember me" changes only refresh-token lifetime. It never stores a password.
- Activation and password-reset links are one-time, hashed at rest, expiring
  tokens. Production public delivery requires SMTP configuration.
- Login throttling stores a keyed digest of login scope and blocks repeated
  failures. Audit logs record success, failure, rotation, reuse, reset, status,
  and logout events without recording passwords or tokens.
- The bootstrap administrator is still created only by first-use setup. That
  setup also seeds administrator permissions and the default chart of accounts.
- The final active administrator cannot be paused, stopped, disabled, or have
  the Administrator role removed. Create another active administrator first.

The desktop depends on the `keyring` package and fails closed if a platform
credential vault is unavailable. There is no plaintext file fallback.

## Tenant and vendor isolation

Every administrator ledger query includes `company_id`. Every vendor self-route
resolves `vendor_id` from the authenticated `VendorUser` relationship and does
not accept a caller-supplied vendor ID. Vendor ledger responses expose only the
vendor-payable dimension; counterpart company revenue, expenses, margins, other
vendors, audit data, and customer PII are not returned.

## Authoritative ledger

New financial events post immutable rows to:

- `ledger_accounts`;
- `ledger_periods`;
- `ledger_journals`;
- `ledger_lines`.

Every posted journal has at least two lines, exactly one debit or credit per
line, equal debit and credit totals, a stable source, and a tenant-unique
idempotency key. Posted lines cannot be edited. Corrections create a linked
reversal journal. Locked and closed periods reject postings; closed periods
cannot be reopened through the API.

Payment, settlement, paid expense, manual journal, and valued company-owned
inventory events post to the new ledger. The transaction then updates legacy
`journal_entries`, `journal_lines`, and `vendor_ledger_entries` projections where
needed. Reconciliation reports detect missing payment/settlement/expense
postings, duplicate source postings, settlement mismatches, vendor-payable
drift, compatibility-journal drift, and inventory projection drift.

The vendor-payables report applies FIFO settlement allocation and exposes
current, 31-60 day, 61-90 day, and over-90-day aging buckets. Ledger journals,
vendor orders, settlements, stock movements, reports, and CSV exports support
bounded tenant-scoped filters. The desktop provides the same date, status,
vendor, account, and source filters where applicable.

Inventory ownership changes payment treatment:

- `vendor_owned` and `consignment`: vendor payable and commission revenue are
  recognized from vendor order-line values;
- `company_owned`: company sales revenue is recognized and an applicable vendor
  commission is recorded as commission expense and vendor payable.

Refund integrations must call the journal reversal service; they must not edit
an original payment journal.

## Vendor inventory

`vendor_inventory_movements` is append-only and is the inventory history.
`vendor_inventory_balances` is a transactionally updated, rebuildable
projection scoped by company, vendor, product, variant, and warehouse.

Administrators can post opening balances, receipts, sales, reservations,
releases, returns, adjustments, damage, transfers, and count corrections.
Vendors have read-only access. Negative on-hand or available quantities are
rejected unless `ERP_ALLOW_NEGATIVE_VENDOR_STOCK` is explicitly enabled.
PostgreSQL balance updates use row locks; SQLite serializes the small local
transaction and remains supported for offline/single-machine operation.

Historical vendor stock is deliberately not fabricated because legacy stock
movements have no vendor dimension. Administrators must post reviewed opening
balances.

## Deployment procedure

1. Back up PostgreSQL or SQLite and verify that the backup can be restored.
2. Configure a production secret, HTTPS, trusted hosts/proxies, SMTP, and the
   worker using the production runbook.
3. Run `alembic upgrade head`. Revision `202607010014` imports legacy accounts,
   periods, journals, lines, and orphan vendor subledger history.
4. Run the ledger reconciliation endpoint and resolve every error before
   enabling payment/settlement writes.
5. Post reviewed vendor opening inventory balances. Do not infer them from
   company stock.
6. Enable desktop vendor and ledger screens, then monitor audit logs and
   reconciliation warnings during the compatibility window.
7. Retire direct legacy accounting writes only after all external integrations
   post through the authoritative service.

Public pages are `/login`, `/register`, `/forgot-password`, `/activate`,
`/reset-password`, and `/account`. State-changing web forms use SameSite
cookies and CSRF tokens; production cookies are Secure when HTTPS enforcement
is enabled.

The desktop vendor workspace contains Overview, Stock, Stock Movements,
Products, Orders/Sales, Financial Ledger, Settlements, Reports, Linked Users,
and Audit tabs. Vendor users receive the same workspace in read-only mode with
company-private tabs and mutation controls hidden. The administrator ledger
workspace contains Overview, Chart of Accounts, Journals, Trial Balance,
Profit/Loss, Balance Sheet, Cash Flow, Vendor Payables/Aging, Inventory, and
Reconciliation views plus permission-controlled CSV export.
