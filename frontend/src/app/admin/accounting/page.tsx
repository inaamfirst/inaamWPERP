"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Overview = { cash_balance_minor: number };
type FinanceDashboard = {
  collected_sales_minor: number; pending_cod_minor: number; rider_cash_in_hand_minor: number;
  vendor_payables_minor: number; approved_vendor_payouts_minor: number;
  rider_earnings_payable_minor: number; delivery_expense_minor: number; expenses_minor: number;
  refunds_minor: number; net_operational_profit_minor: number; reconciliation_warnings: number;
};
type Account = { id: string; code: string; name: string; account_type: string; is_active: boolean };
type TrialBalance = { account_id: string; account_code: string; account_name: string; account_type: string; debit_minor: number; credit_minor: number; balance_minor: number };
type Rider = { id: string; username: string; full_name: string | null };
type RiderSummary = { cash_in_hand_minor: number; earnings_payable_minor: number; pending_cod_minor: number };
type RiderProfile = { rider_user_id: string; delivery_fee_minor: number };
type CodCollection = { id: string; order_number: string; rider_name: string | null; expected_minor: number; collected_minor: number; receipt_reference: string; proof_reference: string };
type Remittance = { id: string; rider_name: string | null; amount_minor: number; reference: string; proof_reference: string };
type VendorSale = { id: string; vendor_id: string; order_number: string | null; name: string; payable_minor: number; commission_minor: number; finance_status: string; payment_status: string | null };

const money = (minor: number) => `PKR ${(minor / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}`;
const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });

