"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type SaleItem = { id: string; name: string; sku?: string | null; quantity: number; line_total_minor: number };
type Sale = {
  id: string;
  bill_number: string;
  created_at: string;
  customer: string;
  total_minor: number;
  item_quantity: number;
  payment_method: string;
  payment_status: string;
  status: string;
  items: SaleItem[];
};
type Tab = "sales" | "bills";
const money = (minor: number) => `PKR ${(minor / 100).toFixed(2)}`;
const escapeHtml = (value: string | number) => String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[character] || character));

export default function VendorPosHistory() {
  const [sales, setSales] = useState<Sale[]>([]);
  const [tab, setTab] = useState<Tab>("sales");
  const [selected, setSelected] = useState<Sale | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const setFromHash = () => {
      const value = window.location.hash.slice(1);
      if (value === "bills") setTab("bills");
      else if (value === "sales") setTab("sales");
      else if (value && active) setSelected((current) => current?.id === value ? current : null);
    };
    setFromHash();
    window.addEventListener("hashchange", setFromHash);
    fetchApi("/commerce/vendor/shop/sales")
      .then((value) => {
        if (!active) return;
        const rows = value as Sale[];
        setSales(rows);
        const billId = window.location.hash.slice(1);
        if (billId && billId !== "sales" && billId !== "bills") setSelected(rows.find((row) => row.id === billId) || null);
      })
      .catch(() => active && setError("Shop sales could not be loaded."));
    return () => { active = false; window.removeEventListener("hashchange", setFromHash); };
  }, []);

  function chooseTab(next: Tab) {
    setTab(next);
    window.location.hash = next;
  }

  function printBill(sale: Sale) {
    const popup = window.open("", "shop-bill", "width=420,height=640");
    if (!popup) { window.print(); return; }
    const itemRows = sale.items.map((item) => `<tr><td>${escapeHtml(item.name)}</td><td>${item.quantity}</td><td style="text-align:right">${money(item.line_total_minor)}</td></tr>`).join("");
    popup.document.write(`<!doctype html><html><head><title>Bill ${escapeHtml(sale.bill_number)}</title><style>body{font-family:Arial,sans-serif;padding:24px;color:#111}h1{font-size:22px;margin:0 0 14px}p{margin:6px 0}table{width:100%;border-collapse:collapse;margin-top:16px}td,th{padding:8px 0;border-bottom:1px solid #ddd;text-align:left}.total{font-size:22px;font-weight:700;text-align:right;margin-top:18px}</style></head><body><h1>Shop bill</h1><p><strong>${escapeHtml(sale.bill_number)}</strong></p><p>${escapeHtml(new Date(sale.created_at).toLocaleString())}</p><p>Customer: ${escapeHtml(sale.customer)}</p><table><thead><tr><th>Item</th><th>Qty</th><th style="text-align:right">Amount</th></tr></thead><tbody>${itemRows}</tbody></table><p class="total">Total: ${money(sale.total_minor)}</p><p>Payment: ${escapeHtml(sale.payment_method)}</p></body></html>`);
    popup.document.close(); popup.focus(); popup.print(); popup.close();
  }

  return <div className={styles.posShell}>
    <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Shop / POS</div><h1 className={styles.pageTitle}>Sales and bills</h1><p className={styles.pageSubtitle}>Walk-in sales are kept here. Online store orders are managed separately in Online Orders.</p></div></div>
    <nav className={styles.posActionBar} aria-label="POS sales history"><button className={`${styles.posActionButton} ${tab === "sales" ? styles.posActionPrimary : ""}`} onClick={() => chooseTab("sales")}>Recent Sales</button><button className={`${styles.posActionButton} ${tab === "bills" ? styles.posActionPrimary : ""}`} onClick={() => chooseTab("bills")}>Bills</button><a className={styles.posActionButton} href="/vendor/pos">Back to POS</a></nav>
    {error && <div className={styles.error} role="alert">{error}</div>}
    <section className={styles.panel}><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>{tab === "bills" ? "Bill" : "Sale"}</th><th>Date & time</th><th>Customer</th><th>Items</th><th>Payment</th><th>Total</th><th>Actions</th></tr></thead><tbody>{sales.map((sale) => <tr key={sale.id}><td><strong>{sale.bill_number}</strong><br /><span className={styles.muted}>{sale.status}</span></td><td>{new Date(sale.created_at).toLocaleString()}</td><td>{sale.customer}</td><td>{sale.item_quantity}</td><td>{sale.payment_method}<br /><span className={styles.muted}>{sale.payment_status}</span></td><td>{money(sale.total_minor)}</td><td><div className={styles.posHistoryActions}><button className={styles.posSmallButton} onClick={() => { setSelected(sale); window.location.hash = sale.id; }}>View</button><button className={styles.posSmallButton} onClick={() => printBill(sale)}>Print</button></div></td></tr>)}{!sales.length && <tr><td colSpan={7} className={styles.empty}>No Shop/POS sales yet. Completed walk-in sales will appear here.</td></tr>}</tbody></table></div></section>
    {selected && <section className={styles.panel}><div className={styles.toolbar}><div><h2 className={styles.panelTitle}>Bill {selected.bill_number}</h2><p className={styles.muted}>{selected.customer} · {new Date(selected.created_at).toLocaleString()}</p></div><div className={styles.posHistoryActions}><button className={styles.posSmallButton} onClick={() => printBill(selected)}>Print bill</button><button className={styles.posSmallButton} onClick={() => { setSelected(null); window.location.hash = tab; }}>Close</button></div></div><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Product</th><th>SKU</th><th>Quantity</th><th>Total</th></tr></thead><tbody>{selected.items.map((item) => <tr key={item.id}><td>{item.name}</td><td>{item.sku || "-"}</td><td>{item.quantity}</td><td>{money(item.line_total_minor)}</td></tr>)}</tbody></table></div><div className={styles.posHistoryTotal}><span>Payment: {selected.payment_method}</span><strong>{money(selected.total_minor)}</strong></div></section>}
  </div>;
}
