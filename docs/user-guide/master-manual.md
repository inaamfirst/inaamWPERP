# Complete ERP Master Manual

## 1. What this ERP does

Inaam's Ecommerce ERP is a tenant/company-scoped commerce system for catalog,
customers, inventory, orders, vendors, delivery, operational finance, and
store integrations. It has two user interfaces:

1. The browser application at the configured frontend URL.
2. The Windows PySide6 desktop control center, which talks to the FastAPI
   backend and never connects directly to the database.

The authenticated browser application resolves `/` to the correct workspace:

| Role | Browser home | Main purpose |
| --- | --- | --- |
| Administrator | `/admin` | All company administration and operational control |
| Manager or custom staff | `/admin` | Permission-filtered operations |
| Vendor | `/vendor` | Own catalog, selling, stock, orders, and financial view |
| Rider | `/rider` | Assigned deliveries and rider finance |

The backend is authoritative. A missing menu item normally means the user does
not have that permission, the module is disabled, or the capability is not
implemented in the browser UI.

## 2. First-time orientation

### Sign in

1. Open the ERP login page, normally `/login`.
2. Enter the **Workspace Slug**. This is the company/workspace identifier,
   such as `platform`, `staging`, or the slug supplied by the administrator.
3. Enter **Username or Email**.
4. Enter **Password**.
5. Select **Sign In**.
6. The system sends the user to the canonical workspace allowed by the role
   and permissions.

The login page also links to **Forgot password?** (`/forgot-password`) and
**Request an account** (`/register`). Repeated failed logins may be throttled.

### Required password change

Temporary or administrator-created accounts may be sent to `/change-password`
before any workspace opens. Enter **Current password**, **New password**, and
**Confirm new password**, then choose **Save password**. New passwords must be
at least eight characters and both new-password fields must match.

### Complete authentication and account lifecycle

- **Sign in** (`/login`) uses **Workspace Slug**, **Username or Email**, and
  **Password**. Choose **Sign In**. The page links to **Forgot password?** and
  **Request an account**. A valid session is redirected to `/`; the root then
  opens the role's canonical workspace. A pending, paused, stopped, or
  throttled account receives a safe error message.
- **Request an account** (`/register`) has **Vendor** and **Staff** tabs. The
  Vendor form asks for **Business name**, **Contact name**, **Email**, **Phone
  (optional)**, **Username**, **Password**, and **Confirm password**. The Staff
  form uses **Full name**, **Email**, **Username**, **Password**, and **Confirm
  password**. Choose **Request vendor account** or **Request staff account**.
  The current Next.js page submits to the `staging` workspace; confirm the
  deployment's intended workspace before using it. **Already have an account?
  Sign in** returns to login. After submission, **Return to sign in** and
  **Submit another request** are available. The request stays pending until an
  administrator approves it and assigns roles.
- **Forgot password?** (`/forgot-password`) asks for **Workspace slug** and
  **Login ID or email**. Choose **Send reset link**. **Back to sign in** and
  **Request an account** are the available links. The success response is
  intentionally generic so it does not reveal whether an account exists.
- **Reset password** (`/reset-password?token=...`) asks for **New password**
  and **Confirm new password**. Choose **Reset password**. **Back to sign in**
  and **Request another link** remain available. An absent or expired token is
  rejected; a successful reset returns a message directing the user to sign
  in.
- **Activate account** (`/activate?token=...`) is the server-rendered activation
  flow. Set **New password**, then choose **Activate account**. The success
  page links to **sign in**; invalid or expired tokens cannot be reused.
- **Continue session** is the server-rendered fallback at `/account` when the
  short-lived access cookie expires but a refresh cookie remains. Choose
  **Continue securely**, or choose **Sign out instead**. `/logout` first shows
  **Sign out** and **Cancel**, then revokes the session and returns to `/login`.
- The authenticated browser layout exposes the current user area and
  **Profile and password** (`/change-password`), plus **Sign out**. Logging
  out clears local session state even if server revocation cannot be confirmed.

### Public marketplace and storefronts