export default function AdminAccounting() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [finance, setFinance] = useState<FinanceDashboard | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [trialBalance, setTrialBalance] = useState<TrialBalance[]>([]);
  const [collections, setCollections] = useState<CodCollection[]>([]);
  const [remittances, setRemittances] = useState<Remittance[]>([]);
  const [vendorSales, setVendorSales] = useState<VendorSale[]>([]);
  const [riders, setRiders] = useState<Rider[]>([]);
  const [riderSummaries, setRiderSummaries] = useState<Record<string, RiderSummary>>({});
  const [profiles, setProfiles] = useState<Record<string, RiderProfile>>({});
  const [form, setForm] = useState({ code: "", name: "", account_type: "asset" });
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true); setError("");
    try {
      const dashboardParams = new URLSearchParams();
      if (dateFrom) dashboardParams.set("date_from", `${dateFrom}T00:00:00Z`);
      if (dateTo) dashboardParams.set("date_to", `${dateTo}T23:59:59Z`);
      const dashboardPath = `/finance/dashboard${dashboardParams.size ? `?${dashboardParams.toString()}` : ""}`;
      const periodSuffix = dashboardParams.size ? `&${dashboardParams.toString()}` : "";
      const [nextOverview, nextFinance, nextAccounts, nextTrial, nextCollections, nextRemittances, nextSales, nextRiders, nextProfiles] = await Promise.all([
        fetchApi("/ledger/overview"), fetchApi(dashboardPath), fetchApi("/accounting/accounts"), fetchApi("/ledger/trial-balance"),
        fetchApi(`/finance/cod-collections?status=submitted${periodSuffix}`), fetchApi(`/finance/remittances?status=submitted${periodSuffix}`), fetchApi(`/finance/vendor-sales${dashboardParams.size ? `?${dashboardParams.toString()}` : ""}`),
        fetchApi("/delivery/admin/riders"), fetchApi("/finance/riders/profiles"),
      ]);
      const riderRows = nextRiders as Rider[];
      const summaries = await Promise.all(riderRows.map(async (rider) => [rider.id, await fetchApi(`/finance/riders/${rider.id}/summary`)] as const));
      setOverview(nextOverview as Overview); setFinance(nextFinance as FinanceDashboard); setAccounts(nextAccounts as Account[]); setTrialBalance(nextTrial as TrialBalance[]);
      setCollections(nextCollections as CodCollection[]); setRemittances(nextRemittances as Remittance[]); setVendorSales(nextSales as VendorSale[]); setRiders(riderRows);
      setRiderSummaries(Object.fromEntries(summaries) as Record<string, RiderSummary>);
      setProfiles(Object.fromEntries((nextProfiles as RiderProfile[]).map((profile) => [profile.rider_user_id, profile])));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Finance data could not be loaded."); }
    finally { setLoading(false); }
  }

  useEffect(() => { void load(); }, []);

  async function createAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setMessage("");
    try { await fetchApi("/accounting/accounts", { method: "POST", body: JSON.stringify({ ...form, is_active: true }) }); setForm({ code: "", name: "", account_type: "asset" }); setMessage("Account created."); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Account could not be created."); }
  }

  async function reconcile(path: string, accepted: boolean) {
    const reason = accepted ? undefined : window.prompt("Reason for rejection:");
    if (!accepted && !reason) return;
    try { await fetchApi(path, { method: "POST", body: JSON.stringify({ accepted, reason }) }); setMessage(accepted ? "Reconciled successfully." : "Rejected with an audit reason."); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "The finance decision could not be saved."); }
  }

  async function decideVendorSale(sale: VendorSale, approved: boolean) {
    const reason = approved ? window.prompt("Optional approval note:") || undefined : window.prompt("Reason for rejection:");
    if (!approved && !reason) return;
    try { await fetchApi(`/finance/vendor-order-items/${sale.id}/decision`, { method: "POST", body: JSON.stringify({ approved, reason }) }); setMessage(approved ? "Vendor sale approved for payout." : "Vendor sale rejected."); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Vendor decision could not be saved."); }
  }

  async function configureRider(rider: Rider) {
    const current = profiles[rider.id]?.delivery_fee_minor ?? 0;
    const value = window.prompt(`Flat fee per reconciled delivery for ${rider.full_name || rider.username} (PKR):`, String(current / 100));
    if (value === null) return;
    const amountMinor = Math.round(Number(value) * 100);
    if (!Number.isFinite(amountMinor) || amountMinor < 0) { setError("Enter a valid non-negative PKR amount."); return; }
    try { await fetchApi(`/finance/riders/${rider.id}/profile`, { method: "PUT", body: JSON.stringify({ delivery_fee_minor: amountMinor, currency: "PKR", is_active: true }) }); setMessage("Rider delivery fee saved."); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Rider fee could not be saved."); }
  }

  async function riderAdjustment(rider: Rider) {
    const amount = window.prompt("Bonus (+) or deduction (-), PKR:"); const memo = window.prompt("Reason:");
    if (amount === null || !memo) return;
    const amountMinor = Math.round(Number(amount) * 100);
    if (!Number.isFinite(amountMinor) || amountMinor === 0) { setError("Enter a non-zero PKR amount."); return; }
    try { await fetchApi(`/finance/riders/${rider.id}/adjustments`, { method: "POST", body: JSON.stringify({ amount_minor: amountMinor, memo, idempotency_key: `manual-${crypto.randomUUID()}` }) }); setMessage("Rider adjustment posted."); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Rider adjustment could not be posted."); }
  }

  async function riderPayout(rider: Rider) {
    const amount = window.prompt("Payout amount, PKR:"); const reference = window.prompt("Payment reference:");
    if (amount === null || !reference) return;
    const amountMinor = Math.round(Number(amount) * 100);
    if (!Number.isFinite(amountMinor) || amountMinor <= 0) { setError("Enter a valid payout amount."); return; }
    try { await fetchApi(`/finance/riders/${rider.id}/payouts`, { method: "POST", body: JSON.stringify({ amount_minor: amountMinor, payment_reference: reference, idempotency_key: `payout-${crypto.randomUUID()}` }) }); setMessage("Rider payout posted."); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Rider payout could not be posted."); }
  }

  async function createVendorPayout(vendorId: string) {
    const reference = window.prompt("Vendor payout payment reference:");
    if (!reference) return;
    try { await fetchApi("/marketplace/settlements", { method: "POST", body: JSON.stringify({ vendor_id: vendorId, payment_reference: reference, currency: "PKR" }) }); setMessage("Vendor payout batch created and posted."); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Vendor payout batch could not be created."); }
  }

  const eligibleVendorSales = useMemo(() => vendorSales.filter((sale) => sale.finance_status === "eligible"), [vendorSales]);
  const approvedVendorIds = useMemo(() => [...new Set(vendorSales.filter((sale) => sale.finance_status === "approved").map((sale) => sale.vendor_id))], [vendorSales]);
  const cards: Array<[string, number, string]> = [["Net operational profit", finance?.net_operational_profit_minor || 0, "finance-profit"], ["Collected sales", finance?.collected_sales_minor || 0, "finance-cod"], ["Pending COD", finance?.pending_cod_minor || 0, "finance-cod"], ["Rider cash in hand", finance?.rider_cash_in_hand_minor || 0, "finance-remittances"], ["Vendor payable", finance?.vendor_payables_minor || 0, "finance-vendors"], ["Rider earnings payable", finance?.rider_earnings_payable_minor || 0, "finance-riders"]];

  return <>
    <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Financial control centre</div><h1 className={styles.pageTitle}>Finance & accounting</h1><p className={styles.pageSubtitle}>Reconcile rider COD, approve vendor payouts, track rider cash and earnings, and see clear operational profit.</p></div><button type="button" className={styles.secondaryButton} onClick={() => void load()}>Refresh</button></div>
    <div className={styles.toolbar}><div className={styles.toolbarActions}><label className={styles.field}>From<input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label><label className={styles.field}>To<input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label></div><div className={styles.toolbarActions}><button type="button" className={styles.secondaryButton} onClick={() => { setDateFrom(""); setDateTo(""); }}>Clear dates</button><button type="button" className={styles.primaryButton} onClick={() => void load()}>Apply period</button></div></div>
    {error && <div className={styles.error}>{error}</div>}{message && <div className={styles.notice}>{message}</div>}
    {loading ? <div className={styles.empty}>Loading finance workspace…</div> : <>
      <div className={styles.metricGrid}>{cards.map(([label, value, target]) => <button type="button" className={styles.metricCard} key={label} onClick={() => scrollTo(target)}><div className={styles.metricLabel}>{label}</div><div className={styles.metricValue}>{money(value)}</div></button>)}</div>
      <div className={styles.notice}>Reconciliation warnings: <strong>{finance?.reconciliation_warnings || 0}</strong> · Cash and bank: <strong>{money(overview?.cash_balance_minor || 0)}</strong></div>

      <section className={styles.panel} id="finance-cod"><div className={styles.toolbar}><div><h2 className={styles.panelTitle}>COD awaiting reconciliation</h2><p className={styles.muted}>Only accepted COD becomes an order payment and may make a delivered vendor sale eligible for approval.</p></div><span className={styles.badge}>{collections.length} pending</span></div><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Order</th><th>Rider</th><th>Expected</th><th>Collected</th><th>Receipt / proof</th><th>Decision</th></tr></thead><tbody>{collections.map((collection) => <tr key={collection.id}><td>{collection.order_number}</td><td>{collection.rider_name || "—"}</td><td>{money(collection.expected_minor)}</td><td>{money(collection.collected_minor)}</td><td>{collection.receipt_reference}<br /><span className={styles.muted}>{collection.proof_reference}</span></td><td><div className={styles.toolbarActions}><button type="button" className={styles.primaryButton} onClick={() => void reconcile(`/finance/cod-collections/${collection.id}/reconcile`, true)}>Accept</button><button type="button" className={styles.dangerButton} onClick={() => void reconcile(`/finance/cod-collections/${collection.id}/reconcile`, false)}>Reject</button></div></td></tr>)}{collections.length === 0 && <tr><td colSpan={6} className={styles.empty}>No COD collections need review.</td></tr>}</tbody></table></div></section>

      <section className={styles.panel} id="finance-remittances"><div className={styles.toolbar}><div><h2 className={styles.panelTitle}>Rider cash remittances</h2><p className={styles.muted}>Accepting a remittance transfers cash from the rider to company clearing.</p></div><span className={styles.badge}>{remittances.length} pending</span></div><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Rider</th><th>Amount</th><th>Reference / proof</th><th>Decision</th></tr></thead><tbody>{remittances.map((remittance) => <tr key={remittance.id}><td>{remittance.rider_name || "—"}</td><td>{money(remittance.amount_minor)}</td><td>{remittance.reference}<br /><span className={styles.muted}>{remittance.proof_reference}</span></td><td><div className={styles.toolbarActions}><button type="button" className={styles.primaryButton} onClick={() => void reconcile(`/finance/remittances/${remittance.id}/reconcile`, true)}>Accept</button><button type="button" className={styles.dangerButton} onClick={() => void reconcile(`/finance/remittances/${remittance.id}/reconcile`, false)}>Reject</button></div></td></tr>)}{remittances.length === 0 && <tr><td colSpan={4} className={styles.empty}>No rider remittances need review.</td></tr>}</tbody></table></div></section>

      <section className={styles.panel} id="finance-vendors"><div className={styles.toolbar}><div><h2 className={styles.panelTitle}>Vendor sales awaiting approval</h2><p className={styles.muted}>Approval creates the vendor payable. Only approved sales can enter a settlement.</p></div><span className={styles.badge}>{eligibleVendorSales.length} eligible</span></div>{approvedVendorIds.length > 0 && <div className={styles.toolbarActions}>{approvedVendorIds.map((vendorId) => <button key={vendorId} type="button" className={styles.secondaryButton} onClick={() => void createVendorPayout(vendorId)}>Create vendor payout batch</button>)}</div>}<div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Order</th><th>Product</th><th>Payment</th><th>Vendor payable</th><th>Commission</th><th>Decision</th></tr></thead><tbody>{eligibleVendorSales.map((sale) => <tr key={sale.id}><td>{sale.order_number || "—"}</td><td>{sale.name}</td><td>{sale.payment_status || "—"}</td><td>{money(sale.payable_minor)}</td><td>{money(sale.commission_minor)}</td><td><div className={styles.toolbarActions}><button type="button" className={styles.primaryButton} onClick={() => void decideVendorSale(sale, true)}>Approve</button><button type="button" className={styles.dangerButton} onClick={() => void decideVendorSale(sale, false)}>Reject</button></div></td></tr>)}{eligibleVendorSales.length === 0 && <tr><td colSpan={6} className={styles.empty}>No vendor sales are ready for finance approval.</td></tr>}</tbody></table></div></section>

      <section className={styles.panel} id="finance-riders"><div className={styles.toolbar}><div><h2 className={styles.panelTitle}>Rider cash, earnings, and payouts</h2><p className={styles.muted}>Set flat delivery fees, then pay only the reconciled earnings balance.</p></div></div><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Rider</th><th>Delivery fee</th><th>Cash in hand</th><th>Pending COD</th><th>Earnings payable</th><th>Actions</th></tr></thead><tbody>{riders.map((rider) => { const summary = riderSummaries[rider.id]; return <tr key={rider.id}><td>{rider.full_name || rider.username}</td><td>{money(profiles[rider.id]?.delivery_fee_minor || 0)}</td><td>{money(summary?.cash_in_hand_minor || 0)}</td><td>{money(summary?.pending_cod_minor || 0)}</td><td>{money(summary?.earnings_payable_minor || 0)}</td><td><div className={styles.toolbarActions}><button type="button" className={styles.secondaryButton} onClick={() => void configureRider(rider)}>Fee</button><button type="button" className={styles.secondaryButton} onClick={() => void riderAdjustment(rider)}>Adjust</button><button type="button" className={styles.primaryButton} onClick={() => void riderPayout(rider)}>Payout</button></div></td></tr>; })}{riders.length === 0 && <tr><td colSpan={6} className={styles.empty}>No active riders found.</td></tr>}</tbody></table></div></section>

      <section className={styles.panel} id="finance-profit"><div className={styles.toolbar}><h2 className={styles.panelTitle}>Profit composition</h2><span className={styles.muted}>Collected sales less approved vendor cost, rider delivery cost, refunds, and paid expenses.</span></div><div className={styles.metricGrid}>{[["Sales", finance?.collected_sales_minor || 0], ["Vendor cost", -(finance?.approved_vendor_payouts_minor || 0)], ["Rider delivery cost", -(finance?.delivery_expense_minor || 0)], ["Business expenses", -(finance?.expenses_minor || 0)], ["Refunds", -(finance?.refunds_minor || 0)], ["Net profit", finance?.net_operational_profit_minor || 0]].map(([label, value]) => <div className={styles.metricCard} key={String(label)}><div className={styles.metricLabel}>{label}</div><div className={styles.metricValue}>{money(Number(value))}</div></div>)}</div></section>

      <div className={styles.formGrid}><form className={styles.panel} onSubmit={createAccount}><h2 className={styles.panelTitle}>Add chart-of-accounts entry</h2><label className={styles.field}>Code<input required value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value })} /></label><label className={styles.field}>Name<input required minLength={2} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label className={styles.field}>Type<select value={form.account_type} onChange={(event) => setForm({ ...form, account_type: event.target.value })}><option value="asset">Asset</option><option value="liability">Liability</option><option value="equity">Equity</option><option value="income">Income</option><option value="expense">Expense</option></select></label><div className={styles.formActions}><button type="submit" className={styles.primaryButton}>Create account</button></div></form><section className={styles.panel}><h2 className={styles.panelTitle}>Chart of accounts</h2><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Code</th><th>Name</th><th>Type</th><th>State</th></tr></thead><tbody>{accounts.map((account) => <tr key={account.id}><td>{account.code}</td><td>{account.name}</td><td>{account.account_type}</td><td>{account.is_active ? "Active" : "Inactive"}</td></tr>)}</tbody></table></div></section></div>
      <section className={styles.panel}><h2 className={styles.panelTitle}>Trial balance</h2><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Account</th><th>Type</th><th>Debit</th><th>Credit</th><th>Balance</th></tr></thead><tbody>{trialBalance.map((row) => <tr key={row.account_id}><td>{row.account_code} — {row.account_name}</td><td>{row.account_type}</td><td>{money(row.debit_minor)}</td><td>{money(row.credit_minor)}</td><td>{money(row.balance_minor)}</td></tr>)}{trialBalance.length === 0 && <tr><td colSpan={5} className={styles.empty}>No trial-balance rows found.</td></tr>}</tbody></table></div></section>
    </>}
  </>;
}
