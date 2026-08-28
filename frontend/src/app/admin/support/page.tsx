"use client";

import { FormEvent, useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Contact = {
  id: string;
  label: string;
  role: string;
  phone: string;
  working_hours?: string | null;
  is_active: boolean;
};

export default function AdminSupport() {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [form, setForm] = useState({
    label: "",
    role: "support",
    phone: "",
    working_hours: "",
    whatsapp_message: "",
  });
  const [error, setError] = useState("");
  async function load() {
    try {
      setContacts(
        (await fetchApi("/commerce/admin/support/contacts")) as Contact[],
      );
    } catch {
      setError("Support directory could not be loaded.");
    }
  }
  useEffect(() => {
    let active = true;
    fetchApi("/commerce/admin/support/contacts")
      .then((value) => active && setContacts(value as Contact[]))
      .catch(
        () => active && setError("Support directory could not be loaded."),
      );
    return () => {
      active = false;
    };
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await fetchApi("/commerce/admin/support/contacts", {
        method: "POST",
        body: JSON.stringify({
          ...form,
          priority: contacts.length,
          is_active: true,
        }),
      });
      setForm({
        label: "",
        role: "support",
        phone: "",
        working_hours: "",
        whatsapp_message: "",
      });
      await load();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Contact could not be added.",
      );
    }
  }
  return (
    <>
      <div className={styles.pageHeader}>
        <div>
          <div className={styles.eyebrow}>Company settings</div>
          <h1 className={styles.pageTitle}>Support directory</h1>
          <p className={styles.pageSubtitle}>
            These contacts appear as clickable WhatsApp support options in every
            vendor workspace.
          </p>
        </div>
      </div>
      {error && <div className={styles.error}>{error}</div>}
      <div className={styles.formGrid}>
        <form className={styles.panel} onSubmit={submit}>
          <h2 className={styles.panelTitle}>Add contact</h2>
          <div className={`${styles.formGrid} ${styles.sectionInset}`}>
            <label className={styles.field}>
              Label
              <input
                required
                value={form.label}
                onChange={(event) =>
                  setForm({ ...form, label: event.target.value })
                }
                placeholder="Operations manager"
              />
            </label>
            <label className={styles.field}>
              Role
              <input
                required
                value={form.role}
                onChange={(event) =>
                  setForm({ ...form, role: event.target.value })
                }
                placeholder="manager"
              />
            </label>
            <label className={styles.field}>
              WhatsApp number
              <input
                required
                value={form.phone}
                onChange={(event) =>
                  setForm({ ...form, phone: event.target.value })
                }
                placeholder="+92..."
              />
            </label>
            <label className={styles.field}>
              Working hours
              <input
                value={form.working_hours}
                onChange={(event) =>
                  setForm({ ...form, working_hours: event.target.value })
                }
                placeholder="Mon–Sat 10:00–18:00"
              />
            </label>
            <label className={styles.field}>
              Default message
              <textarea
                value={form.whatsapp_message}
                onChange={(event) =>
                  setForm({ ...form, whatsapp_message: event.target.value })
                }
                placeholder="Hello, I need help with..."
              />
            </label>
          </div>
          <div className={styles.formActions}>
            <button className={styles.primaryButton} type="submit">
              Add support contact
            </button>
          </div>
        </form>
        <div className={styles.panel}>
          <h2 className={styles.panelTitle}>Configured contacts</h2>
          {contacts.map((contact) => (
            <div className={styles.cartRow} key={contact.id}>
              <span>
                <strong>{contact.label}</strong>
                <br />
                <span className={styles.muted}>
                  {contact.role} · {contact.phone}
                </span>
              </span>
              <span
                className={`${styles.badge} ${contact.is_active ? styles.badgeSuccess : styles.badgeDanger}`}
              >
                {contact.is_active ? "active" : "inactive"}
              </span>
            </div>
          ))}
          {contacts.length === 0 && (
            <div className={styles.empty}>No support contacts yet.</div>
          )}
        </div>
      </div>
    </>
  );
}
