"use client";

import { useEffect, useState, type FormEvent } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Summary = { cash_in_hand_minor: number; earnings_payable_minor: number; pending_cod_minor: number };
type Collection = { id: string; order_number: string; expected_minor: number; collected_minor: number; accepted_minor: number | null; receipt_reference: string; proof_reference: string; status: string; created_at: string };
type Remittance = { id: string; amount_minor: number; reference: string; proof_reference: string; status: string; created_at: string };
type LedgerRow = { id: string; entry_type: string; amount_minor: number; balance_minor: number; memo: string | null; created_at: string };
type Payout = { id: string; payout_number: string; amount_minor: number; payment_reference: string; paid_at: string };
type Delivery = { id: string; order_number: string; order_total_minor: number; payment_status: string; status: string };

const money = (minor: number) => `PKR ${(minor / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}`;

export default function RiderFinancePage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [remittances, setRemittances] = useState<Remittance[]>([]);
  const [ledger, setLedger] = useState<LedgerRow[]>([]);
  const [payouts, setPayouts] = useState<Payout[]>([]);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [collectionForm, setCollectionForm] = useState({ delivery_assignment_id: "", collected: "", receipt_reference: "", proof_reference: "" });
  const [remittanceForm, setRemittanceForm] = useState({ amount: "", reference: "", proof_reference: "" });
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true); setError("");
    try {
      const [nextSummary, nextCollections, nextRemittances, nextLedger, nextPayouts, nextDeliveries] = await Promise.all([
        fetchApi("/rider/finance/summary"), fetchApi("/rider/finance/cod-collections"), fetchApi("/rider/finance/remittances"),
        fetchApi("/rider/finance/ledger"), fetchApi("/rider/finance/payouts"), fetchApi("/delivery/rider/assignments"),
      ]);
      setSummary(nextSummary as Summary); setCollections(nextCollections as Collection[]); setRemittances(nextRemittances as Remittance[]);
      setLedger(nextLedger as LedgerRow[]); setPayouts(nextPayouts as Payout[]); setDeliveries(nextDeliveries as Delivery[]);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Your financial data could not be loaded."); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);

  async function submitCollection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setMessage("");
    const collectedMinor = Math.round(Number(collectionForm.collected) * 100);
    if (!Number.isFinite(collectedMinor) || collectedMinor <= 0) { setError("Enter the cash collected in PKR."); return; }
    try {
      await fetchApi("/rider/finance/cod-collections", { method: "POST", body: JSON.stringify({ ...collectionForm, collected_minor: collectedMinor, idempotency_key: `cod-${crypto.randomUUID()}` }) });
      setCollectionForm({ delivery_assignment_id: "", collected: "", receipt_reference: "", proof_reference: "" }); setMessage("COD submitted for admin reconciliation."); await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "COD could not be submitted."); }
  }

  async function submitRemittance(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setMessage("");
    const amountMinor = Math.round(Number(remittanceForm.amount) * 100);
    if (!Number.isFinite(amountMinor) || amountMinor <= 0) { setError("Enter the remitted cash in PKR."); return; }
    try {
      await fetchApi("/rider/finance/remittances", { method: "POST", body: JSON.stringify({ amount_minor: amountMinor, reference: remittanceForm.reference, proof_reference: remittanceForm.proof_reference, idempotency_key: `remit-${crypto.randomUUID()}` }) });
      setRemittanceForm({ amount: "", reference: "", proof_reference: "" }); setMessage("Cash remittance submitted for admin reconciliation."); await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Cash remittance could not be submitted."); }
  }

  const deliverableCod = deliveries.filter((delivery) => delivery.status === "delivered" && delivery.payment_status !== "paid" && !collections.some((collection) => collection.order_number === delivery.order_number));

  return <>
    <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Rider finance</div><h1 className={styles.pageTitle}>Cash, earnings & payouts</h1><p className={styles.pageSubtitle}>Submit delivered COD with proof, hand in cash, and see exactly what you have earned and been paid.</p></div><button className={styles.secondaryButton} type="button" onClick={() => void load()}>Refresh</button></div>
    {error && <div className={styles.error}>{error}</div>}{message && <div className={styles.notice}>{message}</div>}
    {loading ? <div className={styles.empty}>Loading rider finance…</div> : <>
      <div className={styles.metricGrid}>{[["Cash in hand", summary?.cash_in_hand_minor || 0], ["Pending COD review", summary?.pending_cod_minor || 0], ["Earnings payable", summary?.earnings_payable_minor || 0]].map(([label, value]) => <div className={styles.metricCard} key={String(label)}><div className={styles.metricLabel}>{label}</div><div className={styles.metricValue}>{money(Number(value))}</div></div>)}</div>
      <div className={styles.formGrid}>
        <form className={styles.panel} onSubmit={submitCollection}><h2 className={styles.panelTitle}>Submit COD collection</h2><p className={styles.muted}>A receipt/reference and proof link or photo reference are required. Admin must accept it before the order is paid.</p><label className={styles.field}>Delivered order<select required value={collectionForm.delivery_assignment_id} onChange={(event) => setCollectionForm({ ...collectionForm, delivery_assignment_id: event.target.value })}><option value="">Select delivered order</option>{deliverableCod.map((delivery) => <option key={delivery.id} value={delivery.id}>{delivery.order_number} · Expected {money(delivery.order_total_minor)}</option>)}</select></label><label className={styles.field}>Cash collected (PKR)<input required inputMode="decimal" value={collectionForm.collected} onChange={(event) => setCollectionForm({ ...collectionForm, collected: event.target.value })} /></label><label className={styles.field}>Receipt/reference<input required value={collectionForm.receipt_reference} onChange={(event) => setCollectionForm({ ...collectionForm, receipt_reference: event.target.value })} /></label><label className={styles.field}>Proof reference or photo link<input required value={collectionForm.proof_reference} onChange={(event) => setCollectionForm({ ...collectionForm, proof_reference: event.target.value })} /></label><div className={styles.formActions}><button type="submit" className={styles.primaryButton}>Submit COD</button></div></form>
        <form className={styles.panel} onSubmit={submitRemittance}><h2 className={styles.panelTitle}>Hand in collected cash</h2><p className={styles.muted}>Submit the amount you gave to the office/bank with the handover proof. It stays pending until finance accepts it.</p><label className={styles.field}>Amount (PKR)<input required inputMode="decimal" value={remittanceForm.amount} onChange={(event) => setRemittanceForm({ ...remittanceForm, amount: event.target.value })} /></label><label className={styles.field}>Handover reference<input required value={remittanceForm.reference} onChange={(event) => setRemittanceForm({ ...remittanceForm, reference: event.target.value })} /></label><label className={styles.field}>Proof reference or photo link<input required value={remittanceForm.proof_reference} onChange={(event) => setRemittanceForm({ ...remittanceForm, proof_reference: event.target.value })} /></label><div className={styles.formActions}><button type="submit" className={styles.primaryButton}>Submit remittance</button></div></form>
      </div>
      <section className={styles.panel}><h2 className={styles.panelTitle}>COD collection history</h2><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Order</th><th>Expected</th><th>Submitted</th><th>Accepted</th><th>Reference</th><th>Status</th></tr></thead><tbody>{collections.map((collection) => <tr key={collection.id}><td>{collection.order_number}</td><td>{money(collection.expected_minor)}</td><td>{money(collection.collected_minor)}</td><td>{collection.accepted_minor === null ? "—" : money(collection.accepted_minor)}</td><td>{collection.receipt_reference}</td><td><span className={styles.badge}>{collection.status}</span></td></tr>)}{collections.length === 0 && <tr><td colSpan={6} className={styles.empty}>No COD collections yet.</td></tr>}</tbody></table></div></section>
      <section className={styles.panel}><h2 className={styles.panelTitle}>Cash remittance history</h2><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Amount</th><th>Reference</th><th>Proof</th><th>Status</th></tr></thead><tbody>{remittances.map((remittance) => <tr key={remittance.id}><td>{money(remittance.amount_minor)}</td><td>{remittance.reference}</td><td>{remittance.proof_reference}</td><td><span className={styles.badge}>{remittance.status}</span></td></tr>)}{remittances.length === 0 && <tr><td colSpan={4} className={styles.empty}>No remittances yet.</td></tr>}</tbody></table></div></section>
      <section className={styles.panel}><h2 className={styles.panelTitle}>Earnings statement</h2><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Date</th><th>Type</th><th>Details</th><th>Amount</th><th>Balance</th></tr></thead><tbody>{ledger.map((row) => <tr key={row.id}><td>{new Date(row.created_at).toLocaleDateString()}</td><td>{row.entry_type}</td><td>{row.memo || "—"}</td><td>{money(row.amount_minor)}</td><td>{money(row.balance_minor)}</td></tr>)}{ledger.length === 0 && <tr><td colSpan={5} className={styles.empty}>Your earnings will appear after COD is reconciled.</td></tr>}</tbody></table></div></section>
      <section className={styles.panel}><h2 className={styles.panelTitle}>Payout history</h2><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Date</th><th>Payout</th><th>Reference</th><th>Amount</th></tr></thead><tbody>{payouts.map((payout) => <tr key={payout.id}><td>{new Date(payout.paid_at).toLocaleDateString()}</td><td>{payout.payout_number}</td><td>{payout.payment_reference}</td><td>{money(payout.amount_minor)}</td></tr>)}{payouts.length === 0 && <tr><td colSpan={4} className={styles.empty}>No payouts yet.</td></tr>}</tbody></table></div></section>
    </>}
  </>;
}
