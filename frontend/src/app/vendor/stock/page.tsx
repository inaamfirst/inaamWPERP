"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import styles from "@/components/commerce.module.css";

type StockRow = { product_id: string; name: string; sku?: string | null; warehouse_id: string; warehouse_name: string; quantity_on_hand: number; stock_status: string };

export default function VendorStock() {
  const { permissions } = useAuth();
  const canManage = permissions.includes("vendor.stock.manage");
  const [rows, setRows] = useState<StockRow[]>([]);
  const [selected, setSelected] = useState<StockRow | null>(null);
  const [quantity, setQuantity] = useState("1");
  const [movementType, setMovementType] = useState("stock_in");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    try {
      setRows(await fetchApi("/commerce/vendor/stock") as StockRow[]);
    } catch {
      setError("Stock could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let active = true;
    fetchApi("/commerce/vendor/stock")
      .then((value) => active && setRows(value as StockRow[]))
      .catch(() => active && setError("Stock could not be loaded."))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  async function submit() {
    if (!canManage || !selected) return;
    try {
      await fetchApi("/commerce/vendor/stock/movements", {
        method: "POST",
        body: JSON.stringify({ movement_type: movementType, warehouse_id: selected.warehouse_id, product_id: selected.product_id, quantity: Number(quantity), reason: "Vendor workspace adjustment" }),
      });
      setSelected(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Stock adjustment failed.");
    }
  }

  return (
    <>
      <div className={styles.pageHeader}>
        <div>
          <div className={styles.eyebrow}>Shared inventory</div>
          <h1 className={styles.pageTitle}>Stock management</h1>
          <p className={styles.pageSubtitle}>Physical and online sales use the same quantity. Keep receipts, damage, and corrections visible.</p>
        </div>
      </div>
      {error && <div className={styles.error} role="alert">{error}</div>}
      <div className={styles.panel}>
        <div className={styles.tableWrap}>
          <table className={`${styles.table} ${styles.mobileCardTable}`}>
            <caption className={styles.srOnly}>Vendor stock balances</caption>
            <thead><tr><th>Product</th><th>Warehouse</th><th>On hand</th><th>Status</th>{canManage && <th>Action</th>}</tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={5} className={styles.empty}>Loading stock…</td></tr> : rows.map((row) => <tr key={`${row.product_id}-${row.warehouse_id}`}>
                <td data-label="Product"><strong>{row.name}</strong><br /><span className={styles.muted}>{row.sku || "No SKU"}</span></td>
                <td data-label="Warehouse">{row.warehouse_name}</td>
                <td data-label="On hand"><strong>{row.quantity_on_hand}</strong></td>
                <td data-label="Status"><span className={`${styles.badge} ${row.quantity_on_hand <= 0 ? styles.badgeDanger : styles.badgeSuccess}`}>{row.quantity_on_hand <= 0 ? "out of stock" : row.stock_status}</span></td>
                {canManage && <td data-label="Action"><button type="button" className={styles.secondaryButton} onClick={() => setSelected(row)}>Adjust stock</button></td>}
              </tr>)}
              {!loading && rows.length === 0 && <tr><td colSpan={canManage ? 5 : 4} className={styles.empty}>No vendor stock balances found.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {canManage && selected && <>
        <button type="button" className={styles.mobileOnlyBackdrop} onClick={() => setSelected(null)} aria-label="Close stock adjustment" />
        <section className={`${styles.panel} ${styles.stockInline}`} aria-label="Adjust stock">
          <div className={styles.toolbar}>
            <div><h2 className={styles.panelTitle}>Adjust {selected.name}</h2><p className={styles.muted}>{selected.warehouse_name} · Current quantity {selected.quantity_on_hand}</p></div>
            <button type="button" className={styles.secondaryButton} onClick={() => setSelected(null)}>Close</button>
          </div>
          <div className={styles.formGrid}>
            <label className={styles.field}>Movement<select value={movementType} onChange={(event) => setMovementType(event.target.value)}><option value="stock_in">Receive stock</option><option value="stock_out">Remove stock</option><option value="damaged">Record damage</option></select></label>
            <label className={styles.field}>Quantity<input type="number" min="1" value={quantity} onChange={(event) => setQuantity(event.target.value)} /></label>
          </div>
          <div className={styles.formActions}><button type="button" className={styles.primaryButton} onClick={() => void submit()}>Save movement</button></div>
        </section>
      </>}
    </>
  );
}
