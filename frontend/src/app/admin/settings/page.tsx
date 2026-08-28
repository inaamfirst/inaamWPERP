"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";
import PushNotificationSettings from "@/components/PushNotificationSettings";

type Setting = { key: string; value: Record<string, unknown>; updated_at: string };

export default function AdminSettings() {
  const [settings, setSettings] = useState<Setting[]>([]);
  const [selected, setSelected] = useState<Setting | null>(null);
  const [value, setValue] = useState("{}");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try { setSettings(await fetchApi("/settings") as Setting[]); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Settings could not be loaded."); }
    finally { setLoading(false); }
  }
  // This effect synchronizes the view with the remote settings API.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, []);

  function selectSetting(setting: Setting) { setSelected(setting); setValue(JSON.stringify(setting.value, null, 2)); setError(""); setMessage(""); }

  async function save() {
    if (!selected) return;
    setError(""); setMessage("");
    try {
      const parsed = JSON.parse(value) as Record<string, unknown>;
      const updated = await fetchApi(`/settings/${encodeURIComponent(selected.key)}`, { method: "PUT", body: JSON.stringify({ value: parsed }) }) as Setting;
      setSettings((current) => current.map((item) => item.key === updated.key ? updated : item)); setSelected(updated); setValue(JSON.stringify(updated.value, null, 2)); setMessage("Setting saved.");
    } catch (caught) { setError(caught instanceof SyntaxError ? "Value must be valid JSON." : caught instanceof Error ? caught.message : "Setting could not be saved."); }
  }

  return <>
    <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Company configuration</div><h1 className={styles.pageTitle}>Settings</h1><p className={styles.pageSubtitle}>Review persisted company settings. Sensitive infrastructure secrets remain outside this UI in the protected environment file.</p></div><button type="button" className={styles.secondaryButton} onClick={() => void load()}>Refresh</button></div>
    {error && <div className={styles.error}>{error}</div>}{message && <div className={styles.notice}>{message}</div>}
    <PushNotificationSettings />
    <div className={styles.formGrid}><section className={styles.panel}><div className={styles.toolbar}><h2 className={styles.panelTitle}>Persisted settings</h2><span className={styles.muted}>{loading ? "Loading…" : `${settings.length} settings`}</span></div><div className={styles.tableWrap}><table className={styles.table}><thead><tr><th>Key</th><th>Value</th><th>Updated</th></tr></thead><tbody>{settings.map((setting) => <tr key={setting.key}><td><button type="button" className={styles.linkButton} onClick={() => selectSetting(setting)}>{setting.key}</button></td><td><code>{JSON.stringify(setting.value)}</code></td><td>{new Date(setting.updated_at).toLocaleString()}</td></tr>)}{!loading && settings.length === 0 && <tr><td colSpan={3} className={styles.empty}>No persisted settings found.</td></tr>}</tbody></table></div></section>{selected && <section className={styles.panel}><div className={styles.toolbar}><h2 className={styles.panelTitle}>Edit {selected.key}</h2><button type="button" className={styles.secondaryButton} onClick={() => setSelected(null)}>Close</button></div><label className={styles.field}>JSON value<textarea value={value} onChange={(event) => setValue(event.target.value)} spellCheck={false} /></label><div className={styles.formActions}><button type="button" className={styles.primaryButton} onClick={() => void save()}>Save setting</button></div></section>}</div>
  </>;
}
