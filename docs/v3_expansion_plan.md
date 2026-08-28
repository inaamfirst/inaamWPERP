# V3 Expansion Plan

This is a planning document only. Do not implement these modules until the V1
foundation, production packaging, live connector policies, and commercial
licensing decisions are approved.

## Implementation Order

1. Vendors/marketplace.
2. Purchases and accounting foundations.
3. Delivery/COD.
4. Mobile API.
5. AI assistant.
6. Plugin marketplace.

## Vendors And Marketplace

Purpose: support vendor-owned catalogs, orders, stock visibility, settlements,
and marketplace administration.

Tables: `vendors`, `vendor_users`, `vendor_products`, `vendor_order_items`,
`vendor_settlements`, `vendor_notifications`.

API: vendor onboarding, product assignment, vendor dashboard, order assignment,
settlement summaries, notification preferences.

UI: desktop marketplace administration, vendor portal/mobile views later.

Sync: WooCommerce marketplace plugins such as Dokan/WCFM need external mapping
per vendor and per product. Conflicts must be tenant and vendor scoped.

Security: vendor users must never access another vendor or company. Permissions:
`vendors.view`, `vendors.manage`, `vendors.settle`, `vendors.assign_orders`.

Tests: tenant isolation, vendor isolation, settlement math, assignment rules,
sync mapping, permission boundaries.

Risks: marketplace plugin differences, settlement disputes, data isolation, and
complex reporting.

## Accounting

Purpose: convert sales, purchases, expenses, payments, and settlements into
auditable financial ledgers.

Tables: `accounts`, `journal_entries`, `journal_lines`, `expenses`,
`customer_ledger_entries`, `vendor_ledger_entries`, `tax_rates`, `cash_books`,
`bank_accounts`.

API: chart of accounts, journal posting, cash/bank entries, expense entry,
customer/vendor ledger views, profit reports.

UI: accounting workspace, ledgers, cash book, bank book, expense entry, reports.

Sync: payment and refund events from WooCommerce should create controlled
accounting events, not direct arbitrary journal edits.

Security: separate accounting permissions and audit logs for every posting.
Permissions: `accounting.view`, `accounting.post`, `accounting.reconcile`,
`accounting.reports`.

Tests: double-entry balancing, period locks, tenant isolation, payment/refund
posting, report totals.

Risks: regulatory requirements, tax rules, backdated edits, and migration of
existing customer data.

## Delivery And COD

Purpose: manage dispatch, delivery staff, proof of delivery, COD collection,
returns, and delivery status.

Tables: `delivery_agents`, `delivery_assignments`, `delivery_events`,
`cod_collections`, `delivery_proofs`, `delivery_zones`.

API: assign orders, update delivery status, collect COD, upload proof metadata,
delivery reports.

UI: desktop dispatch board and mobile delivery-agent workflow.

Sync: order status changes may push to WooCommerce after operator-approved
rules. COD collection should post to accounting only after reconciliation.

Security: delivery agents see only assigned orders. Permissions:
`delivery.view`, `delivery.assign`, `delivery.update`, `delivery.reconcile`.

Tests: assignment rules, status transitions, COD totals, proof metadata,
tenant/agent isolation.

Risks: GPS accuracy, offline mobile operation, fraud prevention, and failed
delivery workflows.

## Mobile API

Purpose: expose a controlled API for vendor, delivery, owner dashboard, and
eventual customer-facing mobile apps.

Tables: reuse core tables plus `mobile_devices`, `mobile_sessions`,
`push_subscriptions`.

API: token refresh, device registration, role-specific mobile endpoints,
push-registration endpoints.

UI: mobile apps are separate clients. Desktop remains the main control center.

Sync: mobile offline actions require idempotency keys and outbox processing.

Security: short-lived tokens, device revocation, rate limits, and scoped
permissions. Permissions mirror desktop/API roles.

Tests: token lifecycle, device revocation, offline idempotency, tenant
isolation, rate limits.

Risks: API abuse, stale offline writes, push notification privacy.

## AI Assistant

Purpose: provide premium analytics, report explanation, support drafting, and
operator assistance.

Tables: `ai_conversations`, `ai_messages`, `ai_tool_runs`, `ai_policies`,
`ai_usage_events`.

API: ask business questions, summarize reports, draft customer replies, inspect
order/product context with permission checks.

UI: desktop assistant panel with citations to ERP records and clear human
approval controls.

Sync: AI must read from ERP APIs/services, not bypass tenant permissions. It
must not place customer orders or alter financial data without human approval.

Security: prompt logging policy, PII controls, tenant isolation, tool
allowlists. Permissions: `ai.use`, `ai.admin`, `ai.view_usage`.

Tests: permission filtering, no unauthorized tool calls, human-confirmation
requirements, usage metering.

Risks: hallucinated advice, privacy, cost control, and unsafe automation.

## Plugin Marketplace

Purpose: allow controlled extension modules without modifying core code.

Tables: `plugin_packages`, `plugin_installs`, `plugin_versions`,
`plugin_permissions`, `plugin_events`.

API: list available plugins, install/enable/disable plugins, version checks,
permission review.

UI: admin plugin manager with clear install/upgrade warnings.

Sync: plugins may define connectors, events, migrations, and desktop pages, but
must register through stable module manifests.

Security: signed plugin packages, permission review, migration review, sandboxed
execution policy where practical. Permissions: `plugins.view`,
`plugins.install`, `plugins.manage`.

Tests: manifest validation, dependency resolution, install/rollback behavior,
permission boundaries.

Risks: arbitrary code execution, migration safety, support burden, version
compatibility, and customer trust.
