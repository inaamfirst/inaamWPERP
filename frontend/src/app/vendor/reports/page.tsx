"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type ReportRow = { id?: string; order_number?: string; status?: string; total_minor?: number; paid_minor?: number; payment_status?: string; created_at?: string };

export default function VendorReports() {
  const [rows, setRows] = useState<ReportRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetchApi("/vendor/reports/sales")
      .then((value) => active && setRows(value as ReportRow[]))
      .catch(() => active && setError("Sales report could not be loaded."))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  return (
    <>
      <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Performance analytics</div><h1 className={styles.pageTitle}>Sales reports</h1><p className={styles.pageSubtitle}>Review the sales rows that feed your dashboard and settlements.</p></div></div>
      {error && <div className={styles.error} role="alert">{error}</div>}
      <div className={styles.panel}>
        <div className={styles.tableWrap}>
          <table className={`${styles.table} ${styles.mobileCardTable}`}>
            <thead><tr><th>Reference</th><th>Date</th><th>Status</th><th>Total</th><th>Paid</th><th>Payment</th></tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={6} className={styles.empty}>Loading sales report…</td></tr> : rows.map((row) => <tr key={row.id}>
                <td data-label="Reference"><strong>{row.order_number || row.id?.slice(0, 8)}</strong></td>
                <td data-label="Date">{row.created_at ? new Date(row.created_at).toLocaleDateString() : "—"}</td>
                <td data-label="Status"><span className={styles.badge}>{row.status || "—"}</span></td>
                <td data-label="Total">PKR {((row.total_minor || 0) / 100).toFixed(2)}</td>
                <td data-label="Paid">PKR {((row.paid_minor || 0) / 100).toFixed(2)}</td>
                <td data-label="Payment">{row.payment_status || "—"}</td>
              </tr>)}
              {!loading && rows.length === 0 && <tr><td colSpan={6} className={styles.empty}>No sales report rows found.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
