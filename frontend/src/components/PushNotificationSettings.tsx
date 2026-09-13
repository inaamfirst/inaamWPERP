"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import {
  disablePush,
  enablePush,
  getPushConfig,
  getPushSubscriptions,
  isPushSupported,
  sendPushTest,
  type PushSubscriptionRecord,
  type PushConfig,
} from "@/lib/push";
import styles from "./commerce.module.css";

export default function PushNotificationSettings() {
  const { permissions } = useAuth();
  const [enabled, setEnabled] = useState(false);
  const [subscriptions, setSubscriptions] = useState<PushSubscriptionRecord[]>([]);
  const [config, setConfig] = useState<PushConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function load() {
    if (!isPushSupported()) return;
    try {
      const [config, records] = await Promise.all([getPushConfig(), getPushSubscriptions()]);
      setConfig(config);
      setEnabled(config.enabled);
      setSubscriptions(records.filter((record) => record.is_active));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Notification settings could not be loaded.");
    }
  }

  // Browser notification APIs are unavailable during SSR.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, []);

  async function turnOn() {
    setBusy(true); setError(""); setMessage("");
    try {
      const record = await enablePush();
      setSubscriptions((current) => [...current.filter((item) => item.id !== record.id), record]);
      setMessage("This browser is subscribed to order notifications.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Notifications could not be enabled.");
    } finally { setBusy(false); }
  }

  async function turnOff() {
    setBusy(true); setError(""); setMessage("");
    try {
      await disablePush();
      setSubscriptions([]);
      setMessage("Notifications are disabled on this browser.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Notifications could not be disabled.");
    } finally { setBusy(false); }
  }

  async function test() {
    setBusy(true); setError(""); setMessage("");
    try { await sendPushTest(); setMessage("A test notification was queued."); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "The test notification could not be queued."); }
    finally { setBusy(false); }
  }

  if (!isPushSupported()) {
    return <section className={styles.panel}><h2 className={styles.panelTitle}>Browser notifications</h2><p className={styles.muted}>This browser does not support Web Push notifications.</p></section>;
  }
  if (!permissions.includes("orders.view") && !permissions.includes("vendor.orders.view")) return null;
  return (
    <section className={styles.panel} aria-labelledby="push-settings-title">
      <h2 className={styles.panelTitle} id="push-settings-title">Browser notifications</h2>
      <p className={styles.muted}>
        {enabled ? `${subscriptions.length} active browser subscription${subscriptions.length === 1 ? "" : "s"}. New orders are sent according to your account access.` : "Push notifications are not configured on this server."}
      </p>
      {enabled && <p className={styles.muted}>Administrators receive every new order. Vendors receive only orders containing their own products.</p>}
      {config?.readiness_detail && <p className={config.worker_available || !enabled ? styles.muted : styles.error}>
        {config.readiness_detail}{config.worker_updated_at ? ` Last worker update: ${new Date(config.worker_updated_at).toLocaleString()}.` : ""}
      </p>}
      {error && <div className={styles.error} role="alert">{error}</div>}
      {message && <div className={styles.notice} role="status">{message}</div>}
      {enabled && <div className={styles.formActions}>
        <button type="button" className={styles.primaryButton} disabled={busy} onClick={() => void turnOn()}>Enable this browser</button>
        <button type="button" className={styles.secondaryButton} disabled={busy || subscriptions.length === 0} onClick={() => void test()}>Send test</button>
        <button type="button" className={styles.dangerButton} disabled={busy || subscriptions.length === 0} onClick={() => void turnOff()}>Disable this browser</button>
      </div>}
    </section>
  );
}
