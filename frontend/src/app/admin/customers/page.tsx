"use client";

import { useEffect, useState, type FormEvent } from "react";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useAuth } from "@/contexts/AuthContext";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Customer = { id: string; full_name: string; email: string | null; phone: string | null; status: string; source_channel: string };
type CustomerForm = { full_name: string; email: string; phone: string; status: string; source_channel: string };
const emptyForm: CustomerForm = { full_name: "", email: "", phone: "", status: "active", source_channel: "manual" };

export default function AdminCustomers() {
  const { permissions } = useAuth();
  const canManage = permissions.includes("customers.manage");
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [selected, setSelected] = useState<Customer | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<Customer | null>(null);
  const [form, setForm] = useState<CustomerForm>(emptyForm);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try { setCustomers(await fetchApi("/customers") as Customer[]); setError(""); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Customers could not be loaded."); }
    finally { setLoading(false); }
  }
  // Synchronize the view with the remote customer API.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, []);

  function beginCreate() { setSelected(null); setForm(emptyForm); setError(""); setMessage(""); }
  function beginEdit(customer: Customer) {
    setSelected(customer);
    setForm({ full_name: customer.full_name, email: customer.email || "", phone: customer.phone || "", status: customer.status, source_channel: customer.source_channel });
    setError("");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canManage) return;
    setError(""); setMessage("");
    try {
      const payload = { full_name: form.full_name.trim(), email: form.email.trim() || null, phone: form.phone.trim() || null, status: form.status, source_channel: form.source_channel };
      const saved = selected
        ? await fetchApi(`/customers/${selected.id}`, { method: "PATCH", body: JSON.stringify(payload) }) as Customer
        : await fetchApi("/customers", { method: "POST", body: JSON.stringify(payload) }) as Customer;
      setCustomers((current) => selected ? current.map((customer) => customer.id === saved.id ? saved : customer) : [saved, ...current]);
      beginEdit(saved);
      setMessage("Customer saved.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Customer could not be saved."); }
  }

  async function archive() {
    if (!canManage || !archiveTarget) return;
    try {
      await fetchApi(`/customers/${archiveTarget.id}`, { method: "DELETE" });
      setArchiveTarget(null); setSelected(null); setMessage("Customer archived.");
      await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Customer could not be archived."); }
  }

  return (
    <>
      <div className={styles.pageHeader}>
        <div><div className={styles.eyebrow}>Customer operations</div><h1 className={styles.pageTitle}>Customers</h1><p className={styles.pageSubtitle}>Contact data and lifecycle status used by POS and online orders.</p></div>
        {canManage && <button type="button" className={styles.primaryButton} onClick={beginCreate}>Add customer</button>}
      </div>
      {error && <div className={styles.error} role="alert">{error}</div>}
      {message && <div className={styles.notice} role="status" aria-live="polite">{message}</div>}

      <div className={styles.formGrid}>
        <section className={styles.panel}>
          <div className={styles.toolbar}><h2 className={styles.panelTitle}>Customer directory</h2><button type="button" className={styles.secondaryButton} onClick={() => void load()}>Refresh</button></div>
          {loading ? <div className={styles.empty} role="status">Loading customers…</div> : (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <caption className={styles.srOnly}>Customer directory</caption>
                <thead><tr><th>Name</th><th>Contact</th><th>Source</th><th>Status</th>{canManage && <th>Actions</th>}</tr></thead>
                <tbody>
                  {customers.map((customer) => <tr key={customer.id}><td>{customer.full_name}</td><td>{customer.email || customer.phone || "—"}</td><td>{customer.source_channel}</td><td><span className={styles.badge}>{customer.status}</span></td>{canManage && <td><button type="button" className={styles.secondaryButton} onClick={() => beginEdit(customer)}>Edit</button></td>}</tr>)}
                  {customers.length === 0 && <tr><td colSpan={canManage ? 5 : 4} className={styles.empty}>No customers found.</td></tr>}
                </tbody>
              </table>
            </div>
          )}
        </section>

        {canManage && (
          <section className={styles.panel}>
            <div className={styles.toolbar}><h2 className={styles.panelTitle}>{selected ? "Edit customer" : "New customer"}</h2>{selected && <button type="button" className={styles.secondaryButton} onClick={beginCreate}>New</button>}</div>
            <form className={styles.formGrid} onSubmit={save}>
              <label className={styles.field}>Full name<input required minLength={2} value={form.full_name} onChange={(event) => setForm({ ...form, full_name: event.target.value })} /></label>
              <label className={styles.field}>Email<input type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} /></label>
              <label className={styles.field}>Phone<input value={form.phone} onChange={(event) => setForm({ ...form, phone: event.target.value })} /></label>
              <label className={styles.field}>Source<select value={form.source_channel} onChange={(event) => setForm({ ...form, source_channel: event.target.value })}><option value="manual">Manual</option><option value="pos">POS</option><option value="woocommerce">WooCommerce</option><option value="legacy">Legacy</option></select></label>
              {selected && <label className={styles.field}>Status<select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}><option value="active">Active</option><option value="inactive">Inactive</option><option value="archived">Archived</option></select></label>}
              <div className={styles.formActions}><button className={styles.primaryButton} type="submit">Save customer</button>{selected && <button className={styles.dangerButton} type="button" onClick={() => setArchiveTarget(selected)}>Archive</button>}</div>
            </form>
          </section>
        )}
      </div>

      <ConfirmDialog open={Boolean(archiveTarget)} title="Archive customer?" description={`${archiveTarget?.full_name || "This customer"} will no longer appear in active customer searches. Existing order history is preserved.`} confirmLabel="Archive customer" destructive onCancel={() => setArchiveTarget(null)} onConfirm={() => void archive()} />
    </>
  );
}
