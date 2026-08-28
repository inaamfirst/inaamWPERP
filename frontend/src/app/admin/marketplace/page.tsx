"use client";

import { useEffect, useState, type FormEvent } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Vendor = { id: string; name: string; slug: string; contact_name: string | null; email: string | null; phone: string | null; status: string; default_commission_bps: number };

export default function AdminMarketplace() {
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [form, setForm] = useState({ name: "", contact_name: "", email: "", phone: "", default_commission_bps: "500" });
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try { setVendors(await fetchApi("/marketplace/vendors") as Vendor[]); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Vendors could not be loaded."); }
    finally { setLoading(false); }
  }
  // This effect synchronizes the view with the remote marketplace API.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, []);

  async function createVendor(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setMessage("");
    try { await fetchApi("/marketplace/vendors", { method: "POST", body: JSON.stringify({ name: form.name.trim(), contact_name: form.contact_name.trim() || null, email: form.email.trim() || null, phone: form.phone.trim() || null, default_commission_bps: Number.parseInt(form.default_commission_bps, 10) || 0, status: "pending" }) }); setForm({ name: "", contact_name: "", email: "", phone: "", default_commission_bps: "500" }); setMessage("Vendor created and awaiting approval."); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Vendor could not be created."); }
  }

  async function changeStatus(vendor: Vendor, action: "approve" | "pause" | "reactivate" | "stop") {
    setError("");
    try { const updated = await fetchApi(`/marketplace/vendors/${vendor.id}/${action}`, { method: "POST", body: JSON.stringify({ reason: `Admin ${action}` }) }) as Vendor; setVendors((current) => current.map((item) => item.id === updated.id ? updated : item)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Vendor status could not be changed."); }
  }

  return <>
    <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Marketplace administration</div><h1 className={styles.pageTitle}>Marketplace</h1><p className={styles.pageSubtitle}>Onboard vendors, review approval state, and manage vendor operational access.</p></div><button type="button" className={styles.secondaryButton} onClick={() => void load()}>Refresh</button></div>
    {error && <div className={styles.error}>{error}</div>}{message && <div className={styles.notice}>{message}</div>}
    <div className={styles.formGrid}><form className={styles.panel} onSubmit={createVendor}><h2 className={styles.panelTitle}>Onboard vendor</h2><label className={styles.field}>Business name<input required minLength={2} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label className={styles.field}>Contact name<input value={form.contact_name} onChange={(event) => setForm({ ...form, contact_name: event.target.value })} /></label><label className={styles.field}>Email<input type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></label><label className={styles.field}>Phone<input value={form.phone} onChange={(event) => setForm({ ...form, phone: event.target.value })} /></label><label className={styles.field}>Commission (BPS)<input type="number" min="0" max="10000" value={form.default_commission_bps} onChange={(event) => setForm({ ...form, default_commission_bps: event.target.value })} /></label><div className={styles.formActions}><button type="submit" className={styles.primaryButton}>Create vendor</button></div></form><section className={styles.panel}><div className={styles.toolbar}><h2 className={styles.panelTitle}>Vendor accounts</h2><span className={styles.muted}>{loading ? "Loading…" : `${vendors.length} vendors`}</span></div><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Vendor</th><th>Contact</th><th>Commission</th><th>Status</th><th>Actions</th></tr></thead><tbody>{vendors.map((vendor) => <tr key={vendor.id}><td><strong>{vendor.name}</strong><br /><span className={styles.muted}>{vendor.slug}</span></td><td>{vendor.email || vendor.phone || vendor.contact_name || "—"}</td><td>{(vendor.default_commission_bps / 100).toFixed(2)}%</td><td><span className={`${styles.badge} ${vendor.status === "active" ? styles.badgeSuccess : styles.badgeWarning}`}>{vendor.status}</span></td><td><div className={styles.toolbarActions}>{vendor.status === "pending" && <button type="button" className={styles.primaryButton} onClick={() => void changeStatus(vendor, "approve")}>Approve</button>}{vendor.status === "active" && <button type="button" className={styles.secondaryButton} onClick={() => void changeStatus(vendor, "pause")}>Pause</button>}{vendor.status === "paused" && <button type="button" className={styles.primaryButton} onClick={() => void changeStatus(vendor, "reactivate")}>Reactivate</button>}{vendor.status !== "stopped" && vendor.status !== "active" && <button type="button" className={styles.dangerButton} onClick={() => void changeStatus(vendor, "stop")}>Stop</button>}</div></td></tr>)}{!loading && vendors.length === 0 && <tr><td colSpan={5} className={styles.empty}>No vendors found.</td></tr>}</tbody></table></div></section></div>
  </>;
}
