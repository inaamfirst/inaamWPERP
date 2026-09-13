"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import styles from "@/components/commerce.module.css";

type StockRow = {
  product_id: string;
  name: string;
  sku?: string | null;
  warehouse_id: string;
  warehouse_name: string;
  quantity_on_hand: number;
  stock_status: string;
  is_shop_warehouse?: boolean;
  can_adjust?: boolean;
};

type MovementType = "stock_in" | "stock_out" | "damaged" | "adjustment";

export default function VendorStock() {
  const { permissions } = useAuth();
  const canManage = permissions.includes("vendor.stock.manage");
  const [rows, setRows] = useState<StockRow[]>([]);
  const [selected, setSelected] = useState<StockRow | null>(null);
  const [quantity, setQuantity] = useState("1");
  const [movementType, setMovementType] = useState<MovementType>("stock_in");
  const [reason, setReason] = useState("Vendor stock adjustment");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [modalError, setModalError] = useState("");

  async function load() {
    setLoading(true);
    try {
      setRows(await fetchApi("/commerce/vendor/stock") as StockRow[]);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Stock could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function openEditor(row: StockRow) {
    setSelected(row);
    setQuantity("1");
    setMovementType("stock_in");
    setReason("Vendor stock adjustment");
    setModalError("");
  }

  async function submit() {
    if (!selected || !canManage || !selected.can_adjust) return;
    const parsed = Number(quantity);
    if (!Number.isInteger(parsed) || (movementType === "adjustment" ? parsed === 0 : parsed < 1)) {
      setModalError(movementType === "adjustment" ? "Enter a non-zero whole number." : "Enter a whole number greater than zero.");
      return;
    }
    setSaving(true);
    setModalError("");
    try {
      const body = movementType === "adjustment"
        ? { movement_type: movementType, quantity_delta: parsed, warehouse_id: selected.warehouse_id, product_id: selected.product_id, reason }
        : { movement_type: movementType, quantity: parsed, warehouse_id: selected.warehouse_id, product_id: selected.product_id, reason };
      await fetchApi("/commerce/vendor/stock/movements", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setSelected(null);
      await load();
    } catch (caught) {
      setModalError(caught instanceof Error ? caught.message : "Stock adjustment failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className={styles.pageHeader}>
        <div>
          <div className={styles.eyebrow}>Shared inventory</div>
          <h1 className={styles.pageTitle}>Stock management</h1>
          <p className={styles.pageSubtitle}>Your Vendor Shop balance is used by POS and online sales. Other warehouses are shown for reference.</p>
        </div>
      </div>
      {error && <div className={styles.error} role="alert">{error}</div>}
      <div className={styles.panel}>
        <div className={styles.tableWrap}>
          <table className={`${styles.table} ${styles.mobileCardTable}`}>
            <caption className={styles.srOnly}>Vendor stock balances</caption>
            <thead><tr><th>Product</th><th>Warehouse</th><th>On hand</th><th>Status</th>{canManage && <th>Action</th>}</tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={5} className={styles.empty}>Loading stock…</td></tr> : rows.map((row) => (
                <tr key={`${row.product_id}-${row.warehouse_id}`}>
                  <td data-label="Product"><strong>{row.name}</strong><br /><span className={styles.muted}>{row.sku || "No SKU"}</span></td>
                  <td data-label="Warehouse">{row.warehouse_name}{row.is_shop_warehouse && <><br /><span className={styles.muted}>Your shop stock</span></>}</td>
                  <td data-label="On hand"><strong>{row.quantity_on_hand}</strong></td>
                  <td data-label="Status"><span className={`${styles.badge} ${row.quantity_on_hand <= 0 ? styles.badgeDanger : styles.badgeSuccess}`}>{row.quantity_on_hand <= 0 ? "out of stock" : row.stock_status}</span></td>
                  {canManage && <td data-label="Action">
                    {row.can_adjust ? <button type="button" className={styles.secondaryButton} onClick={() => openEditor(row)}>Adjust stock</button> : <span className={styles.muted}>View only</span>}
                  </td>}
                </tr>
              ))}
              {!loading && rows.length === 0 && <tr><td colSpan={canManage ? 5 : 4} className={styles.empty}>No vendor stock balances found.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      {selected && selected.can_adjust && canManage && <div className={styles.posModalBackdrop} role="presentation" onMouseDown={() => !saving && setSelected(null)}>
        <section className={styles.posModal} role="dialog" aria-modal="true" aria-labelledby="stock-adjust-title" onMouseDown={(event) => event.stopPropagation()}>
          <div className={styles.posModalHeader}>
            <div><h2 id="stock-adjust-title">Adjust stock</h2><p className={styles.muted}>{selected.name}</p></div>
            <button type="button" className={styles.secondaryButton} onClick={() => setSelected(null)} disabled={saving}>Cancel</button>
          </div>
          <div className={styles.posModalBody}>
            <div className={styles.muted}><strong>Warehouse:</strong> {selected.warehouse_name} · <strong>Current quantity:</strong> {selected.quantity_on_hand}</div>
            {modalError && <div className={styles.error} role="alert">{modalError}</div>}
            <div className={styles.formGrid}>
              <label className={styles.field}>Movement type
                <select value={movementType} onChange={(event) => setMovementType(event.target.value as MovementType)} disabled={saving}>
                  <option value="stock_in">Receive stock</option>
                  <option value="stock_out">Remove stock</option>
                  <option value="damaged">Record damage</option>
                  <option value="adjustment">Correction (+ or −)</option>
                </select>
              </label>
              <label className={styles.field}>{movementType === "adjustment" ? "Quantity change" : "Quantity"}
                <input type="number" step="1" min={movementType === "adjustment" ? undefined : 1} value={quantity} onChange={(event) => setQuantity(event.target.value)} disabled={saving} autoFocus />
              </label>
            </div>
            <label className={styles.field}>Reason
              <textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} disabled={saving} placeholder="Why is the stock changing?" />
            </label>
            <div className={styles.posModalActions}>
              <button type="button" className={styles.primaryButton} onClick={() => void submit()} disabled={saving}>{saving ? "Saving…" : "Save adjustment"}</button>
              <button type="button" className={styles.secondaryButton} onClick={() => setSelected(null)} disabled={saving}>Cancel</button>
            </div>
          </div>
        </section>
      </div>}
    </>
  );
}
