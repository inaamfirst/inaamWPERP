"use client";

import { useEffect, useState } from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type Health = {
  status: string;
  environment: string;
  version: string;
  database_ready: boolean;
  migration_revision: string | null;
  expected_migration_revision: string | null;
  module_count: number;
};
type ModuleSummary = {
  id: string;
  name: string;
  release_status?: string;
  enabled?: boolean;
};
type Diagnostics = Record<string, unknown>;

export default function AdminSystem() {
  const [health, setHealth] = useState<Health | null>(null);
  const [modules, setModules] = useState<ModuleSummary[]>([]);
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [healthResponse, modulesResponse, diagnosticsResponse] =
        await Promise.all([
          fetchApi("/health"),
          fetchApi("/modules"),
          fetchApi("/support/diagnostics"),
        ]);
      setHealth(healthResponse as Health);
      setModules(
        (modulesResponse as { modules: ModuleSummary[] }).modules || [],
      );
      setDiagnostics(diagnosticsResponse as Diagnostics);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "System diagnostics could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    // The initial request synchronizes this client view with remote diagnostics.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, []);

  return (
    <>
      <div className={styles.pageHeader}>
        <div>
          <div className={styles.eyebrow}>Runtime operations</div>
          <h1 className={styles.pageTitle}>System diagnostics</h1>
          <p className={styles.pageSubtitle}>
            Verify application health, migration state, enabled modules, and
            redacted runtime diagnostics.
          </p>
        </div>
        <button
          type="button"
          className={styles.secondaryButton}
          onClick={() => void load()}
        >
          Refresh
        </button>
      </div>
      {error && <div className={styles.error}>{error}</div>}
      {loading ? (
        <div className={styles.empty}>Loading diagnostics…</div>
      ) : (
        <>
          <div className={styles.metricGrid}>
            <div className={styles.metricCard}>
              <div className={styles.metricLabel}>API</div>
              <div className={styles.metricValue}>
                {health?.status || "unknown"}
              </div>
            </div>
            <div className={styles.metricCard}>
              <div className={styles.metricLabel}>Database</div>
              <div className={styles.metricValue}>
                {health?.database_ready ? "ready" : "degraded"}
              </div>
            </div>
            <div className={styles.metricCard}>
              <div className={styles.metricLabel}>Version</div>
              <div className={styles.metricValue}>{health?.version || "—"}</div>
            </div>
            <div className={styles.metricCard}>
              <div className={styles.metricLabel}>Modules</div>
              <div className={styles.metricValue}>
                {health?.module_count ?? modules.length}
              </div>
            </div>
          </div>
          <section className={styles.panel}>
            <div className={styles.toolbar}>
              <h2 className={styles.panelTitle}>Migration and environment</h2>
              <span className={styles.badge}>{health?.environment}</span>
            </div>
            <dl>
              <dt>Current revision</dt>
              <dd>
                <code>{health?.migration_revision || "none"}</code>
              </dd>
              <dt>Expected revision</dt>
              <dd>
                <code>{health?.expected_migration_revision || "unknown"}</code>
              </dd>
            </dl>
          </section>
          <section className={styles.panel}>
            <h2 className={styles.panelTitle}>Module release status</h2>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Module</th>
                    <th>Release status</th>
                    <th>Enabled</th>
                  </tr>
                </thead>
                <tbody>
                  {modules.map((module) => (
                    <tr key={module.id}>
                      <td>{module.name}</td>
                      <td>{module.release_status || "not declared"}</td>
                      <td>{module.enabled === false ? "No" : "Yes"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <section className={styles.panel}>
            <h2 className={styles.panelTitle}>Redacted diagnostics</h2>
            <pre className={styles.diagnosticsCode} tabIndex={0}>
              {JSON.stringify(diagnostics, null, 2)}
            </pre>
          </section>
        </>
      )}
    </>
  );
}
