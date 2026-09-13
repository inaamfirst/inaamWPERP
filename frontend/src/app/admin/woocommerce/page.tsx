"use client";

import { useEffect, useState, type FormEvent } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Config = {
  configured: boolean;
  site_url: string | null;
  consumer_key_hint: string | null;
  wordpress_username: string | null;
  wordpress_media_configured: boolean;
  failed_media_pushes: number;
  pending_media_pushes: number;
  last_media_error: string | null;
};
type SyncRun = { id: string; status: string; attempts: number; error: string | null; started_at: string; next_attempt_at?: string | null; stats: { sync_mode?: string; retry_at?: string } };
type Conflict = { id: string; entity_type: string; entity_id: string; status: string; summary: string | null };
type MediaFailure = { id: string; product_id: string; product_name: string; sku: string | null; status: string; attempts: number; next_attempt_at: string | null; last_error: string | null; updated_at: string };

export default function AdminWoocommerce() {
  const [config, setConfig] = useState<Config | null>(null);
  const [runs, setRuns] = useState<SyncRun[]>([]);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [mediaFailures, setMediaFailures] = useState<MediaFailure[]>([]);
  const [form, setForm] = useState({ site_url: "", consumer_key: "", consumer_secret: "", webhook_secret: "", wordpress_username: "", wordpress_application_password: "" });
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [retrying, setRetrying] = useState<string | null>(null);

  async function load() {
    setLoading(true); setError("");
    try {
      const [nextConfig, nextRuns, nextConflicts, nextMediaFailures] = await Promise.all([
        fetchApi("/woocommerce/config"), fetchApi("/woocommerce/sync-runs"),
        fetchApi("/woocommerce/conflicts"), fetchApi("/woocommerce/media-sync-failures"),
      ]);
      const saved = nextConfig as Config;
      setConfig(saved); setRuns(nextRuns as SyncRun[]); setConflicts(nextConflicts as Conflict[]);
      setMediaFailures(nextMediaFailures as MediaFailure[]);
      setForm((current) => ({ ...current, site_url: current.site_url || saved.site_url || "", wordpress_username: current.wordpress_username || saved.wordpress_username || "" }));
    } catch (caught) { setError(caught instanceof Error ? caught.message : "WooCommerce data could not be loaded."); }
    finally { setLoading(false); }
  }
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, []);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setSaving(true); setError(""); setMessage("");
    try {
      const saved = await fetchApi("/woocommerce/config", { method: "PUT", body: JSON.stringify({ ...form, webhook_secret: form.webhook_secret || null, wordpress_username: form.wordpress_username || null, wordpress_application_password: form.wordpress_application_password || null }) }) as Config;
      setConfig(saved); setForm((current) => ({ ...current, consumer_key: "", consumer_secret: "", webhook_secret: "", wordpress_application_password: "" }));
      setMessage("WooCommerce configuration saved. Credentials are never displayed after saving.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "WooCommerce configuration could not be saved."); }
    finally { setSaving(false); }
  }

  async function testConnection() {
    setError(""); setMessage("");
    try { const result = await fetchApi("/woocommerce/test-connection", { method: "POST", body: JSON.stringify({}) }) as { ok: boolean; detail: string }; setMessage(result.detail || (result.ok ? "Connection succeeded." : "Connection failed.")); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Connection test failed."); }
  }

  async function triggerSync() {
    setError(""); setMessage("");
    try { await fetchApi("/woocommerce/sync?mode=incremental", { method: "POST", body: JSON.stringify({}) }); setMessage("Sync queued for the worker."); await load(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Sync could not be queued."); }
  }

  async function retryMedia(productId?: string) {
    setRetrying(productId || "all"); setError(""); setMessage("");
    try {
      const path = productId ? `/woocommerce/media-sync-failures/${encodeURIComponent(productId)}/retry` : "/woocommerce/media-sync-failures/retry-all";
      const result = await fetchApi(path, { method: "POST", body: JSON.stringify({}) }) as { queued_products: number };
      setMessage(result.queued_products ? `${result.queued_products} product image sync ${result.queued_products === 1 ? "was" : "were"} queued.` : "No failed product image syncs need retrying.");
      await load();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Image retry could not be queued."); }
    finally { setRetrying(null); }
  }

  return <>
    <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Commerce connector</div><h1 className={styles.pageTitle}>WooCommerce</h1><p className={styles.pageSubtitle}>Configure the connector, publish products and images, and inspect secure sync diagnostics.</p></div><div className={styles.toolbarActions}><button type="button" className={styles.secondaryButton} onClick={() => void testConnection()} disabled={!config?.configured}>Test connection</button><button type="button" className={styles.primaryButton} onClick={() => void triggerSync()} disabled={!config?.configured}>Queue sync</button></div></div>
    {error && <div className={styles.error} role="alert">{error}</div>}{message && <div className={styles.notice} role="status">{message}</div>}
    <form className={styles.panel} onSubmit={save}><div className={styles.toolbar}><h2 className={styles.panelTitle}>Connection settings</h2><span className={`${styles.badge} ${config?.configured ? styles.badgeSuccess : styles.badgeWarning}`}>{config?.configured ? "configured" : "not configured"}</span></div><div className={styles.formGrid}><label className={styles.field}>Site URL<input required type="url" value={form.site_url} onChange={(event) => setForm({ ...form, site_url: event.target.value })} placeholder="https://store.example.com" /></label><label className={styles.field}>Consumer key<input required minLength={8} type="password" value={form.consumer_key} onChange={(event) => setForm({ ...form, consumer_key: event.target.value })} placeholder={config?.consumer_key_hint || "Enter new key"} /></label><label className={styles.field}>Consumer secret<input required minLength={8} type="password" value={form.consumer_secret} onChange={(event) => setForm({ ...form, consumer_secret: event.target.value })} placeholder="Enter new secret" /></label><label className={styles.field}>Webhook secret<input minLength={8} type="password" value={form.webhook_secret} onChange={(event) => setForm({ ...form, webhook_secret: event.target.value })} placeholder="Optional" /></label><label className={styles.field}>WordPress username<input value={form.wordpress_username} onChange={(event) => setForm({ ...form, wordpress_username: event.target.value })} /></label><label className={styles.field}>Application password<input minLength={8} type="password" value={form.wordpress_application_password} onChange={(event) => setForm({ ...form, wordpress_application_password: event.target.value })} placeholder="Required for local ERP image uploads" /></label></div><p className={styles.muted}>{config?.wordpress_media_configured ? "WordPress Media upload is configured." : "Add a WordPress username and application password to publish images stored in the ERP."}</p><div className={styles.formActions}><button type="submit" className={styles.primaryButton} disabled={saving}>{saving ? "Saving…" : "Save configuration"}</button></div></form>
    <section className={styles.panel}><div className={styles.toolbar}><div><h2 className={styles.panelTitle}>Product image sync problems</h2><p className={styles.muted}>Failed images are safe to retry. Credentials and private data are never shown here.</p></div><button type="button" className={styles.secondaryButton} disabled={!mediaFailures.length || retrying !== null} onClick={() => void retryMedia()}>{retrying === "all" ? "Queueing…" : "Retry all failed images"}</button></div>{config?.last_media_error && <div className={styles.error} role="alert">Latest image sync error: {config.last_media_error}</div>}<div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Product</th><th>Attempts</th><th>Error</th><th>Action</th></tr></thead><tbody>{mediaFailures.map((failure) => <tr key={failure.id}><td><strong>{failure.product_name}</strong><br /><span className={styles.muted}>{failure.sku || "No SKU"}</span></td><td>{failure.attempts}{failure.next_attempt_at && <div className={styles.muted}>Next retry: {new Date(failure.next_attempt_at).toLocaleString()}</div>}</td><td>{failure.last_error || "No error detail available."}</td><td><button type="button" className={styles.primaryButton} disabled={retrying !== null} onClick={() => void retryMedia(failure.product_id)}>{retrying === failure.product_id ? "Queueing…" : "Retry image"}</button></td></tr>)}{!loading && mediaFailures.length === 0 && <tr><td colSpan={4} className={styles.empty}>No failed product image syncs.</td></tr>}</tbody></table></div></section>
    <div className={styles.formGrid}><section className={styles.panel}><div className={styles.toolbar}><h2 className={styles.panelTitle}>Sync runs</h2><span className={styles.muted}>{loading ? "Loading…" : `${runs.length} runs`}</span></div><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Mode</th><th>Status</th><th>Attempts</th><th>Created</th></tr></thead><tbody>{runs.map((run) => <tr key={run.id}><td>{run.stats?.sync_mode || "incremental"}</td><td><span className={styles.badge}>{run.status}</span>{(run.next_attempt_at || run.stats?.retry_at) && <div className={styles.muted}>Retrying at {new Date(run.next_attempt_at || run.stats.retry_at || "").toLocaleString()}</div>}{run.error && <div className={styles.muted}>{run.error}</div>}</td><td>{run.attempts}</td><td>{new Date(run.started_at).toLocaleString()}</td></tr>)}{!loading && runs.length === 0 && <tr><td colSpan={4} className={styles.empty}>No sync runs found.</td></tr>}</tbody></table></div></section><section className={styles.panel}><h2 className={styles.panelTitle}>Open conflicts</h2><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Entity</th><th>ID</th><th>Status</th></tr></thead><tbody>{conflicts.map((conflict) => <tr key={conflict.id}><td>{conflict.entity_type}</td><td>{conflict.entity_id}</td><td>{conflict.status}</td></tr>)}{!loading && conflicts.length === 0 && <tr><td colSpan={3} className={styles.empty}>No unresolved conflicts.</td></tr>}</tbody></table></div></section></div>
  </>;
}
