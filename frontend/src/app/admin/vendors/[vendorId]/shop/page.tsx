"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Shop = { warehouse: { code: string; name: string }; accounting: { purchase_total_minor: number; supplier_payable_minor: number; cash_in_minor: number; cash_out_minor: number; currency: string }; suppliers: Array<{ id: string; name: string }>; stock: Array<{ product_id: string; name: string; quantity_on_hand: number; warehouse_name: string }> };
const money = (amount: number, currency: string) => `${currency} ${(amount / 100).toFixed(2)}`;

export default function AdminVendorShop({ params }: { params: Promise<{ vendorId: string }> }) {
  const [shop, setShop] = useState<Shop | null>(null); const [error, setError] = useState("");
  useEffect(() => { void params.then(({ vendorId }) => fetchApi(`/commerce/admin/vendors/${vendorId}/shop`).then((value) => setShop(value as Shop)).catch(() => setError("Vendor shop could not be loaded."))); }, [params]);
  const currency = shop?.accounting.currency || "PKR";
  return <><div className={styles.pageHeader}><div><div className={styles.eyebrow}>Administrator oversight</div><h1 className={styles.pageTitle}>Vendor shop</h1><p className={styles.pageSubtitle}>Read and manage this vendor’s stock, suppliers, purchases, and shop cash records.</p></div></div>{error && <div className={styles.error}>{error}</div>}{shop && <><div className={styles.metricGrid}><div className={styles.metricCard}><span className={styles.metricLabel}>Shop warehouse</span><strong className={styles.metricValue}>{shop.warehouse.code}</strong></div><div className={styles.metricCard}><span className={styles.metricLabel}>Supplier payable</span><strong className={styles.metricValue}>{money(shop.accounting.supplier_payable_minor, currency)}</strong></div><div className={styles.metricCard}><span className={styles.metricLabel}>Cash in</span><strong className={styles.metricValue}>{money(shop.accounting.cash_in_minor, currency)}</strong></div><div className={styles.metricCard}><span className={styles.metricLabel}>Cash out</span><strong className={styles.metricValue}>{money(shop.accounting.cash_out_minor, currency)}</strong></div></div><section className={styles.panel}><h2 className={styles.panelTitle}>Shop stock</h2><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Product</th><th>Warehouse</th><th>On hand</th></tr></thead><tbody>{shop.stock.map((row) => <tr key={`${row.product_id}-${row.warehouse_name}`}><td>{row.name}</td><td>{row.warehouse_name}</td><td>{row.quantity_on_hand}</td></tr>)}</tbody></table></div></section></>}</>;
}