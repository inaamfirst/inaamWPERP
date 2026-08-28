"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Ledger = { balance_minor?: number; payable_minor?: number; settled_minor?: number; [key: string]: unknown };

export default function VendorLedger() {
  const [data, setData] = useState<Ledger | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetchApi("/commerce/vendor/ledger/overview")
      .then((value) => active && setData(value as Ledger))
      .catch(() => active && setError("Ledger overview could not be loaded."))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  return (
    <>
      <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Financial workspace</div><h1 className={styles.pageTitle}>Your ledger</h1><p className={styles.pageSubtitle}>Shop payments, online marketplace payable, settlements, and balances stay separated from other vendors and company-only accounts.</p></div></div>
      {error && <div className={styles.error} role="alert">{error}</div>}
      <div className={styles.metricGrid}>
        {loading ? <div className={styles.panel}><div className={styles.empty}>Loading ledger…</div></div> : Object.entries(data || {}).map(([key, value]) => <div className={styles.metricCard} key={key}><div className={styles.metricLabel}>{key.replaceAll("_", " ")}</div><div className={styles.metricValue}>{typeof value === "number" && key.includes("minor") ? `PKR ${(value / 100).toFixed(2)}` : String(value)}</div></div>)}
      </div>
      <div className={styles.panel}><h2 className={styles.panelTitle}>Accounting rule</h2><p className={styles.muted}>Posted journals are immutable. Refunds and corrections create reversals, so the ledger remains auditable.</p></div>
    </>
  );
}
