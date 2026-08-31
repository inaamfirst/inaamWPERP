"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Overview = { balance_minor: number; payable_minor: number; settled_minor: number };
type LedgerEntry = { id: string; entry_type: string; amount_minor: number; balance_minor: number; memo: string | null; created_at: string };
type Sale = { id: string; order_number: string | null; name: string; quantity: number; line_total_minor: number; commission_minor: number; payable_minor: number; payment_status: string | null; finance_status: string; created_at: string };
type Settlement = { id: string; settlement_number: string; status: string; payable_minor: number; paid_minor: number; payment_reference: string | null; paid_at: string | null };

const money = (minor: number) => `PKR ${(minor / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}`;

function downloadCsv(sales: Sale[]) {
  const rows = [
    ["Order", "Product", "Quantity", "Sale", "Commission", "Approved/Paid balance", "Payment", "Finance state"],
    ...sales.map((sale) => [sale.order_number || "", sale.name, String(sale.quantity), (sale.line_total_minor / 100).toFixed(2), (sale.commission_minor / 100).toFixed(2), (sale.payable_minor / 100).toFixed(2), sale.payment_status || "", sale.finance_status]),
  ];
  const csv = rows.map((row) => row.map((cell) => `"${cell.replaceAll('"', '""')}"`).join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "vendor-sales-ledger.csv";
  link.click();
  URL.revokeObjectURL(url);
}

export default function VendorLedger() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [sales, setSales] = useState<Sale[]>([]);
  const [settlements, setSettlements] = useState<Settlement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [nextOverview, nextEntries, nextSales, nextSettlements] = await Promise.all([
        fetchApi("/commerce/vendor/ledger/overview"),
        fetchApi("/vendor/ledger/entries"),
        fetchApi("/vendor/sales"),
        fetchApi("/vendor/reports/settlements"),
      ]);
      setOverview(nextOverview as Overview);
      setEntries(nextEntries as LedgerEntry[]);
      setSales(nextSales as Sale[]);
      setSettlements(nextSettlements as Settlement[]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Your financial records could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  return <>
    <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Financial workspace</div><h1 className={styles.pageTitle}>Sales, approval & settlement ledger</h1><p className={styles.pageSubtitle}>See each sale, its commission, finance decision, payout status, and immutable ledger history in one place.</p></div><button className={styles.secondaryButton} type="button" onClick={() => void load()}>Refresh</button></div>
    {error && <div className={styles.error} role="alert">{error}</div>}
    <div className={styles.metricGrid}>
      {loading ? <div className={styles.panel}><div className={styles.empty}>Loading ledger...</div></div> : <>
        <div className={styles.metricCard}><div className={styles.metricLabel}>Current balance</div><div className={styles.metricValue}>{money(overview?.balance_minor || 0)}</div></div>
        <div className={styles.metricCard}><div className={styles.metricLabel}>Approved payable</div><div className={styles.metricValue}>{money(overview?.payable_minor || 0)}</div></div>
        <div className={styles.metricCard}><div className={styles.metricLabel}>Settled</div><div className={styles.metricValue}>{money(overview?.settled_minor || 0)}</div></div>
      </>}
    </div>
    <section className={styles.panel}>
      <div className={styles.toolbar}><div><h2 className={styles.panelTitle}>Order-level sales</h2><p className={styles.muted}>A sale waits for successful delivery, reconciled payment, and an admin finance decision before payout.</p></div><button className={styles.secondaryButton} type="button" onClick={() => downloadCsv(sales)} disabled={!sales.length}>Export CSV</button></div>
      <div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Order</th><th>Product</th><th>Sale</th><th>Commission</th><th>Payable</th><th>Payment</th><th>Approval</th></tr></thead><tbody>
        {sales.map((sale) => <tr key={sale.id}><td>{sale.order_number || "-"}</td><td>{sale.name} x{sale.quantity}</td><td>{money(sale.line_total_minor)}</td><td>{money(sale.commission_minor)}</td><td>{money(sale.payable_minor)}</td><td>{sale.payment_status || "pending"}</td><td><span className={styles.badge}>{sale.finance_status}</span></td></tr>)}
        {!sales.length && <tr><td colSpan={7} className={styles.empty}>No marketplace sales yet.</td></tr>}
      </tbody></table></div>
    </section>
    <section className={styles.panel}><h2 className={styles.panelTitle}>Settlement history</h2><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Settlement</th><th>Status</th><th>Approved</th><th>Paid</th><th>Reference</th><th>Paid at</th></tr></thead><tbody>
      {settlements.map((settlement) => <tr key={settlement.id}><td>{settlement.settlement_number}</td><td><span className={styles.badge}>{settlement.status}</span></td><td>{money(settlement.payable_minor)}</td><td>{money(settlement.paid_minor)}</td><td>{settlement.payment_reference || "-"}</td><td>{settlement.paid_at ? new Date(settlement.paid_at).toLocaleDateString() : "-"}</td></tr>)}
      {!settlements.length && <tr><td colSpan={6} className={styles.empty}>No settlements have been paid yet.</td></tr>}
    </tbody></table></div></section>
    <section className={styles.panel}><h2 className={styles.panelTitle}>Ledger history</h2><p className={styles.muted}>Posted entries are immutable. Corrections and refunds appear as separate reversals.</p><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Date</th><th>Type</th><th>Details</th><th>Amount</th><th>Running balance</th></tr></thead><tbody>
      {entries.map((entry) => <tr key={entry.id}><td>{new Date(entry.created_at).toLocaleDateString()}</td><td>{entry.entry_type}</td><td>{entry.memo || "-"}</td><td>{money(entry.amount_minor)}</td><td>{money(entry.balance_minor)}</td></tr>)}
      {!entries.length && <tr><td colSpan={5} className={styles.empty}>No ledger entries yet.</td></tr>}
    </tbody></table></div></section>
  </>;
}
