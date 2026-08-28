"use client";

import { useEffect, useState, type FormEvent } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Overview = { assets_minor: number; liabilities_minor: number; equity_minor: number; income_minor: number; expenses_minor: number; cash_balance_minor: number; inventory_value_minor: number; vendor_payables_minor: number };
type Account = { id: string; code: string; name: string; account_type: string; is_active: boolean };
type TrialBalance = { account_id: string; account_code: string; account_name: string; account_type: string; debit_minor: number; credit_minor: number; balance_minor: number };

const money = (minor: number) => `PKR ${(minor / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}`;

export default function AdminAccounting() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [trialBalance, setTrialBalance] = useState<TrialBalance[]>([]);
  const [form, setForm] = useState({ code: "", name: "", account_type: "asset" });
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true); setError("");
    try { const [nextOverview, nextAccounts, nextTrial] = await Promise.all([fetchApi("/ledger/overview"), fetchApi("/accounting/accounts"), fetchApi("/ledger/trial-balance")]); setOverview(nextOverview as Overview); setAccounts(nextAccounts as Account[]); setTrialBalance(nextTrial as TrialBalance[]); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Accounting data could not be loaded."); }
    finally { setLoading(false); }
  }
  // This effect synchronizes the view with the remote accounting API.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, []);

  async function createAccount(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(""); setMessage("");
    try { await fetchApi("/accounting/accounts", { method: "POST", body: JSON.stringify({ ...form, is_active: true }) }); setForm({ code: "", name: "", account_type: "asset" }); setMessage("Account created."); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Account could not be created."); }
  }

  return <>
    <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Financial controls</div><h1 className={styles.pageTitle}>Accounting</h1><p className={styles.pageSubtitle}>View the ledger overview, maintain the chart of accounts, and inspect the current trial balance.</p></div><button type="button" className={styles.secondaryButton} onClick={() => void load()}>Refresh</button></div>
    {error && <div className={styles.error}>{error}</div>}{message && <div className={styles.notice}>{message}</div>}
    {loading ? <div className={styles.empty}>Loading accounting data…</div> : <><div className={styles.metricGrid}>{[["Assets", overview?.assets_minor || 0], ["Liabilities", overview?.liabilities_minor || 0], ["Cash", overview?.cash_balance_minor || 0], ["Inventory", overview?.inventory_value_minor || 0], ["Vendor payables", overview?.vendor_payables_minor || 0], ["Income", overview?.income_minor || 0]].map(([label, value]) => <div className={styles.metricCard} key={String(label)}><div className={styles.metricLabel}>{label}</div><div className={styles.metricValue}>{money(Number(value))}</div></div>)}</div><div className={styles.formGrid}><form className={styles.panel} onSubmit={createAccount}><h2 className={styles.panelTitle}>Add chart-of-accounts entry</h2><label className={styles.field}>Code<input required value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value })} /></label><label className={styles.field}>Name<input required minLength={2} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label className={styles.field}>Type<select value={form.account_type} onChange={(event) => setForm({ ...form, account_type: event.target.value })}><option value="asset">Asset</option><option value="liability">Liability</option><option value="equity">Equity</option><option value="income">Income</option><option value="expense">Expense</option></select></label><div className={styles.formActions}><button type="submit" className={styles.primaryButton}>Create account</button></div></form><section className={styles.panel}><h2 className={styles.panelTitle}>Chart of accounts</h2><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Code</th><th>Name</th><th>Type</th><th>State</th></tr></thead><tbody>{accounts.map((account) => <tr key={account.id}><td>{account.code}</td><td>{account.name}</td><td>{account.account_type}</td><td>{account.is_active ? "Active" : "Inactive"}</td></tr>)}{accounts.length === 0 && <tr><td colSpan={4} className={styles.empty}>No accounts found.</td></tr>}</tbody></table></div></section></div><section className={styles.panel}><h2 className={styles.panelTitle}>Trial balance</h2><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Account</th><th>Type</th><th>Debit</th><th>Credit</th><th>Balance</th></tr></thead><tbody>{trialBalance.map((row) => <tr key={row.account_id}><td>{row.account_code} — {row.account_name}</td><td>{row.account_type}</td><td>{money(row.debit_minor)}</td><td>{money(row.credit_minor)}</td><td>{money(row.balance_minor)}</td></tr>)}{trialBalance.length === 0 && <tr><td colSpan={5} className={styles.empty}>No trial-balance rows found.</td></tr>}</tbody></table></div></section></>}
  </>;
}
