"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import type { Delivery } from "@/lib/delivery";
import styles from "@/components/commerce.module.css";

type Summary = Record<string, number>;
type Rider = { id: string; username: string; full_name: string | null; is_active: boolean };
type Unassigned = { id: string; order_number: string; status: string; customer_name: string | null; customer_phone: string | null };

export default function DeliveryDispatchPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [riders, setRiders] = useState<Rider[]>([]);
  const [unassigned, setUnassigned] = useState<Unassigned[]>([]);
  const [assignments, setAssignments] = useState<Delivery[]>([]);
  const [selectedRiders, setSelectedRiders] = useState<Record<string, string>>({});
  const [error, setError] = useState("");

  async function load() {
    try {
      const [nextSummary, nextRiders, nextUnassigned, nextAssignments] = await Promise.all([
        fetchApi("/delivery/admin/summary"), fetchApi("/delivery/admin/riders"),
        fetchApi("/delivery/admin/unassigned"), fetchApi("/delivery/admin/assignments"),
      ]);
      setSummary(nextSummary as Summary);
      setRiders(nextRiders as Rider[]);
      setUnassigned(nextUnassigned as Unassigned[]);
      setAssignments(nextAssignments as Delivery[]);
    } catch {
      setError("Unable to load delivery dispatch data.");
    }
  }

  // This effect synchronizes the view with the remote delivery API.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, []);

  async function assign(orderId: string, assignmentId?: string) {
    const riderId = selectedRiders[assignmentId || orderId];
    if (!riderId) { setError("Select a rider first."); return; }
    try {
      await fetchApi(assignmentId ? `/delivery/admin/assignments/${assignmentId}` : "/delivery/admin/assignments", {
        method: assignmentId ? "PUT" : "POST",
        body: JSON.stringify(assignmentId ? { rider_user_id: riderId } : { order_id: orderId, rider_user_id: riderId }),
      });
      setError("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The delivery assignment could not be saved.");
    }
  }

  const riderOptions = () => <>
    <option value="">Select rider</option>
    {riders.map((rider) => <option key={rider.id} value={rider.id}>{rider.full_name || rider.username}</option>)}
  </>;

  return (
    <>
      <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Admin operations</div><h1 className={styles.pageTitle}>Delivery dispatch</h1><p className={styles.pageSubtitle}>Assign ready orders to riders and monitor delivery progress from one queue.</p></div></div>
      {error && <div className={styles.error}>{error}</div>}
      <div className={styles.metricGrid}>{[["Unassigned", summary?.unassigned_count], ["Assigned", summary?.assigned_count], ["Out for delivery", summary?.out_for_delivery_count], ["Delivered", summary?.delivered_count], ["Failed", summary?.failed_count], ["Active riders", summary?.active_rider_count]].map(([label, value]) => <div className={styles.metricCard} key={label}><div className={styles.metricLabel}>{label}</div><div className={styles.metricValue}>{value ?? "—"}</div></div>)}</div>
      <section className={styles.panel}>
        <div className={styles.toolbar}><h2 className={styles.panelTitle}>Unassigned orders</h2><span className={styles.muted}>{unassigned.length} waiting</span></div>
        {unassigned.length === 0 ? <div className={styles.empty}>No ready orders are waiting for dispatch.</div> : <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Order</th><th>Customer</th><th>Status</th><th>Rider</th><th /></tr></thead><tbody>{unassigned.map((order) => <tr key={order.id}><td>{order.order_number}</td><td>{order.customer_name || "—"}<br /><span className={styles.muted}>{order.customer_phone || "No phone"}</span></td><td><span className={styles.badge}>{order.status}</span></td><td><select value={selectedRiders[order.id] || ""} onChange={(event) => setSelectedRiders((current) => ({ ...current, [order.id]: event.target.value }))}>{riderOptions()}</select></td><td><button className={styles.primaryButton} type="button" onClick={() => assign(order.id)}>Assign</button></td></tr>)}</tbody></table></div>}
      </section>
      <section className={styles.panel}>
        <div className={styles.toolbar}><h2 className={styles.panelTitle}>Assignments</h2><span className={styles.muted}>{assignments.length} total</span></div>
        {assignments.length === 0 ? <div className={styles.empty}>No assignments have been created.</div> : <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Order</th><th>Rider</th><th>Status</th><th>Customer</th><th>Reassign</th></tr></thead><tbody>{assignments.map((assignment) => <tr key={assignment.id}><td>{assignment.order_number}</td><td>{assignment.rider_name || assignment.rider_username || "—"}</td><td><span className={`${styles.badge} ${assignment.status === "delivered" ? styles.badgeSuccess : assignment.status === "failed" ? styles.badgeDanger : styles.badgeWarning}`}>{assignment.status.replaceAll("_", " ")}</span></td><td>{assignment.recipient_name}<br /><span className={styles.muted}>{assignment.city || assignment.address_line1}</span></td><td><select value={selectedRiders[assignment.id] || assignment.rider_user_id} onChange={(event) => setSelectedRiders((current) => ({ ...current, [assignment.id]: event.target.value }))}>{riderOptions()}</select>{!["delivered", "cancelled"].includes(assignment.status) && <button className={styles.secondaryButton} type="button" onClick={() => assign(assignment.order_id, assignment.id)}>Save</button>}</td></tr>)}</tbody></table></div>}
      </section>
    </>
  );
}
