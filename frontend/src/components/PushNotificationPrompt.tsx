"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { enablePush, getPushConfig, isPushSupported } from "@/lib/push";
import styles from "./commerce.module.css";

const PROMPT_PREFIX = "erp-push-prompted:";

export default function PushNotificationPrompt() {
  const { user, permissions, isLoading } = useAuth();
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (isLoading || !user || !isPushSupported()) return;
    if (!permissions.includes("orders.view") && !permissions.includes("vendor.orders.view")) return;
    if (Notification.permission !== "default") return;
    const storageKey = `${PROMPT_PREFIX}${user.id}`;
    if (window.localStorage.getItem(storageKey)) return;
    let active = true;
    getPushConfig().then((config) => {
      if (active && config.enabled) setVisible(true);
    }).catch(() => undefined);
    return () => { active = false; };
  }, [isLoading, permissions, user]);

  function dismiss() {
    if (user) window.localStorage.setItem(`${PROMPT_PREFIX}${user.id}`, "dismissed");
    setVisible(false);
  }

  async function enable() {
    setBusy(true); setError("");
    try {
      await enablePush();
      if (user) window.localStorage.setItem(`${PROMPT_PREFIX}${user.id}`, "enabled");
      setVisible(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Push notifications could not be enabled.");
    } finally { setBusy(false); }
  }

  if (!visible) return null;
  return (
    <aside className={styles.pushPrompt} role="dialog" aria-label="Enable order notifications">
      <div>
        <strong>Get order alerts</strong>
        <p>Receive secure browser notifications when orders need attention.</p>
        {error && <div className={styles.error}>{error}</div>}
      </div>
      <div className={styles.formActions}>
        <button type="button" className={styles.primaryButton} disabled={busy} onClick={() => void enable()}>
          {busy ? "Enabling…" : "Enable notifications"}
        </button>
        <button type="button" className={styles.secondaryButton} disabled={busy} onClick={dismiss}>Not now</button>
      </div>
    </aside>
  );
}
