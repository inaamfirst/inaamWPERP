# Web UI architecture

## Product surfaces

The browser experience consists of the Next.js authenticated application and
the server-rendered FastAPI authentication/storefront fallback. Both surfaces
use the same blue, neutral, and semantic color contract.

Canonical workspace homes are `/admin`, `/vendor`, and `/rider`. The root URL
resolves the authenticated user to one of those homes. Legacy `/products` and
`/orders` URLs remain compatibility redirects.

## Canonical roles

| Role | Access contract |
| --- | --- |
| Administrator | Every declared tenant permission. |
| Manager | Catalog, customers, inventory, orders, delivery, and reports. |
| Vendor | Own profile, products, orders, settlements, ledger, stock, and reports. |
| Rider | View and update assigned deliveries only. |
| Custom | The exact union of assigned permissions. |

The backend remains authoritative. The frontend hides actions without a grant,
disables only granted actions that are temporarily unavailable, and shows an
access-denied state for direct navigation within the correct workspace.

## Navigation

Admin navigation is grouped into Overview, Operations, Commerce, Finance, and
Administration. Vendor navigation is grouped into Overview, Selling, Catalog,
Finance, and Help. Rider navigation is grouped into Overview, Active Work,
History, and Account.

- Below 768px: bottom navigation with four role-priority destinations and More.
- 768px to 899px in portrait: top bar and accessible drawer.
- 768px to 1199px in landscape, or 900px and wider: compact navigation rail.
- 1200px and wider: full persistent sidebar.
- 1600px and wider: content expands up to a 1520px maximum canvas.

Short landscape viewports reduce vertical chrome. All fixed navigation observes
safe-area insets.

## Screen inventory

- Authentication: login, password recovery/reset/change, registration,
  activation, session continuation, and logout.
- Admin/Staff: dashboard, orders, products, customers, inventory, delivery,
  vendors, marketplace, accounting, WooCommerce, support, identity, settings,
  and system diagnostics.
- Vendor: overview, POS, products, orders, stock, ledger, reports, and support.
- Rider: overview, assigned deliveries, today, and history.
- Public: marketplace landing, company storefront, and vendor storefront.

## Responsive and accessibility contract

Layouts are mobile-first and content-driven. Operational records become cards
on phones; financial and diagnostic data retain accessible scrollable tables.
Controls are at least 44px, focus is always visible, dialogs and drawers trap and
restore focus, tabs implement keyboard semantics, status changes use live
regions, and motion respects `prefers-reduced-motion`. The target is WCAG 2.2 AA.
