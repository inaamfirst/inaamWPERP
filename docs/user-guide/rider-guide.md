# Rider Guide

## Rider workspace

Sign in with the assigned workspace slug. The rider home is `/rider`. Rider
navigation is grouped as Overview, Active work, History, and Account.

Rider data is assignment-scoped. A rider can view and update only deliveries
assigned to that account. A rider does not receive company-wide order access.

## Overview — `/rider`

The dashboard displays **My deliveries**, assigned count, picked-up count, out
for delivery count, delivered count, and failed count. **Sales** is not
applicable to the rider view.

Quick destinations:

- **Assigned deliveries** → `/rider/deliveries`
- **Today's deliveries** → `/rider/today`
- **Delivery history** → `/rider/history`
- **Cash & earnings** → `/rider/finance` when `rider.finance.view` is granted
- **Profile & password** → `/change-password`

## Delivery cards

Each card contains order number, delivery status, payment status, order total,
recipient name/phone, and the formatted delivery address. The active delivery
card can show:

- **Mark picked up** when status is `assigned`
- **Mark out for delivery** when status is `picked_up`
- **Mark delivered** when status is `out_for_delivery`
- **Mark failed** for an active delivery

Choose the next normal status in order. Choosing **Mark failed** opens a reason
prompt; a blank or cancelled prompt leaves the delivery unchanged.

The permitted normal flow is:

```text
assigned → picked_up → out_for_delivery → delivered
```

Failed and cancelled deliveries are terminal for the rider card. **Delivery
history** hides status-changing controls and shows terminal records.

## Assigned, today, and history filters

- **Assigned deliveries** shows active/non-terminal assignments.
- **Today's deliveries** shows assignments whose assignment date is today,
  while retaining the active/history distinction used by the page.
- **Delivery history** shows terminal deliveries such as delivered, failed, or
  cancelled.

If the page says **No deliveries found**, refresh or confirm with dispatch that
the delivery was assigned to the correct rider account.

## Cash & earnings — `/rider/finance`

### Submit COD collection

Use **Submit COD collection** only for a delivered COD assignment.

1. Select **Delivered order**.
2. Enter **Cash collected (PKR)**.
3. Enter **Receipt/reference**.
4. Enter **Proof reference or photo link**.
5. Choose **Submit COD**.

The collection remains pending until finance accepts or rejects it. The
expected amount, submitted amount, accepted amount, receipt/reference, and
status appear in **COD collection history**.

### Submit a cash remittance

1. In **Hand in collected cash**, enter **Amount (PKR)**.
2. Enter **Handover reference**.
3. Enter **Proof reference or photo link**.
4. Choose **Submit remittance**.

The remittance remains pending until finance accepts it. Use **Cash remittance
history** to verify amount, reference, proof, and status.

### Read earnings

**Earnings statement** lists date, type, details, amount, and running balance.
**Payout history** lists date, payout number, payment reference, and amount.
Earnings appear after COD is reconciled and delivery/accounting rules make the
entry eligible.

Use **Refresh** after submitting or after finance tells you a reconciliation is
complete.

## Rider safety and troubleshooting

- Keep proof references readable and tied to the correct order/remittance.
- Do not submit the same collection or remittance twice; idempotency prevents
  some duplicates, but verify the history first.
- If a status update fails, report order number, current status, and failure
  reason to dispatch; do not jump to a later status.
- If finance rejects a collection, read the reason or contact the finance/admin
  team before submitting a correction.
- Never share your password, access token, or another rider's customer data.
