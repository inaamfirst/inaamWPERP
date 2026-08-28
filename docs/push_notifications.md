# Browser Push Notifications

The web workspace supports opt-in browser notifications for administrators,
staff with order permissions, and vendor users. Notifications are delivered
through the durable ERP worker and use standard Web Push with VAPID keys.

## Production configuration

Set these values in the protected production environment file:

```text
ERP_PUSH_ENABLED=true
ERP_PUSH_VAPID_PUBLIC_KEY=...
ERP_PUSH_VAPID_PRIVATE_KEY=...
ERP_PUSH_VAPID_SUBJECT=mailto:operations@example.com
ERP_PUSH_TTL_SECONDS=300
ERP_PUSH_MAX_ATTEMPTS=5
ERP_PUSH_POLL_SECONDS=5
ERP_WORKER_LOOP=true
```

The public and private VAPID keys must be a matching pair. Keep the private key
out of source control. Production also requires the existing public HTTPS
configuration because browsers reject push subscriptions on insecure origins
(localhost is permitted for development).

## User setup

After login, eligible users see an opt-in prompt. The browser permission dialog
must be accepted from a user gesture. Users can later manage the current
browser subscription from Admin Settings or the Vendor workspace dashboard and
can send a test notification from the same panel.

## Delivery behavior

Order creation/import, order status changes, payments, vendor-item status
changes, delivery assignment changes, and delivery status changes are written
to the push outbox in the same database transaction as the business change.
The worker retries transient provider failures and disables subscriptions that
return HTTP 404 or 410. Payloads contain order operational data only; customer
addresses, phone numbers, and full order details are not sent to the browser
lock screen.

For mixed-vendor orders, company administrators receive the company-scoped
notification and each vendor receives only the event for its own order items.
