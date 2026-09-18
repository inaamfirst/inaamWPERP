"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import styles from "@/components/commerce.module.css";
import {
  VENDOR_ORDER_FILTERS,
  nextVendorOrderStatus,
  vendorOrderCollectionEndpoint,
  vendorOrderStatusEndpoint,
} from "@/lib/vendor-orders";

type VendorOrder = { id: string; order_id: string; order_number?: string; name: string; quantity: number; line_total_minor: number; status: string; order_status?: string; reservation_status?: string; created_at: string };

export default function VendorOrders() {
  const { permissions } = useAuth();
  const canManage = permissions.includes("vendor.orders.manage");
  const [orders, setOrders] = useState<VendorOrder[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetchApi(vendorOrderCollectionEndpoint(filter))
      .then((value) => active && setOrders(value as VendorOrder[]))
      .catch(() => active && setError("Failed to load online orders."))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [filter]);

  async function advance(row: VendorOrder) {
    if (!canManage) return;
    const status = nextVendorOrderStatus(row.status);
    if (!status) return;
    try {
      await fetchApi(vendorOrderStatusEndpoint(row.id), { method: "POST", body: JSON.stringify({ status }) });
      const refreshed = await fetchApi(vendorOrderCollectionEndpoint(filter)) as VendorOrder[];
      setOrders(refreshed);
    } catch {
      setError("This order cannot move to the next stage.");
    }
  }

  return (
    <>
      <div className={styles.pageHeader}>
        <div>
          <div className={styles.eyebrow}>Online store operations</div>
          <h1 className={styles.pageTitle}>Orders &amp; fulfillment</h1>
          <p className={styles.pageSubtitle}>Process online order items through confirmation, packing, RTS, dispatch, and delivery.</p>
        </div>
      </div>
      <div className={styles.toolbar}>
        <div className={styles.filterRow} aria-label="Filter orders by status">
          {VENDOR_ORDER_FILTERS.map((item) => <button key={item} type="button" className={`${styles.workspaceButton} ${filter === item ? styles.workspaceButtonActive : ""}`} onClick={() => { setLoading(true); setFilter(item); }}>{item === "all" ? "All" : item}</button>)}
        </div>
      </div>
      {error && <div className={styles.error} role="alert">{error}</div>}
      <div className={styles.panel}>
        <div className={styles.tableWrap}>
          <table className={`${styles.table} ${styles.mobileCardTable}`}>
            <caption className={styles.srOnly}>Vendor order items</caption>
            <thead><tr><th>Order item</th><th>Product</th><th>Qty</th><th>Value</th><th>Status</th><th>Next action</th></tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={6} className={styles.empty}>Loading orders…</td></tr> : orders.map((row) => <tr key={row.id}>
                <td data-label="Order item"><strong>{row.order_number || row.order_id.slice(0, 8)}</strong><br /><span className={styles.muted}>{new Date(row.created_at).toLocaleDateString()}</span></td>
                <td data-label="Product">{row.name}</td>
                <td data-label="Qty">{row.quantity}</td>
                <td data-label="Value">PKR {(row.line_total_minor / 100).toFixed(2)}</td>
                <td data-label="Status"><span className={`${styles.badge} ${row.status === "delivered" ? styles.badgeSuccess : styles.badgeWarning}`}>{row.status}</span>{row.reservation_status === "stock_issue" && <><br /><span className={styles.inlineError}>Stock check needed</span></>}</td>
                <td data-label="Next action">{canManage && nextVendorOrderStatus(row.status) ? <button type="button" className={styles.primaryButton} onClick={() => void advance(row)}>Move to {nextVendorOrderStatus(row.status)}</button> : <span className={styles.muted}>{canManage ? "No action" : "Read only"}</span>}</td>
              </tr>)}
              {!loading && orders.length === 0 && <tr><td colSpan={6} className={styles.empty}>No order items match this filter.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