The server-rendered public fallback exposes `/marketplace`,
`/store/<workspace-slug>`, and
`/store/<workspace-slug>/vendors/<vendor-slug>`. The marketplace landing page
directs the visitor to a company storefront. A company storefront lists active
products whose visibility is not `hidden`, shows price in PKR, and provides
**Sold by <vendor>** links for active vendors. A vendor storefront lists that
vendor's active visible products and provides **Back to <company>**. These
pages are catalog displays only; checkout, cart, and customer ordering are not
implemented in this public fallback.

An unknown/inactive workspace or vendor returns not found. The server fallback
root `/` redirects to `/marketplace`; the Next.js authenticated root instead
redirects to `/login`, `/change-password`, or the user's canonical workspace.
The compatibility routes `/products`, `/products/new`, and `/orders` redirect
to `/admin/products`, `/admin/products/new`, and `/admin/orders` respectively.

### Global navigation

The desktop browser layout contains the company/application name, workspace
navigation, the current user area, and **Sign out**. The current user area links
to **Profile and password** (`/change-password`).

Navigation changes by viewport:

| Viewport | Location |
| --- | --- |
| Under 768px | Four priority links plus **More** in bottom navigation |
| 768–899px portrait | Top bar and accessible navigation drawer |
| 768–1199px landscape, or 900px+ | Compact navigation rail |
| 1200px+ | Persistent full sidebar |

Use **Open navigation**, **Close navigation**, or **More** as displayed. A
keyboard user can use the skip link **Skip to main content** and visible focus
states. Dialogs can be closed with **Cancel**, their close button, or the
standard keyboard dialog behavior.

Global controls:

| Control | What it does |
| --- | --- |
| **Refresh** | Reloads the current page's data from the backend |
| **Close** | Closes the selected record/editor/sheet without saving new changes |
| **Cancel** | Leaves a new/edit form without submitting it |
| **Sign out** | Revokes the active session and returns to login |
| **Dismiss notification** | Removes a toast message only |
| **Return to your workspace** | Leaves an access-denied page for the user's canonical home |
| **Confirm / Cancel** in a dialog | Completes or abandons a destructive action |

## 3. Role and permission behavior

### Administrator

An Administrator is seeded with all declared tenant permissions and normally
sees every Admin destination. The last active Administrator cannot be paused,
stopped, disabled, or stripped of the Administrator role.

### Manager

The default Manager role has catalog, customers, inventory, orders, delivery,
and reports permissions. It does not automatically have accounting, identity,
vendor administration, settings, or system permissions.

### Vendor

The Vendor role is restricted to the vendor's own profile and company-scoped
records. Vendor self-service permissions cover products, orders, settlements,
ledger, stock, and reports. Vendor records are resolved from the authenticated
vendor relationship; a vendor cannot select another vendor by changing a URL
parameter.

### Rider

The Rider role sees only assigned deliveries and, when granted, rider finance.
Riders cannot browse company orders or other riders' assignments.

### Custom staff

Custom staff receive the union of permissions assigned to their roles. The
browser hides navigation without a grant, but the backend still enforces every
permission. A direct URL can therefore show **You don't have access to this
page** even when the user manually entered the address.

## 4. Browser screen map

### Admin workspace

