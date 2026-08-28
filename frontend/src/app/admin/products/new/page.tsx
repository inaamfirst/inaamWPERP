"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { createProduct, type ProductStatus, type ProductType } from "@/lib/products";
import styles from "@/components/commerce.module.css";

function slugify(value: string) {
  return value.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

export default function NewProductPage() {
  const router = useRouter();
  const [form, setForm] = useState({ name: "", slug: "", sku: "", barcode: "", product_type: "simple" as ProductType, status: "active" as ProductStatus, price: "0" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await createProduct({
        name: form.name.trim(),
        slug: form.slug.trim() || slugify(form.name),
        sku: form.sku.trim() || undefined,
        barcode: form.barcode.trim() || undefined,
        product_type: form.product_type,
        status: form.status,
        regular_price_minor: Math.round(Number(form.price || 0) * 100),
      });
      router.replace("/admin/products");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Product could not be created.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Catalog operations</div><h1 className={styles.pageTitle}>Add product</h1><p className={styles.pageSubtitle}>Create the core catalog record. You can add channel details and inventory after saving.</p></div></div>
      {error && <div className={styles.error} role="alert">{error}</div>}
      <form className={`${styles.panel} ${styles.editorNarrow}`} onSubmit={submit}>
        <div className={styles.formGrid}>
          <label className={styles.field}>Name<input required minLength={2} autoFocus value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label>
          <label className={styles.field}>Slug<input value={form.slug} onChange={(event) => setForm({ ...form, slug: event.target.value })} placeholder="Generated from name" /></label>
          <label className={styles.field}>SKU<input value={form.sku} onChange={(event) => setForm({ ...form, sku: event.target.value })} /></label>
          <label className={styles.field}>Barcode<input value={form.barcode} onChange={(event) => setForm({ ...form, barcode: event.target.value })} /></label>
          <label className={styles.field}>Product type<select value={form.product_type} onChange={(event) => setForm({ ...form, product_type: event.target.value as ProductType })}><option value="simple">Simple</option><option value="variable">Variable</option><option value="digital">Digital</option><option value="service">Service</option></select></label>
          <label className={styles.field}>Price (PKR)<input required type="number" min="0" step="0.01" value={form.price} onChange={(event) => setForm({ ...form, price: event.target.value })} /></label>
          <label className={styles.field}>Status<select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value as ProductStatus })}><option value="active">Active</option><option value="draft">Draft</option></select></label>
        </div>
        <div className={styles.formActions}><button type="button" className={styles.secondaryButton} onClick={() => router.back()}>Cancel</button><button type="submit" className={styles.primaryButton} disabled={saving}>{saving ? "Creating…" : "Create product"}</button></div>
      </form>
    </>
  );
}
