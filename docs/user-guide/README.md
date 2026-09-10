# Inaam's Ecommerce ERP — User Documentation

This folder is the user, operator, technical, and AI-assistance documentation
pack for the current ERP implementation.

## Start here

| Need | Guide |
| --- | --- |
| Understand the whole system | [Master manual](master-manual.md) |
| Administer the company, users, vendors, finance, and system | [Administrator guide](admin-guide.md) |
| Work as a manager or permission-limited staff member | [Manager/staff guide](manager-staff-guide.md) |
| Manage a vendor business | [Vendor guide](vendor-guide.md) |
| Deliver orders and submit delivery cash | [Rider guide](rider-guide.md) |
| Operate the Windows desktop client | [Desktop guide](desktop-guide.md) |
| Look up API, permissions, modules, deployment, or status rules | [Technical reference](technical-reference.md) |
| Give operating instructions to an AI assistant | [AI reference](ai-reference.md) |

## Documentation contract

- Snapshot date: **2026-09-01**.
- The current source code, module manifests, and API schemas are authoritative
  when older project documents disagree with the current implementation.
- A feature marked **implemented** has code in the repository. It may still be
  disabled by configuration, limited to the API or desktop, or not be suitable
  for production. Those distinctions are called out explicitly.
- Never copy real passwords, access tokens, license keys, customer data, or
  production URLs into examples.
- All displayed currency examples use PKR. Backend money fields ending in
  `_minor` are integer minor units: `12500` means `PKR 125.00`.

## How to read directions

Directions use the visible workspace and navigation labels. For example:

```text
Admin → Operations → Products → Add product
Vendor → Selling → Shop POS → Review sale → Complete sale
Rider → Active work → Assigned deliveries → Mark picked up
```

On a phone, the first four role-priority destinations appear in the bottom
navigation. Use **More** for the remaining destinations. On a narrow tablet,
open the navigation drawer. On larger screens use the compact rail or full
sidebar.

## Coverage

The pack documents the browser application, PySide6 desktop client, public
authentication/storefront pages, exposed API, integrations, operator scripts,
and the feature limitations that matter when using or supporting the ERP.
