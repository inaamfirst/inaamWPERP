"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Shop = {
  warehouse: { code: string; name: string };
  accounting: { purchase_total_minor: number; supplier_payable_minor: number; cash_in_minor: number; cash_out_minor: number; currency: string };
  suppliers: Array<{ id: string; name: string; phone?: string | null; outstanding_minor?: number }>;
  catalog: Array<{ id: string; name: string; sku?: string | null; stock_quantity: number; online_status: string; regular_price_minor: number; sale_price_minor?: number | null }>;
  purchases: Array<{ id: string; purchase_number: string; total_minor: number; paid_minor: number; payment_status: string; created_at: string }>;
  sales: Array<{ id: string; bill_number: string; customer: string; total_minor: number; payment_method: string; status: string; channel?: string; created_at: string }>;
  stock: Array<{ product_id: string; name: string; quantity_on_hand: number; warehouse_name: string }>;
};
type Tab = "products" | "stock" | "sales" | "purchases" | "accounting";
const money = (amount: number, currency: string) => `${currency} ${(amount / 100).toFixed(2)}`;

export default function AdminVendorShop({ params }: { params: Promise<{ vendorId: string }> }) {
  const [shop, setShop] = useState<Shop | null>(null);
  const [tab, setTab] = useState<Tab>("products");
  const [error, setError] = useState("");
  useEffect(() => { void params.then(({ vendorId }) => fetchApi(`/commerce/admin/vendors/${vendorId}/shop`).then((value) => setShop(value as Shop)).catch(() => setError("Vendor shop could not be loaded."))); }, [params]);
  const currency = shop?.accounting.currency || "PKR";
  return <div className={styles.posShell}>
    <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Administrator oversight</div><h1 className={styles.pageTitle}>Vendor shop</h1><p className={styles.pageSubtitle}>Check this vendor's products, stock, sales, purchases, bills, and shop cash.</p></div></div>
    {error && <div className={styles.error}>{error}</div>}
    {shop && <>
      <div className={styles.metricGrid}><div className={styles.metricCard}><span className={styles.metricLabel}>Shop location</span><strong className={styles.metricValue}>{shop.warehouse.code}</strong></div><div className={styles.metricCard}><span className={styles.metricLabel}>Supplier payable</span><strong className={styles.metricValue}>{money(shop.accounting.supplier_payable_minor, currency)}</strong></div><div className={styles.metricCard}><span className={styles.metricLabel}>Cash in</span><strong className={styles.metricValue}>{money(shop.accounting.cash_in_minor, currency)}</strong></div><div className={styles.metricCard}><span className={styles.metricLabel}>Cash out</span><strong className={styles.metricValue}>{money(shop.accounting.cash_out_minor, currency)}</strong></div></div>
      <nav className={styles.posActionBar} aria-label="Vendor shop sections">{(["products", "stock", "sales", "purchases", "accounting"] as Tab[]).map((name) => <button key={name} className={`${styles.posActionButton} ${tab === name ? styles.posActionPrimary : ""}`} onClick={() => setTab(name)}>{name === "products" ? "Products & publishing" : name === "stock" ? "Shop stock" : name === "sales" ? "POS / online sales" : name === "purchases" ? "Purchases & suppliers" : "Accounting"}</button>)}</nav>
      {tab === "products" && <section className={styles.panel}><h2 className={styles.panelTitle}>Products and publication</h2><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Product</th><th>SKU</th><th>Shop stock</th><th>Online</th><th>Price</th></tr></thead><tbody>{shop.catalog.map((row) => <tr key={row.id}><td>{row.name}</td><td>{row.sku || "-"}</td><td>{row.stock_quantity}</td><td>{row.online_status === "published" ? "Published" : "Private"}</td><td>{money(row.sale_price_minor ?? row.regular_price_minor, currency)}</td></tr>)}</tbody></table></div></section>}
      {tab === "stock" && <section className={styles.panel}><h2 className={styles.panelTitle}>Shop stock</h2><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Product</th><th>Location</th><th>On hand</th></tr></thead><tbody>{shop.catalog.map((row) => <tr key={row.id}><td>{row.name}</td><td>{shop.warehouse.name}</td><td>{row.stock_quantity}</td></tr>)}</tbody></table></div></section>}
      {tab === "sales" && <section className={styles.panel}><h2 className={styles.panelTitle}>Recent POS and online sales</h2><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Bill</th><th>Channel</th><th>Date</th><th>Customer</th><th>Total</th><th>Payment</th><th>Status</th></tr></thead><tbody>{shop.sales.map((row) => <tr key={row.id}><td>{row.bill_number}</td><td>{row.channel === "pos" ? "POS" : "Online"}</td><td>{new Date(row.created_at).toLocaleString()}</td><td>{row.customer}</td><td>{money(row.total_minor, currency)}</td><td>{row.payment_method}</td><td>{row.status}</td></tr>)}</tbody></table></div></section>}
      {tab === "purchases" && <section className={styles.panel}><h2 className={styles.panelTitle}>Purchases and suppliers</h2><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Purchase</th><th>Date</th><th>Total</th><th>Paid</th><th>Status</th></tr></thead><tbody>{shop.purchases.map((row) => <tr key={row.id}><td>{row.purchase_number}</td><td>{new Date(row.created_at).toLocaleString()}</td><td>{money(row.total_minor, currency)}</td><td>{money(row.paid_minor, currency)}</td><td>{row.payment_status}</td></tr>)}</tbody></table></div><h3>Suppliers</h3><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Name</th><th>Phone</th><th>Outstanding</th></tr></thead><tbody>{shop.suppliers.map((row) => <tr key={row.id}><td>{row.name}</td><td>{row.phone || "-"}</td><td>{money(row.outstanding_minor || 0, currency)}</td></tr>)}</tbody></table></div></section>}
      {tab === "accounting" && <section className={styles.panel}><h2 className={styles.panelTitle}>Shop accounting</h2><div className={styles.metricGrid}><div className={styles.metricCard}><span className={styles.metricLabel}>Purchase total</span><strong className={styles.metricValue}>{money(shop.accounting.purchase_total_minor, currency)}</strong></div><div className={styles.metricCard}><span className={styles.metricLabel}>Supplier balance</span><strong className={styles.metricValue}>{money(shop.accounting.supplier_payable_minor, currency)}</strong></div><div className={styles.metricCard}><span className={styles.metricLabel}>Cash in</span><strong className={styles.metricValue}>{money(shop.accounting.cash_in_minor, currency)}</strong></div><div className={styles.metricCard}><span className={styles.metricLabel}>Cash out</span><strong className={styles.metricValue}>{money(shop.accounting.cash_out_minor, currency)}</strong></div></div><p className={styles.muted}>Use the vendor's shop ledger for the complete audited transaction history.</p></section>}
    </>}
  </div>;
}
