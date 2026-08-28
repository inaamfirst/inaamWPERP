"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Order = { id: string; order_number: string; status: string; payment_status: string; total_minor: number; created_at: string; notes: string | null };
const statuses = ["pending", "confirmed", "processing", "ready", "dispatched", "delivered", "cancelled", "returned", "refunded"];

export default function AdminOrders() {
  const { permissions } = useAuth();
  const canChangeStatus = permissions.includes("orders.change_status");
  const [orders, setOrders] = useState<Order[]>([]);
  const [selected, setSelected] = useState<Order | null>(null);
  const [status, setStatus] = useState("");
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    try { setOrders(await fetchApi("/orders") as Order[]); setError(""); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Orders could not be loaded."); }
    finally { setLoading(false); }
  }
  // Synchronize the view with the remote order API.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, []);

  function openOrder(order: Order) { setSelected(order); setStatus(order.status); setReason(""); }

  async function changeStatus() {
    if (!canChangeStatus || !selected || !status) return;
    setSaving(true); setError("");
    try {
      const updated = await fetchApi(`/orders/${selected.id}/status`, { method: "POST", body: JSON.stringify({ status, reason: reason || null }) }) as Order;
      setOrders((current) => current.map((order) => order.id === updated.id ? updated : order));
      setSelected(updated); setStatus(updated.status); setReason("");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Order status could not be changed."); }
    finally { setSaving(false); }
  }

  return (
    <>
      <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Order operations</div><h1 className={styles.pageTitle}>Orders</h1><p className={styles.pageSubtitle}>Review order totals and follow the controlled fulfillment workflow.</p></div><button type="button" className={styles.secondaryButton} onClick={() => void load()}>Refresh</button></div>
      {error && <div className={styles.error} role="alert">{error}</div>}
      <div className={styles.formGrid}>
        <section className={styles.panel}>
          <div className={styles.toolbar}><h2 className={styles.panelTitle}>Sales orders</h2><span className={styles.muted}>{orders.length} total</span></div>
          {loading ? <div className={styles.empty} role="status">Loading orders…</div> : (
            <div className={styles.tableWrap}><table className={styles.table}><caption className={styles.srOnly}>Sales orders</caption><thead><tr><th>Order</th><th>Total</th><th>Payment</th><th>Status</th><th>Date</th></tr></thead><tbody>{orders.map((order) => <tr key={order.id}><td><button type="button" className={styles.linkButton} onClick={() => openOrder(order)}>{order.order_number}</button></td><td>PKR {(order.total_minor / 100).toFixed(2)}</td><td>{order.payment_status}</td><td><span className={styles.badge}>{order.status.replaceAll("_", " ")}</span></td><td>{new Date(order.created_at).toLocaleDateString()}</td></tr>)}{orders.length === 0 && <tr><td colSpan={5} className={styles.empty}>No orders found.</td></tr>}</tbody></table></div>
          )}
        </section>

        {selected && <section className={styles.panel}>
          <div className={styles.toolbar}><h2 className={styles.panelTitle}>Order {selected.order_number}</h2><button type="button" className={styles.secondaryButton} onClick={() => setSelected(null)}>Close</button></div>
          <p className={styles.muted}>Current status: {selected.status}. Changes are recorded in the order status history.</p>
          {canChangeStatus ? <>
            <label className={styles.field}>New status<select value={status} onChange={(event) => setStatus(event.target.value)}>{statuses.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
            <label className={styles.field}>Reason<textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={5000} placeholder="Optional operational note" /></label>
            <div className={styles.formActions}><button type="button" className={styles.primaryButton} disabled={saving || status === selected.status} title={status === selected.status ? "Choose a different status first" : undefined} onClick={() => void changeStatus()}>{saving ? "Saving…" : "Save status"}</button></div>
          </> : <div className={styles.notice}>This account has read-only order access.</div>}
        </section>}
      </div>
    </>
  );
}
