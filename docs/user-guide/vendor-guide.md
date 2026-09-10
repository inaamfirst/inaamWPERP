# Vendor Guide

## Vendor workspace

Sign in with the workspace slug and an approved Vendor account. Both the user
account and vendor business must be `active`. The browser opens `/vendor` and
groups navigation as Overview, Selling, Catalog, Finance, and Help.

Vendor users see only their own products, order items, stock, settlements,
ledger, reports, notifications, and support contacts. A paused or stopped
vendor cannot use protected vendor routes; active sessions are revoked when
access is paused or stopped.

## Overview — `/vendor`

Use **Combined**, **Shop / POS**, or **Online Store** under the **Workspace**
selector. The dashboard shows sales, orders, pending fulfilment, low stock,
reserved lines, product count, and channel performance.

Quick links:

- **Open POS** → `/vendor/pos`
- **Manage products** → `/vendor/products`
- **Manage stock** → `/vendor/stock`
- **View orders** → `/vendor/orders`
- **View ledger** → `/vendor/ledger`
- **View reports** → `/vendor/reports`
- **Get support** → `/vendor/support`

The **Browser notifications** panel can show **Enable this browser**, **Send
test**, and **Disable this browser**. The browser must support notifications;
test/disable controls require an existing subscription.

## Products & publishing — `/vendor/products`

### Product list

Choose **New product** to open the editor, **Refresh** to reload products and
listings, or **Edit** on an existing product. The list shows name, SKU, type,
status, listing/publishing state, and product actions.

### Editor tabs and fields

The editor is divided into these tabs:

| Tab | Fields and purpose |
| --- | --- |
| Basic | Name, Slug, SKU, Barcode, Product type, Status, Category, Brand, Description, Short description |
| Pricing | Regular price, Sale price, Sale start, Sale end, Global unique ID |
| Tax | Tax status, Tax class |
| Inventory | Featured, Visibility, Manage stock, Stock quantity, Stock status, Backorders, Sold individually |
| Shipping | Weight, Length, Width, Height, Shipping class |
| Images | Image URL, image name, alt text, sort order, variant association, upload |
| Videos | HTTPS direct-MP4, YouTube, or Vimeo URL; MP4 upload; name and sort order |
| Variants | Variant name, SKU, barcode, price, cost, sale price, attributes, stock, stock status, backorders, dimensions, shipping class, description, image URL, metadata |
| SEO | SEO title, SEO description, reviews allowed, purchase note |
| Advanced | Menu order, tags, upsell IDs, cross-sell IDs, grouped product IDs, attributes, default attributes, custom metadata, metadata |

Use the tab buttons to move between sections. On keyboard, use Arrow keys and
Home/End as supported by the tab control.

### Editor controls

- **Save** or **Save changes** writes the product.
- **Publish** marks the selected product active/published.
- **Save as Draft** marks it draft.
- **Move to Trash** or archive removes it from active use without deleting
  history.
- **Restore** returns a trashed/archived record when supported by the current
  status.
- **Delete Permanently** irreversibly removes the selected product; use only
  after verifying that historical and integration data are not required.
- **Close** hides the editor without a new save.
- **New** clears the editor for a new product.
- **New category** and **New brand** create references through a prompt and
  select the newly created reference.
- **Add image** adds an image URL record.
- **Upload image** uploads one file after the product has been saved.
- **Remove image** removes the selected image from the editor.
- **Add video URL** accepts an HTTPS direct-MP4, YouTube, or Vimeo link.
- **Upload MP4** uploads one video after the product has been saved; the limit is
  100 MB per file and 10 videos per product.
- **Open selected video** opens the link in the system browser.
- **Remove selected video** removes it from the editor; save to apply the change.
- **Add variant** adds a variant row.
- **Remove variant** removes the selected variant from the editor.

Product status choices are **Active / Published**, **Draft**, and **Trash** in
the vendor UI. The backend vendor product status model also tracks submitted,
approved, rejected, published, and archived states when marketplace approval
is enabled.

### Publishing guidance

