"use client";

import { FormEvent, useEffect, useState } from "react";
import { ApiError, fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Supplier = { id: string; name: string; contact_name?: string | null; phone?: string | null; email?: string | null };
type Summary = { purchase_total_minor: number; supplier_payable_minor: number; cash_in_minor: number; cash_out_minor: number; currency: string };
const money = (value: number, currency = "PKR") => `${currency} ${(value / 100).toFixed(2)}`;

export default function VendorShopPage() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [name, setName] = useState("");
  const [contact, setContact] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = async () => {
    try {
      const [supplierRows, accounting] = await Promise.all([
        fetchApi("/commerce/vendor/shop/suppliers"),
        fetchApi("/commerce/vendor/shop/accounting"),
      ]);
      setSuppliers(supplierRows as Supplier[]);
      setSummary(accounting as Summary);
    } catch (caught) {
      setError(caught instanceof ApiError ? String(caught.data.detail || caught.message) : "Shop data could not be loaded.");
    }
  };
  useEffect(() => { void load(); }, []);

  async function addSupplier(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) return;
    setError("");
    try {
      await fetchApi("/commerce/vendor/shop/suppliers", { method: "POST", body: JSON.stringify({ name: name.trim(), contact_name: contact.trim() || null }) });
      setName(""); setContact(""); setMessage("Supplier added."); await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? String(caught.data.detail || caught.message) : "Supplier could not be added.");
    }
  }

  return <>
    <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Shop / POS</div><h1 className={styles.pageTitle}>Purchasing &amp; cash</h1><p className={styles.pageSubtitle}>Manage companies you buy from and track your local shop cash position.</p></div></div>
    {message && <div className={styles.notice}>{message}</div>}{error && <div className={styles.error}>{error}</div>}
    <div className={styles.metricGrid}>
      <div className={styles.metricCard}><span className={styles.metricLabel}>Purchases received</span><strong className={styles.metricValue}>{money(summary?.purchase_total_minor || 0, summary?.currency)}</strong></div>
      <div className={styles.metricCard}><span className={styles.metricLabel}>Supplier payable</span><strong className={styles.metricValue}>{money(summary?.supplier_payable_minor || 0, summary?.currency)}</strong></div>
      <div className={styles.metricCard}><span className={styles.metricLabel}>Cash in</span><strong className={styles.metricValue}>{money(summary?.cash_in_minor || 0, summary?.currency)}</strong></div>
      <div className={styles.metricCard}><span className={styles.metricLabel}>Cash out</span><strong className={styles.metricValue}>{money(summary?.cash_out_minor || 0, summary?.currency)}</strong></div>
    </div>
    <div className={styles.formGrid}>
      <section className={styles.panel}><h2 className={styles.panelTitle}>Add supplier</h2><form className={styles.formGrid} onSubmit={addSupplier}><label className={styles.field}>Company name<input value={name} onChange={(event) => setName(event.target.value)} required /></label><label className={styles.field}>Contact name<input value={contact} onChange={(event) => setContact(event.target.value)} /></label><div className={styles.formActions}><button className={styles.primaryButton} type="submit">Save supplier</button></div></form></section>
      <section className={styles.panel}><div className={styles.toolbar}><h2 className={styles.panelTitle}>Suppliers</h2><button className={styles.secondaryButton} type="button" onClick={() => void load()}>Refresh</button></div><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Company</th><th>Contact</th><th>Phone</th></tr></thead><tbody>{suppliers.map((supplier) => <tr key={supplier.id}><td>{supplier.name}</td><td>{supplier.contact_name || supplier.email || "—"}</td><td>{supplier.phone || "—"}</td></tr>)}{!suppliers.length && <tr><td colSpan={3} className={styles.empty}>No suppliers yet.</td></tr>}</tbody></table></div></section>
    </div>
  </>;
}