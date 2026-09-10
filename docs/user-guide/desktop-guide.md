# Windows Desktop Guide

## Desktop application

The PySide6 desktop client is an API-backed Windows control center. It is not
the browser UI embedded in a window. It uses the configured API base URL and a
secure operating-system keyring for refresh-token storage; it has no plaintext
credential fallback.

## Sign in and session controls

The login page contains:

- **Login ID**
- **Password**
- **Workspace**
- **Remember me**
- **Sign in**
- **Forgot password**
- **Register as a vendor**

After sign-in, the root application contains the session status and **Logout**.
If a temporary account requires a password change, use **Current password**,
**New password**, **Confirm password**, **Change password**, or **Logout**.

Remember me changes refresh-token lifetime only; it never stores a password.

## Top-level navigation

The desktop sidebar contains:

1. Dashboard
2. Products
3. Customers
4. Inventory
5. Orders
6. WooCommerce
7. Marketplace
8. Accounting
9. Settings
10. Admin

Items are hidden according to the authenticated permissions. Vendor sessions
may instead load the vendor self-service data inside Marketplace and related
tabs.

## Dashboard

Controls:

- **Refresh Dashboard** — reload summary counts
- **Sync Products** — request product synchronization when WooCommerce is
  configured
- **Sync All Content** — request broader content synchronization

The summary includes products, customers, revenue, sales, pending orders, and
low stock. Vendor sessions receive the vendor-scoped dashboard instead of
company-wide totals.

## Products

The product screen contains search, status filtering, sort field/order, bulk
action controls, and product editor controls.

### Product list controls

- **Search products** — filter by product text
- Status and sort selectors
- Bulk action selector and **Apply**
- **Save menu order**
- **New**
- **Refresh Products**
- **Clear**
- **Trash**

### Product editor tabs

The tabs are **Basic**, **Pricing**, **Inventory**, **Shipping**, **Images**,
**Videos**, **Variants**, **SEO**, and **Advanced**.

### Product editor buttons

- **Save**
- **Move to Trash**
- **Delete Permanently**
- **Publish**
- **Save as Draft**
- **Restore**
- **Add Image URL**
- **Upload Image**
- **Remove Selected Image**
- **Add Video URL**
- **Upload MP4**
- **Open Selected Video**
- **Remove Selected Video**
- **Add Variant**
- **Remove Selected Variant**

Fields cover product identity, type (`simple`/`variable`), status, category,
brand, description, prices, tax, stock, backorders, dimensions, shipping
class, image URLs, product videos, variant JSON/attributes, SEO, purchase note, tags,
cross-sells/upsells/grouped products, and metadata. Save the product before
uploading an image or video. Videos allow HTTPS direct-MP4, YouTube, and Vimeo
links, or a local MP4 upload up to 100 MB. A product can have up to 10 videos.
Videos open in the system browser. With the optional ChoiceOye ERP Product
Videos WordPress plugin installed, they synchronize to WooCommerce after the
product images; otherwise they remain available only in the ERP.

## Customers

Controls:

- **Create Customer** — creates a customer from name, phone, and email
- **Refresh Customers** — reloads the list

Customer source and lifecycle details are richer in the browser Admin page.

## Inventory

**Refresh Stock** reloads stock rows. The desktop inventory screen is a compact
control view; use the browser Admin or vendor Stock page for the richer
warehouse/movement workflows.

## Orders

**Refresh Orders** reloads order rows. Browser Admin provides the controlled
status editor and reason field. Desktop order controls are intentionally more
limited than the browser operations workspace.

## WooCommerce

Connection fields:

- Site URL
- Consumer key
- Consumer secret
- Webhook secret
- WordPress username
- WordPress application password

Buttons:

- **Save Config**
- **Test Connection**
- **Run Sync**
- **Refresh WooCommerce**

Review the recent sync runs and open conflicts. Credentials are protected and
not re-displayed. A configured worker is required to process queued work. Test
Connection also reports the optional product-video plugin and WordPress upload
limit. Local MP4 video uploads need the WordPress username and application
password; the effective limit is the lower of 100 MB and WordPress's limit.

## Marketplace

The desktop Marketplace screen supports both administrator and vendor views.

### Administrator controls

- Vendor form: name, slug, legal name, contact, email, phone, status, username,
  temporary password, onboarding method, and commission BPS
- **Create Vendor**
- **Refresh Marketplace**
- **Edit Vendor**
- **Reset User Password**
- **Approve**, **Pause**, **Reactivate**, **Stop**
- **Apply Selected Vendor Status**
- **Apply Vendor Filters**
- **Previous Page**, **Next Page**

Vendor detail tabs are **Overview**, **Stock**, **Stock Movements**, **Products**,
**Orders / Sales**, **Financial Ledger**, **Settlements**, **Reports**,
**Linked Users**, and **Audit**.

### Vendor controls

- **Add My Product**
- **Update Selected Product Price**
- **Adjust Selected Stock**
- **Update Selected Order Item**

Vendor status choices and order-item transitions remain backend-controlled.

## Accounting and ledger

The desktop Accounting area has:

- **Refresh Accounting**
- Create Account: code, name, type, parent, active state
- Create Cash Book: code, name, currency, opening balance
- Create Bank Account: code, bank name, account name, account number, IBAN,
  currency, opening balance
- Export controls in the ledger workspace

Ledger tabs:

1. Overview
2. Chart of Accounts
3. Journals
4. Trial Balance
5. Profit & Loss
6. Balance Sheet
7. Cash Flow
8. Vendor Payables
9. Inventory
10. Reconciliation

Use date, vendor, account, source, and journal-status filters where available;
choose **Apply Ledger Filters** and **Export Journals CSV**.

Posted journals cannot be edited. Use a reversal with a reason for correction.

## Settings and Admin

**Refresh API Status** shows health/module status. The Admin page includes:

- **Refresh Admin**
- **Update Company**
- **Create User**
- **Apply Account Status and Roles**
- **Reset Password**
- **Create Role**
- **Activate License**
- **Validate License**
- **Revoke License**

The desktop Admin view covers companies, users, roles, license state, and
diagnostic information. Use the browser Identity page for the more accessible
pending-registration and permission-editor workflow.

## Desktop operation rules

- Errors appear in the page message and global status area.
- Long API operations use background tasks and disable their controls while
  running.
- A lost session clears the local UI session and requires sign-in again.
- Never disable the OS keyring or place credentials in a text file.
- In cloud mode, configure `ERP_API_BASE_URL` and verify the API health URL
  before diagnosing individual screens.
