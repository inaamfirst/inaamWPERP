"use client";

import { useEffect, useState, type FormEvent } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Config = { configured: boolean; site_url: string | null; consumer_key_hint: string | null; wordpress_username: string | null };
type SyncRun = { id: string; status: string; attempts: number; error: string | null; started_at: string; next_attempt_at?: string | null; stats: { sync_mode?: string; retry_at?: string } };
type Conflict = { id: string; entity_type: string; entity_id: string; status: string; summary: string | null };

export default function AdminWoocommerce() {
  const [config, setConfig] = useState<Config | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [form, setForm] = useState({ site_url: "", consumer_key: "", consumer_secret: "", webhook_secret: "", wordpress_username: "", wordpress_application_password: "" });
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  async function load() {
    setLoading(true); setError("");
    try {
      const [nextConfig, nextRuns, nextConflicts] = await Promise.all([fetchApi("/woocommerce/config"), fetchApi("/woocommerce/sync-runs"), fetchApi("/woocommerce/conflicts")]);
      const saved = nextConfig as Config; setConfig(saved); setRuns(nextRuns as SyncRun[]); setConflicts(nextConflicts as Conflict[]);
      setForm((current) => ({ ...current, site_url: current.site_url || saved.site_url || "", wordpress_username: current.wordpress_username || saved.wordpress_username || "" }));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "WooCommerce data could not be loaded."); }
    finally { setLoading(false); }
  }
  // This effect synchronizes the view with the remote WooCommerce API.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, []);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError(""); setMessage("");
    try { const saved = await fetchApi("/woocommerce/config", { method: "PUT", body: JSON.stringify({ ...form, webhook_secret: form.webhook_secret || null, wordpress_username: form.wordpress_username || null, wordpress_application_password: form.wordpress_application_password || null }) }) as Config; setConfig(saved); setForm((current) => ({ ...current, consumer_key: "", consumer_secret: "", webhook_secret: "", wordpress_application_password: "" })); setMessage("WooCommerce configuration saved. Credentials are never displayed after saving."); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "WooCommerce configuration could not be saved."); }
    finally { setSaving(false); }
  }

  async function testConnection() {
    setError(""); setMessage("");
    try { const result = await fetchApi("/woocommerce/test-connection", { method: "POST", body: JSON.stringify({}) }) as { ok: boolean; detail: string }; setMessage(result.detail || (result.ok ? "Connection succeeded." : "Connection failed.")); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Connection test failed."); }
  }

  async function triggerSync() {
    setError(""); setMessage("");
    try { await fetchApi("/woocommerce/sync?mode=incremental", { method: "POST", body: JSON.stringify({}) }); setMessage("Incremental sync queued for the worker."); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Sync could not be queued."); }
  }

  return <>
    <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Commerce connector</div><h1 className={styles.pageTitle}>WooCommerce</h1><p className={styles.pageSubtitle}>Configure the connector, test credentials, queue sync work, and inspect durable sync runs.</p></div><div className={styles.toolbarActions}><button type="button" className={styles.secondaryButton} onClick={() => void testConnection()} disabled={!config?.configured}>Test connection</button><button type="button" className={styles.primaryButton} onClick={() => void triggerSync()} disabled={!config?.configured}>Queue sync</button></div></div>
    {error && <div className={styles.error}>{error}</div>}{message && <div className={styles.notice}>{message}</div>}
    <form className={styles.panel} onSubmit={save}><div className={styles.toolbar}><h2 className={styles.panelTitle}>Connection settings</h2><span className={`${styles.badge} ${config?.configured ? styles.badgeSuccess : styles.badgeWarning}`}>{config?.configured ? "configured" : "not configured"}</span></div><div className={styles.formGrid}><label className={styles.field}>Site URL<input required type="url" value={form.site_url} onChange={(event) => setForm({ ...form, site_url: event.target.value })} placeholder="https://store.example.com" /></label><label className={styles.field}>Consumer key<input required minLength={8} type="password" value={form.consumer_key} onChange={(event) => setForm({ ...form, consumer_key: event.target.value })} placeholder={config?.consumer_key_hint || "Enter new key"} /></label><label className={styles.field}>Consumer secret<input required minLength={8} type="password" value={form.consumer_secret} onChange={(event) => setForm({ ...form, consumer_secret: event.target.value })} placeholder="Enter new secret" /></label><label className={styles.field}>Webhook secret<input minLength={8} type="password" value={form.webhook_secret} onChange={(event) => setForm({ ...form, webhook_secret: event.target.value })} placeholder="Optional" /></label><label className={styles.field}>WordPress username<input value={form.wordpress_username} onChange={(event) => setForm({ ...form, wordpress_username: event.target.value })} /></label><label className={styles.field}>Application password<input minLength={8} type="password" value={form.wordpress_application_password} onChange={(event) => setForm({ ...form, wordpress_application_password: event.target.value })} placeholder="Optional" /></label></div><div className={styles.formActions}><button type="submit" className={styles.primaryButton} disabled={saving}>{saving ? "Saving…" : "Save configuration"}</button></div></form>
    <div className={styles.formGrid}><section className={styles.panel}><div className={styles.toolbar}><h2 className={styles.panelTitle}>Sync runs</h2><span className={styles.muted}>{loading ? "Loading…" : `${runs.length} runs`}</span></div><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Mode</th><th>Status</th><th>Attempts</th><th>Created</th></tr></thead><tbody>{runs.map((run) => <tr key={run.id}><td>{run.stats?.sync_mode || "incremental"}</td><td><span className={styles.badge}>{run.status}</span>{(run.next_attempt_at || run.stats?.retry_at) && <div className={styles.muted}>Rate-limited; retrying at {new Date(run.next_attempt_at || run.stats.retry_at || "").toLocaleString()}</div>}{run.error && <div className={styles.muted}>{run.error}</div>}</td><td>{run.attempts}</td><td>{new Date(run.started_at).toLocaleString()}</td></tr>)}{!loading && runs.length === 0 && <tr><td colSpan={4} className={styles.empty}>No sync runs found.</td></tr>}</tbody></table></div></section><section className={styles.panel}><h2 className={styles.panelTitle}>Open conflicts</h2><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Entity</th><th>ID</th><th>Status</th></tr></thead><tbody>{conflicts.map((conflict) => <tr key={conflict.id}><td>{conflict.entity_type}</td><td>{conflict.entity_id}</td><td>{conflict.status}</td></tr>)}{!loading && conflicts.length === 0 && <tr><td colSpan={3} className={styles.empty}>No unresolved conflicts.</td></tr>}</tbody></table></div></section></div>
  </>;
}
