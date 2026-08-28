"use client";

import { useEffect, useState, type FormEvent } from "react";
import { fetchApi } from "@/lib/api";
import { getProducts, type Product } from "@/lib/products";
import { useAuth } from "@/contexts/AuthContext";
import styles from "@/components/commerce.module.css";

type Warehouse = { id: string; code: string; name: string; address: string | null; is_active: boolean };
type StockLevel = { warehouse_id: string; product_id: string; variant_id: string | null; quantity_on_hand: number };

export default function AdminInventory() {
  const { permissions } = useAuth();
  const canManage = permissions.includes("inventory.manage");
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [stock, setStock] = useState<StockLevel[]>([]);
  const [warehouseForm, setWarehouseForm] = useState({ code: "", name: "", address: "" });
  const [movementForm, setMovementForm] = useState({ warehouse_id: "", product_id: "", quantity_delta: "", reason: "" });
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true); setError("");
    try {
      const [warehouseRows, productRows, stockRows] = await Promise.all([
        fetchApi("/inventory/warehouses"), getProducts(), fetchApi("/inventory/stock"),
      ]);
      const nextWarehouses = warehouseRows as Warehouse[];
      setWarehouses(nextWarehouses); setProducts(productRows); setStock(stockRows as StockLevel[]);
      setMovementForm((current) => ({ ...current, warehouse_id: current.warehouse_id || nextWarehouses[0]?.id || "", product_id: current.product_id || productRows[0]?.id || "" }));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Inventory could not be loaded."); }
    finally { setLoading(false); }
  }
  // This effect synchronizes the view with the remote inventory API.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, []);

  async function createWarehouse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canManage) return;
    setError(""); setMessage("");
    try { await fetchApi("/inventory/warehouses", { method: "POST", body: JSON.stringify(warehouseForm) }); setWarehouseForm({ code: "", name: "", address: "" }); setMessage("Warehouse created."); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Warehouse could not be created."); }
  }

  async function recordMovement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canManage) return;
    setError(""); setMessage("");
    const delta = Number.parseInt(movementForm.quantity_delta, 10);
    if (!movementForm.warehouse_id || !movementForm.product_id || !Number.isInteger(delta) || delta === 0) { setError("Choose a product and warehouse and enter a non-zero quantity change."); return; }
    try { await fetchApi("/inventory/stock-movements", { method: "POST", body: JSON.stringify({ movement_type: "adjustment", warehouse_id: movementForm.warehouse_id, product_id: movementForm.product_id, quantity_delta: delta, reason: movementForm.reason || null }) }); setMovementForm((current) => ({ ...current, quantity_delta: "", reason: "" })); setMessage("Stock movement recorded."); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Stock movement could not be recorded."); }
  }

  const productName = (id: string) => products.find((product) => product.id === id)?.name || id;
  const warehouseName = (id: string) => warehouses.find((warehouse) => warehouse.id === id)?.name || id;

  return <>
    <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Stock operations</div><h1 className={styles.pageTitle}>Inventory</h1><p className={styles.pageSubtitle}>Manage warehouses, inspect stock, and record auditable stock movements.</p></div><button type="button" className={styles.secondaryButton} onClick={() => void load()}>Refresh</button></div>
    {error && <div className={styles.error}>{error}</div>}{message && <div className={styles.notice}>{message}</div>}
    {canManage && <div className={styles.formGrid}><form className={styles.panel} onSubmit={createWarehouse}><h2 className={styles.panelTitle}>Add warehouse</h2><label className={styles.field}>Code<input required pattern="[A-Za-z0-9_-]+" value={warehouseForm.code} onChange={(event) => setWarehouseForm({ ...warehouseForm, code: event.target.value })} /></label><label className={styles.field}>Name<input required minLength={2} value={warehouseForm.name} onChange={(event) => setWarehouseForm({ ...warehouseForm, name: event.target.value })} /></label><label className={styles.field}>Address<input value={warehouseForm.address} onChange={(event) => setWarehouseForm({ ...warehouseForm, address: event.target.value })} /></label><div className={styles.formActions}><button type="submit" className={styles.primaryButton}>Create warehouse</button></div></form><form className={styles.panel} onSubmit={recordMovement}><h2 className={styles.panelTitle}>Record stock movement</h2><label className={styles.field}>Warehouse<select required value={movementForm.warehouse_id} onChange={(event) => setMovementForm({ ...movementForm, warehouse_id: event.target.value })}>{warehouses.map((warehouse) => <option key={warehouse.id} value={warehouse.id}>{warehouse.code} — {warehouse.name}</option>)}</select></label><label className={styles.field}>Product<select required value={movementForm.product_id} onChange={(event) => setMovementForm({ ...movementForm, product_id: event.target.value })}>{products.map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}</select></label><label className={styles.field}>Quantity change<input required type="number" value={movementForm.quantity_delta} onChange={(event) => setMovementForm({ ...movementForm, quantity_delta: event.target.value })} placeholder="+10 or -2" /></label><label className={styles.field}>Reason<input value={movementForm.reason} onChange={(event) => setMovementForm({ ...movementForm, reason: event.target.value })} /></label><div className={styles.formActions}><button type="submit" className={styles.primaryButton}>Record movement</button></div></form></div>}
    <section className={styles.panel}><div className={styles.toolbar}><h2 className={styles.panelTitle}>Current stock</h2><span className={styles.muted}>{loading ? "Loading…" : `${stock.length} balances`}</span></div><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Warehouse</th><th>Product</th><th>Quantity on hand</th></tr></thead><tbody>{stock.map((row) => <tr key={`${row.warehouse_id}:${row.product_id}:${row.variant_id || "base"}`}><td>{warehouseName(row.warehouse_id)}</td><td>{productName(row.product_id)}</td><td><strong>{row.quantity_on_hand}</strong></td></tr>)}{!loading && stock.length === 0 && <tr><td colSpan={3} className={styles.empty}>No stock balances found.</td></tr>}</tbody></table></div></section>
  </>;
}
