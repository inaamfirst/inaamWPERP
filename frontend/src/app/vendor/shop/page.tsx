"use client";

import { FormEvent, useEffect, useState } from "react";
import { ApiError, fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Supplier = { id: string; name: string; contact_name?: string | null; phone?: string | null; email?: string | null };
type ChannelSummary = { sales_count: number; units_sold: number; sales_minor: number; paid_minor: number; payment_methods: Record<string, number>; vendor_payable_minor?: number };
type Summary = {
  purchase_total_minor: number;
  supplier_payable_minor: number;
  cash_in_minor: number;
  cash_out_minor: number;
  currency: string;
  shop?: ChannelSummary;
  online?: ChannelSummary;
  shared_inventory?: { purchase_total_minor: number; supplier_payable_minor: number; cash_out_minor: number };
};

const money = (value: number, currency = "PKR") => `${currency} ${(value / 100).toFixed(2)}`;

function ChannelMetrics({ title, description, link, linkLabel, summary, currency, payable }: {
  title: string; description: string; link: string; linkLabel: string; summary?: ChannelSummary; currency: string; payable?: boolean;
}) {
  return <section className={styles.panel}>
    <div className={styles.toolbar}>
      <div><h2 className={styles.panelTitle}>{title}</h2><p className={styles.muted}>{description}</p></div>
      <a className={styles.secondaryButton} href={link}>{linkLabel}</a>
    </div>
    <div className={styles.metricGrid}>
      <div className={styles.metricCard}><span className={styles.metricLabel}>Sales</span><strong className={styles.metricValue}>{money(summary?.sales_minor || 0, currency)}</strong></div>
      <div className={styles.metricCard}><span className={styles.metricLabel}>{payable ? "Orders" : "Bills"}</span><strong className={styles.metricValue}>{summary?.sales_count || 0}</strong></div>
      <div className={styles.metricCard}><span className={styles.metricLabel}>Units sold</span><strong className={styles.metricValue}>{summary?.units_sold || 0}</strong></div>
      <div className={styles.metricCard}><span className={styles.metricLabel}>{payable ? "Vendor payable" : "Payments received"}</span><strong className={styles.metricValue}>{money(payable ? summary?.vendor_payable_minor || 0 : summary?.paid_minor || 0, currency)}</strong></div>
    </div>
  </section>;
}

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

  const currency = summary?.currency || "PKR";
  const shared = summary?.shared_inventory;
  return <>
    <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Shop / POS</div><h1 className={styles.pageTitle}>Sales, stock &amp; cash</h1><p className={styles.pageSubtitle}>Shop sales and Online Store orders are shown separately. The same Vendor Shop stock is used by both.</p></div></div>
    {message && <div className={styles.notice}>{message}</div>}{error && <div className={styles.error}>{error}</div>}
    <ChannelMetrics title="Shop / POS sales" description="Walk-in sales and printable bills only." link="/vendor/pos/history#sales" linkLabel="Open sales and bills" summary={summary?.shop} currency={currency} />
    <ChannelMetrics title="Online Store sales" description="WooCommerce orders and fulfillment only." link="/vendor/orders" linkLabel="Open online orders" summary={summary?.online} currency={currency} payable />
    <section className={styles.panel}><h2 className={styles.panelTitle}>Shared inventory purchases</h2><p className={styles.muted}>Purchased stock is shared by Shop/POS and the Online Store.</p><div className={styles.metricGrid}>
      <div className={styles.metricCard}><span className={styles.metricLabel}>Purchases received</span><strong className={styles.metricValue}>{money(shared?.purchase_total_minor ?? summary?.purchase_total_minor ?? 0, currency)}</strong></div>
      <div className={styles.metricCard}><span className={styles.metricLabel}>Supplier payable</span><strong className={styles.metricValue}>{money(shared?.supplier_payable_minor ?? summary?.supplier_payable_minor ?? 0, currency)}</strong></div>
      <div className={styles.metricCard}><span className={styles.metricLabel}>Cash out</span><strong className={styles.metricValue}>{money(shared?.cash_out_minor ?? summary?.cash_out_minor ?? 0, currency)}</strong></div>
      <div className={styles.metricCard}><span className={styles.metricLabel}>Cash in</span><strong className={styles.metricValue}>{money(summary?.cash_in_minor || 0, currency)}</strong></div>
    </div></section>
    <div className={styles.formGrid}>
      <section className={styles.panel}><h2 className={styles.panelTitle}>Add supplier</h2><form className={styles.formGrid} onSubmit={addSupplier}><label className={styles.field}>Company name<input value={name} onChange={(event) => setName(event.target.value)} required /></label><label className={styles.field}>Contact name<input value={contact} onChange={(event) => setContact(event.target.value)} /></label><div className={styles.formActions}><button className={styles.primaryButton} type="submit">Save supplier</button></div></form></section>
      <section className={styles.panel}><div className={styles.toolbar}><h2 className={styles.panelTitle}>Suppliers</h2><button className={styles.secondaryButton} type="button" onClick={() => void load()}>Refresh</button></div><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Company</th><th>Contact</th><th>Phone</th></tr></thead><tbody>{suppliers.map((supplier) => <tr key={supplier.id}><td>{supplier.name}</td><td>{supplier.contact_name || supplier.email || "-"}</td><td>{supplier.phone || "-"}</td></tr>)}{!suppliers.length && <tr><td colSpan={3} className={styles.empty}>No suppliers yet.</td></tr>}</tbody></table></div></section>
    </div>
  </>;
}
