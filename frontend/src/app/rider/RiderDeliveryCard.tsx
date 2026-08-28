"use client";

import { deliveryAddress, type Delivery, nextDeliveryStatus } from "@/lib/delivery";
import styles from "@/components/commerce.module.css";

type Props = {
  delivery: Delivery;
  onStatusChange?: (delivery: Delivery, status: string) => void;
};

export default function RiderDeliveryCard({ delivery, onStatusChange }: Props) {
  const nextStatus = nextDeliveryStatus[delivery.status];
  return (
    <article className={styles.panel}>
      <div className={styles.toolbar}>
        <div>
          <h3 className={styles.panelTitle}>{delivery.order_number}</h3>
          <p className={styles.muted}>{delivery.recipient_name} · {delivery.recipient_phone || "No phone"}</p>
        </div>
        <span className={`${styles.badge} ${delivery.status === "delivered" ? styles.badgeSuccess : delivery.status === "failed" ? styles.badgeDanger : styles.badgeWarning}`}>
          {delivery.status.replaceAll("_", " ")}
        </span>
      </div>
      <p className={styles.muted}>{deliveryAddress(delivery)}</p>
      <p className={styles.muted}>Payment: {delivery.payment_status} · Total: PKR {(delivery.order_total_minor / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}</p>
      {delivery.failure_reason && <div className={styles.error}>{delivery.failure_reason}</div>}
      {nextStatus && onStatusChange && (
        <div className={styles.formActions}>
          <button className={styles.primaryButton} type="button" onClick={() => onStatusChange(delivery, nextStatus)}>
            Mark {nextStatus.replaceAll("_", " ")}
          </button>
          <button className={styles.dangerButton} type="button" onClick={() => onStatusChange(delivery, "failed")}>
            Mark failed
          </button>
        </div>
      )}
    </article>
  );
}