Save the product before uploading media. When the administrator has configured
the optional ChoiceOye ERP Product Videos WordPress plugin, vendor videos
synchronize to WooCommerce after product images. Otherwise they remain in the
ERP. Use `visible`, `catalog`, `search`, or `hidden` visibility intentionally.
Check stock status and backorder policy before selecting **Publish**. A listing
may be published only after the backend's vendor/marketplace rules accept it.

## Shop POS — `/vendor/pos`

1. Select **Warehouse**.
2. Keep or replace **Customer / walk-in name**.
3. Select **Payment method**: Cash, Bank, Card, or COD.
4. Search products using **Search SKU or name**.
5. Choose **Add** beside a product. Repeated adds increase quantity.
6. Select **Review sale** on a phone, or review the **Current sale** panel on
   desktop width.
7. Use **Remove** to remove one line and **Clear** to empty the cart.
8. Choose **Complete sale**.

The sale creates the backend order/payment and stock operation. Do not press
Complete sale repeatedly if the browser is waiting; verify the result first.

## Online orders — `/vendor/orders`

The status filter buttons are **All**, **pending**, **accepted**, **packing**,
**dispatched**, **delivered**, and **rejected**. Each row shows order item,
product, quantity, value, status, and the next permitted action.

With `vendor.orders.manage`, use **Move to accepted**, **Move to packing**,
**Move to dispatched**, and **Move to delivered** as the status progresses.
There is no next action for delivered or rejected lines. Without the manage
permission, the row says **Read only**.

The vendor transition rule is:

```text
pending → accepted → packing → dispatched → delivered
pending → rejected
```

Do not skip a step or manually change a terminal line through a different URL.

## Stock — `/vendor/stock`

The stock table shows product and warehouse quantities. Choose **Refresh** to
reload it and **Adjust stock** on a row when `vendor.stock.manage` is granted.
The adjustment sheet shows the current quantity and contains:

- **Movement**: Receive stock, Remove stock, or Record damage
- **Quantity**: positive integer, minimum 1
- **Save movement**
- **Close**

Stock movements are appended to history. If a quantity is wrong, record a
correcting movement with a reason rather than editing history.

## Ledger — `/vendor/ledger`

Choose **Refresh** to reload data and **Export CSV** to download the visible
order-level sales rows. The export includes order, product, quantity, sale,
commission, payable, payment status, and finance status.

Panels:

- **Order-level sales** — sale amount, commission, vendor payable, payment,
  finance approval.
- **Settlement history** — settlement number, status, approved amount, paid
  amount, payment reference, and paid date.
- **Ledger history** — date, entry type, details, amount, and running balance.

The ledger is vendor-payable only; it does not expose company revenue, other
vendors, company expenses, audit data, or unrelated customer PII. Posted
entries are immutable; refunds/corrections appear as reversals.

## Reports — `/vendor/reports`

The sales report shows the rows that feed the dashboard and settlements. Use it
to compare order item, quantity, line total, commission, payable amount,
payment status, finance status, and dates with the Ledger page.

The backend also exposes vendor stock and settlement reports. These may be
available to integrations or the desktop even when the browser page only shows
the current sales report.

## Support — `/vendor/support`

Support contacts are maintained by the administrator. Choose **Chat on
WhatsApp** under a contact to open the generated WhatsApp URL in a new tab or
window. The contact may include role, phone, working hours, and a default
message.

## Vendor troubleshooting

| Problem | Action |
| --- | --- |
| Login rejected | Confirm workspace slug and that both account/vendor status are active |
| Product action missing | Ask for `vendor.products.manage` or check that the marketplace module is enabled |
| Stock action missing | Ask for `vendor.stock.manage` |
| Order says Read only | Ask for `vendor.orders.manage`; do not attempt a direct API mutation |
| Sale cannot complete | Check warehouse, cart, stock, payment method, and network result before retrying |
| Payout not visible | Sale must be delivered, payment-reconciled, finance-approved, and included in settlement |
| WhatsApp link absent | Ask the administrator to add an active support contact |