| Navigation group | Screen | URL | Main controls |
| --- | --- | --- | --- |
| Overview | Overview | `/admin` | Workspace selector, quick links, summary metrics, attention panels, channel performance |
| Operations | Orders | `/admin/orders` | Refresh, order-number link/button, Close, status selector, Reason, Save status |
| Operations | Products & catalog | `/admin/products` | Add product, Refresh, Edit, Close, Save changes, Archive |
| Operations | Add product | `/admin/products/new` | Create product, Cancel |
| Operations | Customers | `/admin/customers` | Add customer, Refresh, Edit, New, Save customer, Archive |
| Operations | Inventory | `/admin/inventory` | Refresh, Add warehouse, Record movement |
| Operations | Delivery dispatch | `/admin/delivery` | Rider selectors, Assign, Reassign Save |
| Commerce | Vendors | `/admin/vendors` | Vendor status controls: Approve, Pause, Reactivate |
| Commerce | Marketplace | `/admin/marketplace` | Create vendor, Refresh, Approve, Pause, Reactivate, Stop |
| Commerce | WooCommerce | `/admin/woocommerce` | Save configuration, Test connection, Queue sync, Refresh data |
| Finance | Accounting | `/admin/accounting` | Date filters, Clear dates, Apply period, metric jump buttons, Accept, Reject, Fee, Adjust, Payout, Create account |
| Administration | Support contacts | `/admin/support` | Add support contact |
| Administration | Users & Roles | `/admin/identity` | Add Vendor User, Add Staff User, Refresh, Users/Roles tabs, Edit, Activate, Pause, Approve, Reject, Save Role |
| Administration | Settings | `/admin/settings` | Refresh, setting-key editor, Close, Save setting, browser notification controls |
| Administration | System diagnostics | `/admin/system` | Refresh, health/module/diagnostic views |

### Vendor workspace

| Navigation group | Screen | URL | Main controls |
| --- | --- | --- | --- |
| Overview | Overview | `/vendor` | Workspace selector, quick links, summary, browser notifications |
| Selling | Shop POS | `/vendor/pos` | Warehouse, customer name, payment method, product search, Add, Review sale, Remove, Close, Complete sale, Clear |
| Selling | Online orders | `/vendor/orders` | Status filters, Move to next status |
| Catalog | Products & publishing | `/vendor/products` | Add product, Refresh, Edit, Publish/Unpublish, editor tabs, save, category/brand creation, image/variant controls, permanent deletion |
| Catalog | Stock | `/vendor/stock` | Refresh, Adjust stock, movement selector, quantity, Save movement, Close |
| Finance | Ledger | `/vendor/ledger` | Refresh, Export CSV, sales/settlement/ledger tables |
| Finance | Reports | `/vendor/reports` | Sales report table and report data |
| Help | Support | `/vendor/support` | Dynamic **Chat on WhatsApp** links |

### Rider workspace

| Navigation group | Screen | URL | Main controls |
| --- | --- | --- | --- |
| Overview | Overview | `/rider` | My deliveries view, delivery metrics, progress |
| Active work | Assigned deliveries | `/rider/deliveries` | Delivery cards, Mark picked up, Mark out for delivery, Mark delivered, Mark failed |
| Active work | Today's deliveries | `/rider/today` | Same cards filtered to today's assignments |
| History | Delivery history | `/rider/history` | Terminal delivery history; status controls are not shown |
| Account | Cash & earnings | `/rider/finance` | Refresh, Submit COD, Submit remittance, finance tables |

## 5. Daily operating workflows

### Product lifecycle

1. Go to **Admin → Operations → Products → Add product** or **Vendor →
   Catalog → Products & publishing → Add product**.
2. Enter a name. The slug is generated from the name when left blank.
3. Enter optional SKU and barcode.
4. Choose product type: `simple`, `variable`, `digital`, or `service` in the
   full vendor editor; the short Admin form exposes the type supported there.
5. Enter a non-negative PKR price and choose `active` or `draft`.
6. Choose **Create product** or **Save**.
7. In the vendor editor, complete Basic, Pricing, Tax, Inventory, Shipping,
   Images, Videos, Variants, SEO, and Advanced information as needed. Videos may
   be HTTPS direct-MP4, YouTube, or Vimeo links, or uploaded MP4 files up to
   100 MB. With the optional ChoiceOye ERP Product Videos plugin they sync to
   WooCommerce after product images; otherwise they remain in the ERP.
8. Choose **Publish** only after price, stock, visibility, and images are
   correct. Choose **Save as draft** when the record is not ready.

Archiving removes a product from active sales channels while preserving
historical records. **Delete permanently** is destructive and should only be
used when the operator has verified that no historical or integration data is
needed.

### Inventory

1. Go to **Admin → Operations → Inventory**.
2. Create a warehouse with a unique alphanumeric/underscore/hyphen **Code**,
   **Name**, and optional **Address**.
