"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Vendor = { id: string; name: string; contact_name?: string | null; email?: string | null; phone?: string | null; status: string; default_commission_bps: number };

export default function AdminVendors() {
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { fetchApi("/marketplace/vendors").then((value) => setVendors(value as Vendor[])).catch(() => setError("Vendors could not be loaded.")); }, []);
  async function changeStatus(vendor: Vendor, action: string) { try { await fetchApi(`/marketplace/vendors/${vendor.id}/${action}`, { method: "POST", body: JSON.stringify({ reason: `Admin ${action}` }) }); setVendors((current) => current.map((item) => item.id === vendor.id ? { ...item, status: action === "approve" || action === "reactivate" ? "active" : action === "pause" ? "paused" : "stopped" } : item)); } catch { setError("Vendor status could not be changed."); } }
  return <><div className={styles.pageHeader}><div><div className={styles.eyebrow}>Marketplace administration</div><h1 className={styles.pageTitle}>Vendor control</h1><p className={styles.pageSubtitle}>Approve vendors, pause operations, and review commission configuration from the admin workspace.</p></div></div>{error && <div className={styles.error}>{error}</div>}<div className={styles.panel}><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Vendor</th><th>Contact</th><th>Status</th><th>Commission</th><th>Actions</th></tr></thead><tbody>{vendors.map((vendor) => <tr key={vendor.id}><td><strong>{vendor.name}</strong><br /><span className={styles.muted}>{vendor.contact_name || "No contact name"}</span></td><td>{vendor.email || vendor.phone || "—"}</td><td><span className={`${styles.badge} ${vendor.status === "active" ? styles.badgeSuccess : styles.badgeWarning}`}>{vendor.status}</span></td><td>{(vendor.default_commission_bps / 100).toFixed(2)}%</td><td><div className={styles.toolbarActions}>{vendor.status === "pending" && <button type="button" className={styles.primaryButton} onClick={() => changeStatus(vendor, "approve")}>Approve</button>}{vendor.status === "active" && <button type="button" className={styles.secondaryButton} onClick={() => changeStatus(vendor, "pause")}>Pause</button>}{vendor.status === "paused" && <button type="button" className={styles.primaryButton} onClick={() => changeStatus(vendor, "reactivate")}>Reactivate</button>}</div></td></tr>)}{vendors.length === 0 && <tr><td colSpan={5} className={styles.empty}>No vendors found.</td></tr>}</tbody></table></div></div></>;
}
