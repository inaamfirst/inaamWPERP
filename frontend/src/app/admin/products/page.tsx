"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useAuth } from "@/contexts/AuthContext";
import { ApiError, fetchApi } from "@/lib/api";
import { getProducts, type Product } from "@/lib/products";
import styles from "@/components/commerce.module.css";

type ProductForm = { name: string; sku: string; status: string; price: string };

function formFromProduct(product: Product): ProductForm {
  return {
    name: product.name,
    sku: product.sku || "",
    status: product.status,
    price: (product.regular_price_minor / 100).toFixed(2),
  };
}

export default function AdminProducts() {
  const { permissions } = useAuth();
  const canManage = permissions.includes("catalog.manage");
  const [products, setProducts] = useState<Product[]>([]);
  const [selected, setSelected] = useState<Product | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<Product | null>(null);
  const [form, setForm] = useState<ProductForm>({ name: "", sku: "", status: "active", price: "0" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    try {
      setProducts(await getProducts());
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Products could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  // Synchronize the view with the remote catalog API.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, []);

  function selectProduct(product: Product) {
    setSelected(product);
    setForm(formFromProduct(product));
    setError("");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canManage || !selected || !form.name.trim()) return;
    setSaving(true);
    setError("");
    try {
      const updated = await fetchApi(`/catalog/products/${selected.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: form.name.trim(),
          sku: form.sku.trim() || null,
          status: form.status,
          regular_price_minor: Math.round(Number(form.price || 0) * 100),
        }),
      }) as Product;
      setProducts((current) => current.map((product) => product.id === updated.id ? updated : product));
      setSelected(updated);
      setForm(formFromProduct(updated));
    } catch (caught) {
      setError(caught instanceof ApiError ? String(caught.data.detail || caught.message) : "Product could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function archive() {
    if (!canManage || !archiveTarget) return;
    try {
      await fetchApi(`/catalog/products/${archiveTarget.id}`, { method: "DELETE" });
      setArchiveTarget(null);
      setSelected(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Product could not be archived.");
    }
  }

  return (
    <>
      <div className={styles.pageHeader}>
        <div>
          <div className={styles.eyebrow}>Catalog operations</div>
          <h1 className={styles.pageTitle}>Products &amp; catalog</h1>
          <p className={styles.pageSubtitle}>Review products across every channel. Editing actions follow your assigned catalog permissions.</p>
        </div>
        {canManage && <Link className={styles.primaryButton} href="/admin/products/new">Add product</Link>}
      </div>

      {error && <div className={styles.error} role="alert">{error}</div>}
      <div className={styles.formGrid}>
        <section className={styles.panel}>
          <div className={styles.toolbar}>
            <h2 className={styles.panelTitle}>Product catalog</h2>
            <button type="button" className={styles.secondaryButton} onClick={() => void load()}>Refresh</button>
          </div>
          {loading ? <div className={styles.empty} role="status">Loading products…</div> : (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <caption className={styles.srOnly}>Product catalog</caption>
                <thead><tr><th>Name</th><th>SKU</th><th>Price</th><th>Status</th>{canManage && <th>Actions</th>}</tr></thead>
                <tbody>
                  {products.map((product) => (
                    <tr key={product.id}>
                      <td><strong>{product.name}</strong><br /><span className={styles.muted}>{product.product_type}</span></td>
                      <td>{product.sku || "—"}</td>
                      <td>PKR {(product.regular_price_minor / 100).toFixed(2)}</td>
                      <td><span className={`${styles.badge} ${product.status === "active" ? styles.badgeSuccess : styles.badgeWarning}`}>{product.status}</span></td>
                      {canManage && <td><button type="button" className={styles.secondaryButton} onClick={() => selectProduct(product)}>Edit</button></td>}
                    </tr>
                  ))}
                  {products.length === 0 && <tr><td colSpan={canManage ? 5 : 4} className={styles.empty}>No products found.</td></tr>}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {canManage && selected && (
          <section className={styles.panel}>
            <div className={styles.toolbar}><h2 className={styles.panelTitle}>Edit product</h2><button type="button" className={styles.secondaryButton} onClick={() => setSelected(null)}>Close</button></div>
            <form className={styles.formGrid} onSubmit={save}>
              <label className={styles.field}>Name<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required minLength={2} /></label>
              <label className={styles.field}>SKU<input value={form.sku} onChange={(event) => setForm({ ...form, sku: event.target.value })} /></label>
              <label className={styles.field}>Price (PKR)<input type="number" min="0" step="0.01" value={form.price} onChange={(event) => setForm({ ...form, price: event.target.value })} /></label>
              <label className={styles.field}>Status<select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}><option value="active">Active</option><option value="draft">Draft</option><option value="archived">Archived</option></select></label>
              <div className={styles.formActions}>
                <button className={styles.primaryButton} disabled={saving} type="submit">{saving ? "Saving…" : "Save changes"}</button>
                <button className={styles.dangerButton} type="button" onClick={() => setArchiveTarget(selected)}>Archive</button>
              </div>
            </form>
          </section>
        )}
      </div>

      <ConfirmDialog
        open={Boolean(archiveTarget)}
        title="Archive product?"
        description={`${archiveTarget?.name || "This product"} will be removed from active sales channels. Historical records remain available.`}
        confirmLabel="Archive product"
        destructive
        onCancel={() => setArchiveTarget(null)}
        onConfirm={() => void archive()}
      />
    </>
  );
}