3. Select a warehouse and product in the stock-movement form.
4. Enter a non-zero integer quantity change and a reason.
5. Select **Record movement**. The movement is auditable and the stock view is
   refreshed.

Vendors use **Vendor → Catalog → Stock → Adjust stock**. The movement choices
are **Receive stock**, **Remove stock**, and **Record damage**. A quantity of at
least one is required. Stock records are company/warehouse/product scoped.

### Customer management

1. Go to **Admin → Operations → Customers**.
2. Choose **Add customer**.
3. Enter required **Full name** and optional **Email** and **Phone**.
4. Choose **Source**: Manual, POS, WooCommerce, or Legacy.
5. Choose **Save customer**.
6. Select **Edit** to change contact/status information.
7. Choose **Archive**, review the confirmation, then choose **Archive
   customer**. Existing order history is retained.

### Order review and fulfilment

1. Go to **Admin → Operations → Orders**.
2. Select the order number to open its editor.
3. Review total, payment status, current status, and the status history.
4. Choose a different **New status** and optionally enter a **Reason**.
5. Select **Save status**.

The general order statuses are `pending`, `confirmed`, `processing`, `ready`,
`dispatched`, `delivered`, `cancelled`, `returned`, and `refunded`. Every
change is added to status history. A vendor sees only vendor order items and
uses the narrower flow `pending → accepted → packing → dispatched → delivered`
or `pending → rejected`.

### POS sale

1. Go to **Vendor → Selling → Shop POS**.
2. Select a **Warehouse**.
3. Leave **Customer / walk-in name** as `Walk-in Customer` or enter a name.
4. Select **Payment method**: Cash, Bank, Card, or COD.
5. Search by SKU or name.
6. Choose **Add** beside each product. Repeating a product increases its cart
   quantity.
7. Choose **Review sale** on a small screen, or review **Current sale** on the
   right side of a wide screen.
8. Use **Remove** for an item or **Clear** for the whole cart.
9. Choose **Complete sale**. A paid POS payment and stock reservation/sale are
   sent to the backend.

Do not retry blindly after a network timeout: check the order/sale result first
to avoid creating a duplicate transaction. The API supports idempotency for
the underlying commerce operation.

### Delivery and COD

1. Admin opens **Admin → Operations → Delivery dispatch**.
2. In **Unassigned orders**, select a rider and choose **Assign**.
3. For an existing non-terminal assignment, select another rider and choose
   **Save** under **Reassign**.
4. The rider opens **Rider → Active work → Assigned deliveries**.
5. On each card choose the next status in order: **Mark picked up**, **Mark out
   for delivery**, then **Mark delivered**.
6. For a failed delivery, choose **Mark failed** and enter a failure reason in
   the prompt. Cancelling the prompt leaves the delivery unchanged.
7. For a delivered COD order, go to **Rider → Account → Cash & earnings**.
8. In **Submit COD collection**, select the delivered order, enter cash
   collected, receipt/reference, and a proof reference or photo link. Choose
   **Submit COD**.
9. In **Hand in collected cash**, enter amount, handover reference, and proof;
   choose **Submit remittance**.
10. Admin reviews **Accounting → COD awaiting reconciliation** and **Rider
    cash remittances**, then selects **Accept** or **Reject**.

### Vendor finance

Vendor sales become eligible only after successful delivery, accepted payment,
and finance review. The admin goes to **Admin → Finance → Accounting**:

1. Review **Vendor sales awaiting approval**.
2. Choose **Approve** or **Reject** for each line.
3. After approval, choose **Create vendor payout batch** for the vendor.
4. Review vendor sales, settlements, and ledger history in the vendor or admin
   views.

Vendor users use **Vendor → Finance → Ledger** to see sale value, commission,
payable amount, finance status, settlement status, payment reference, and
immutable ledger entries. Corrections and refunds appear as reversals rather
than edits to posted entries.

## 6. Finance and accounting concepts

The accounting screen shows collected sales, approved vendor cost, rider
delivery cost, business expenses, refunds, and net operational profit. The
chart of accounts supports asset, liability, equity, income, expense, and
contra account types in the authoritative ledger API.

