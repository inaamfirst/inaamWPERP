"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/contexts/AuthContext";
import { ApiError, fetchApi } from "@/lib/api";
import styles from "./commerce.module.css";

type SyncMode = "products" | "incremental";

type SyncRun = {
  id?: string;
  status?: string;
  error?: string | null;
  stats?: {
    current_phase?: string | null;
    pushed_records?: number;
    pushed_media_records?: number;
    pulled_products?: number;
    failed_product_pushes?: number;
    failed_media_pushes?: number;
    failed_taxonomies?: number;
    pending_product_pushes?: number;
    pending_media_pushes?: number;
  };
  next_attempt_at?: string | null;
};

function errorMessage(value: unknown): string {
  if (value instanceof ApiError) return value.message;
  if (value instanceof Error) return value.message;
  return "The sync could not be started.";
}

function completionMessage(run: SyncRun): { message: string; warning: boolean } {
  const stats = run.stats || {};
  const failed = (stats.failed_product_pushes || 0)
    + (stats.failed_media_pushes || 0)
    + (stats.failed_taxonomies || 0);
  const pending = (stats.pending_product_pushes || 0) + (stats.pending_media_pushes || 0);
  if (failed || pending) {
    const failedImages = stats.failed_media_pushes || 0;
    const imageDetail = failedImages ? ` (${failedImages} product image ${failedImages === 1 ? "sync" : "syncs"})` : "";
    return {
      message: `Sync finished with ${failed} failed${imageDetail} and ${pending} pending item(s). Open WooCommerce diagnostics to see the reason and retry safely.`,
      warning: true,
    };
  }
  const pushed = (stats.pushed_records || 0) + (stats.pushed_media_records || 0);
  const pulled = stats.pulled_products || 0;
  return {
    message: `Sync completed successfully: ${pushed} pushed, ${pulled} products pulled.`,
    warning: false,
  };
}

export default function SyncActions() {
  const { user, permissions } = useAuth();
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const canSync = permissions.includes("woocommerce.sync");
  const isVendor = user?.role_names?.includes("Vendor") && !user.role_names.includes("Administrator");

  useEffect(() => {
    if (!activeRunId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      try {
        const runs = await fetchApi("/woocommerce/sync-runs") as SyncRun[];
        const run = runs.find((item) => item.id === activeRunId);
        if (cancelled) return;
        if (!run || run.status === "success" || run.status === "failed") {
          setBusy(false);
          setActiveRunId(null);
          if (run?.status === "failed") {
            setError(run.error || "The sync failed. Review sync history for details.");
            setMessage("");
          } else {
            const completion = run && completionMessage(run);
            setMessage(completion?.message || "Sync status is no longer available.");
            if (completion?.warning) setError(completion.message);
          }
          return;
        }
        const phase = run.stats?.current_phase;
        setMessage(phase ? `Sync in progress: ${phase}` : "Sync queued. Waiting for the worker...");
        timer = setTimeout(() => void poll(), 1500);
      } catch (caught) {
        if (cancelled) return;
        setBusy(false);
        setActiveRunId(null);
        setError(errorMessage(caught));
        setMessage("");
      }
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [activeRunId]);

  async function startSync(mode: SyncMode) {
    if (busy) return;
    setBusy(true);
    setError("");
    setMessage(mode === "products" ? "Starting product sync..." : "Starting content sync...");
    try {
      const run = await fetchApi(`/woocommerce/sync?mode=${mode}`, { method: "POST" }) as SyncRun;
      if (run.id && (run.status === "queued" || run.status === "running")) {
        setActiveRunId(run.id);
        return;
      }
      setBusy(false);
      setMessage(run.status === "failed" ? "Sync failed." : "Sync request completed.");
      if (run.status === "failed") setError(run.error || "Review sync history for details.");
    } catch (caught) {
      setBusy(false);
      setMessage("");
      setError(errorMessage(caught));
    }
  }

  if (!canSync && !isVendor) return null;

  return (
    <section className={styles.panel} aria-labelledby="sync-actions-title">
      <h2 className={styles.panelTitle} id="sync-actions-title">WooCommerce sync</h2>
      <p className={styles.muted}>{isVendor ? "Your approved product changes are queued and published automatically through the shared WooCommerce lane." : "Sync the company catalog and WooCommerce content."}</p>
      {canSync && <div className={styles.formActions}>
        <button type="button" className={styles.secondaryButton} disabled={busy} onClick={() => void startSync("products")}>
          Sync Products
        </button>
        <button type="button" className={styles.primaryButton} disabled={busy} onClick={() => void startSync("incremental")}>
          Sync All Content
        </button>
      </div>}
      {message && <div className={styles.notice} role="status">{message}</div>}
      {error && <div className={styles.error} role="alert">{error}</div>}
      {error && canSync && <div className={styles.formActions}>
        <Link className={styles.secondaryButton} href="/admin/woocommerce">Open WooCommerce diagnostics</Link>
      </div>}
    </section>
  );
}
