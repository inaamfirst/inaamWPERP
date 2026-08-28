"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Contact = { id: string; label: string; role: string; phone: string; whatsapp_url: string; working_hours?: string | null; is_active: boolean };

export default function VendorSupport() {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetchApi("/commerce/support/contacts")
      .then((value) => active && setContacts(value as Contact[]))
      .catch(() => active && setError("Support contacts could not be loaded."))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  return (
    <>
      <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Direct help</div><h1 className={styles.pageTitle}>Support contacts</h1><p className={styles.pageSubtitle}>Contact the owner, manager, or support team directly on WhatsApp. Your support directory is managed by the administrator.</p></div></div>
      {error && <div className={styles.error} role="alert">{error}</div>}
      {loading ? <div className={styles.panel}><div className={styles.empty}>Loading support contacts…</div></div> : <div className={styles.supportGrid}>
        {contacts.map((contact) => <div className={styles.panel} key={contact.id}>
          <span className={styles.badge}>{contact.role}</span>
          <h2 className={styles.panelTitle}>{contact.label}</h2>
          <p className={styles.muted}>{contact.phone}</p>
          {contact.working_hours && <p className={styles.muted}>Hours: {contact.working_hours}</p>}
          <div className={styles.formActions}><a className={styles.primaryButton} href={contact.whatsapp_url} target="_blank" rel="noreferrer">Chat on WhatsApp</a></div>
        </div>)}
        {contacts.length === 0 && <div className={styles.panel}><div className={styles.empty}>No active support contacts have been configured.</div></div>}
      </div>}
    </>
  );
}