Posted journals are double-entry and immutable. A posted journal must have at
least two lines with balanced debit and credit totals. Locked or closed periods
reject new postings. A correction is a linked reversal journal.

The desktop exposes the fuller ledger control center: Overview, Chart of
Accounts, Journals, Trial Balance, Profit & Loss, Balance Sheet, Cash Flow,
Vendor Payables, Inventory, and Reconciliation.

## 7. Integrations and operations

### WooCommerce

Go to **Admin → Commerce → WooCommerce**. Enter Site URL, Consumer key,
Consumer secret, optional Webhook secret, WordPress username, and optional
Application password. Choose **Save configuration**, then **Test connection**.
Choose **Queue sync** for an incremental worker job. Review **Sync runs** and
**Open conflicts**. Credentials are not displayed after saving.

The connector is implemented as a tested foundation, but it is disabled by
default and live-store certification, rate-limit handling, and full conflict
operations require deployment approval. The worker must be running for queued
sync work to complete.

### WhatsApp support

Vendor support contacts are configured by an admin at **Admin →
Administration → Support contacts**. Vendors use **Chat on WhatsApp**, which
opens a dynamic `whatsapp_url` in a new tab/window. WhatsApp message/template
routes exist as a mock/queue foundation; this repository is not evidence of a
live WhatsApp provider integration.

### Notifications

In **Admin → Administration → Settings**, or on the vendor overview, the
**Browser notifications** panel provides **Enable this browser**, **Send test**,
and **Disable this browser**. Browser support and permission are required.

### Health and diagnostics

Go to **Admin → Administration → System diagnostics** and choose **Refresh**.
Review API status, database readiness, version, module count, current and
expected migration revisions, module release status, and redacted diagnostics.
The diagnostics view intentionally does not reveal secrets.

## 8. Backup, licensing, and deployment boundaries

The API has SQLite/development backup and restore-plan capabilities. Production
backup and restore use PostgreSQL `pg_dump`/`pg_restore` runbooks and require a
maintenance window and explicit restore confirmation.

Licensing supports activation, validation, revocation, signed offline-grace
artifacts, and tenant-scoped status as a product foundation. The in-repository
license server uses in-memory storage for deterministic tests and is not a
complete production licensing service without durable hosting, TLS,
authentication, monitoring, backups, and key rotation.

Supported deployment directions are:

- Local PC: API, desktop, and optional worker on one Windows PC.
- Cloud API: FastAPI/PostgreSQL/worker hosted remotely while the desktop points
  to `ERP_API_BASE_URL=https://YOURDOMAIN`.
- PythonAnywhere/API hosting: API and worker on the host; the Windows desktop
  remains a separate client.

Production requires PostgreSQL, HTTPS, protected environment configuration,
trusted hosts/proxies, migrations at the package head, PostgreSQL backup
tools, writable runtime directories, and a fresh worker heartbeat.

## 9. Troubleshooting quick map

| Symptom | Check |
| --- | --- |
| User returns to login | Session expired/revoked, workspace slug incorrect, or account is not active |
| Vendor cannot sign in | Both user account and vendor business must be `active` |
| Menu item is missing | Required permission is absent or the module is disabled |
| Direct URL shows access denied | Backend/frontend permission policy correctly rejected the route |
| WooCommerce Queue sync is disabled | Save a valid configuration first and ensure the worker is running |
| No COD finance action appears | Delivery must be delivered and rider must submit a collection/remittance |
| Vendor payout is unavailable | Sale must be delivered, payment reconciled, and finance-approved |
| Stock update fails | Choose a warehouse/product, use a non-zero valid quantity, and check stock rules |
| Password reset gives a generic response | This is intentional to avoid revealing whether an account exists; check SMTP with an admin |
| Desktop cannot retain a session | A secure operating-system keyring is required; there is no plaintext fallback |

For exact permissions, API routes, status values, module flags, and operator
commands, use the [technical reference](technical-reference.md). For AI-safe
operating instructions, use the [AI reference](ai-reference.md).
