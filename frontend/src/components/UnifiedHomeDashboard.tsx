"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  QuickLinks,
  WorkspaceSwitcher,
  type Workspace,
} from "@/components/CommerceWorkspace";
import SyncActions from "@/components/SyncActions";
import { useAuth } from "@/contexts/AuthContext";
import { getWorkspaceRole } from "@/lib/permissions";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";

type RoleKey = "admin" | "vendor" | "rider" | "staff";

type HomeSummary = {
  sales_minor_total: number;
  shop_sales_minor: number;
  online_sales_minor: number;
  order_count: number;
  pending_orders: number;
  low_stock_count: number;
  product_count: number;
  reserved_line_count: number;
  assigned_count: number;
  picked_up_count: number;
  out_for_delivery_count: number;
  delivered_count: number;
  failed_count: number;
};

const emptySummary: HomeSummary = {
  sales_minor_total: 0,
  shop_sales_minor: 0,
  online_sales_minor: 0,
  order_count: 0,
  pending_orders: 0,
  low_stock_count: 0,
  product_count: 0,
  reserved_line_count: 0,
  assigned_count: 0,
  picked_up_count: 0,
  out_for_delivery_count: 0,
  delivered_count: 0,
  failed_count: 0,
};

const numberValue = (value: unknown) => (typeof value === "number" ? value : 0);
const money = (minor: number) =>
  `PKR ${(minor / 100).toLocaleString(undefined, { minimumFractionDigits: 2 })}`;

function normalizeSummary(value: unknown, role: RoleKey): HomeSummary {
  const source = value as { summary?: Record<string, unknown> } & Record<
    string,
    unknown
  >;
  const summary = role === "rider" ? source.summary || {} : source;
  if (role !== "rider") {
    return {
      ...emptySummary,
      ...Object.fromEntries(
        Object.keys(emptySummary).map((key) => [
          key,
          numberValue(summary[key]),
        ]),
      ),
    } as HomeSummary;
  }
  return {
    ...emptySummary,
    assigned_count: numberValue(summary.assigned_count),
    picked_up_count: numberValue(summary.picked_up_count),
    out_for_delivery_count: numberValue(summary.out_for_delivery_count),
    delivered_count: numberValue(summary.delivered_count),
    failed_count: numberValue(summary.failed_count),
    order_count: numberValue(summary.assigned_count),
  };
}

export default function UnifiedHomeDashboard() {
  const { user, permissions, isLoading: authLoading } = useAuth();
  const searchParams = useSearchParams();
  const workspace = (searchParams.get("workspace") as Workspace) || "combined";
  const workspaceRole = getWorkspaceRole(user);
  const role: RoleKey =
    workspaceRole === "administrator" ? "admin" : workspaceRole;
  const canViewCommerceSummary =
    role !== "staff" || permissions.includes("reports.view");
  const requestKey = `${role}:${workspace}`;
  const [summary, setSummary] = useState<HomeSummary>(emptySummary);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState("");
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    if (authLoading || !user) return;
    if (!canViewCommerceSummary) {
      return;
    }
    let active = true;
    const endpoint =
      role === "rider"
        ? "/delivery/rider/dashboard"
        : role === "vendor"
          ? `/commerce/vendor/dashboard?workspace=${workspace}`
          : `/commerce/dashboard?workspace=${workspace}`;
    fetchApi(endpoint)
      .then((value) => {
        if (!active) return;
        setSummary(normalizeSummary(value, role));
        setLoadedKey(requestKey);
        setError("");
      })
      .catch(() => {
        if (!active) return;
        setLoadedKey(requestKey);
        setError("Unable to load your workspace overview.");
      });
    return () => {
      active = false;
    };
  }, [authLoading, canViewCommerceSummary, role, requestKey, user, workspace]);

  const roleLabel =
    role === "rider"
      ? "Rider workspace"
      : role === "vendor"
        ? "Vendor workspace"
        : role === "staff"
          ? "Staff workspace"
          : "Admin workspace";
  const metrics =
    role === "rider"
      ? [
          {
            label: "Sales",
            value: "—",
            meta: "Not applicable to deliveries",
            tone: "",
          },
          {
            label: "Assigned",
            value: summary.assigned_count,
            meta: "Orders in your queue",
            tone: "accent",
          },
          {
            label: "Out for delivery",
            value: summary.out_for_delivery_count,
            meta: "Active customer drops",
            tone: "warning",
          },
          {
            label: "Failed",
            value: summary.failed_count,
            meta: "Needs follow-up",
            tone: summary.failed_count ? "danger" : "",
          },
          {
            label: "Picked up",
            value: summary.picked_up_count,
            meta: "Collected from dispatch",
            tone: "",
          },
          {
            label: "Delivered",
            value: summary.delivered_count,
            meta: "Completed deliveries",
            tone: "",
          },
        ]
      : [
          {
            label: "Sales",
            value: money(summary.sales_minor_total),
            meta: "Across selected channels",
            tone: "accent",
          },
          {
            label: "Orders",
            value: summary.order_count,
            meta: "In the workspace",
            tone: "",
          },
          {
            label: "Pending fulfillment",
            value: summary.pending_orders,
            meta: "Needs attention",
            tone: summary.pending_orders ? "warning" : "",
          },
          {
            label: "Low stock",
            value: summary.low_stock_count,
            meta: "Products to replenish",
            tone: summary.low_stock_count ? "danger" : "",
          },
          {
            label: "Reserved lines",
            value: summary.reserved_line_count,
            meta: "Reserved for orders",
            tone: "",
          },
          {
            label: "Products",
            value: summary.product_count,
            meta: "In the catalog",
            tone: "",
          },
        ];

  const channelTotal = summary.shop_sales_minor + summary.online_sales_minor;
  const shopPercent = channelTotal
    ? Math.round((summary.shop_sales_minor / channelTotal) * 100)
    : 0;
  const onlinePercent = channelTotal ? 100 - shopPercent : 0;
  const quickMode = role === "rider" ? "rider" : role;
  const insightRows = useMemo(
    () =>
      role === "rider"
        ? [
            [
              "Out for delivery",
              summary.out_for_delivery_count,
              "Active deliveries",
            ],
            ["Failed deliveries", summary.failed_count, "Review and follow up"],
          ]
        : [
            [
              "Pending fulfillment",
              summary.pending_orders,
              "Order items ready for action",
            ],
            [
              "Low stock",
              summary.low_stock_count,
              "Products that may need replenishing",
            ],
          ],
    [
      role,
      summary.failed_count,
      summary.low_stock_count,
      summary.out_for_delivery_count,
      summary.pending_orders,
    ],
  );

  return (
    <>
      <section className={styles.homeHero}>
        <div>
          <div className={styles.eyebrow}>Unified mobile workspace</div>
          <h1 className={styles.pageTitle}>
            Good to see you, {user?.username || "there"}
          </h1>
          <p className={styles.pageSubtitle}>
            Your daily operations, actions, and performance in one simple view.
          </p>
        </div>
        <span className={styles.rolePill}>{roleLabel}</span>
      </section>

      <div className={styles.workspaceSectionHeader}>
        <h2>Workspace</h2>
        <span>
          {role === "rider"
            ? "Delivery view"
            : canViewCommerceSummary
              ? "Choose a channel"
              : "Your assigned access"}
        </span>
      </div>
      {role === "rider" ? (
        <div className={styles.scopeBar}>
          <span className={styles.workspaceLabel}>View</span>
          <span
            className={`${styles.workspaceButton} ${styles.workspaceButtonActive}`}
          >
            My deliveries
          </span>
        </div>
      ) : canViewCommerceSummary ? (
        <WorkspaceSwitcher value={workspace} />
      ) : (
        <div className={styles.scopeBar}>
          <span className={styles.workspaceLabel}>View</span>
          <span
            className={`${styles.workspaceButton} ${styles.workspaceButtonActive}`}
          >
            Assigned modules
          </span>
        </div>
      )}

      <div className={styles.workspaceSectionHeader}>
        <h2>Quick actions</h2>
        <span>Common tasks</span>
      </div>
      <QuickLinks mode={quickMode} permissions={permissions} />
      {role !== "rider" && <SyncActions />}
      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}

      {canViewCommerceSummary && (
        <div className={styles.workspaceSectionHeader}>
          <h2>At a glance</h2>
          <span>{loading ? "Updating" : "Live summary"}</span>
        </div>
      )}
      {canViewCommerceSummary && (
        <div className={styles.metricGrid} aria-label="Workspace summary">
          {metrics.map((metric) => {
            const toneClass =
              metric.tone === "accent"
                ? styles.metricAccent
                : metric.tone === "warning"
                  ? styles.metricWarning
                  : metric.tone === "danger"
                    ? styles.metricDanger
                    : "";
            return (
              <div
                className={`${styles.metricCard} ${toneClass}`}
                key={metric.label}
              >
                <div className={styles.metricLabel}>{metric.label}</div>
                <div className={styles.metricValue}>
                  {loading ? "…" : metric.value}
                </div>
                <div className={styles.metricMeta}>{metric.meta}</div>
              </div>
            );
          })}
        </div>
      )}

      {canViewCommerceSummary && (
        <div className={styles.homeColumns}>
          <section className={styles.panel}>
            <div className={styles.workspaceSectionHeader}>
              <h2>Needs attention</h2>
              <span>Today</span>
            </div>
            <div className={styles.insightList}>
              {insightRows.map(([label, value, meta]) => (
                <div className={styles.insightRow} key={String(label)}>
                  <div>
                    <strong>{label}</strong>
                    <span>{meta}</span>
                  </div>
                  <b>{loading ? "…" : value}</b>
                </div>
              ))}
            </div>
          </section>
          <section className={styles.panel}>
            <div className={styles.workspaceSectionHeader}>
              <h2>
                {role === "rider" ? "Delivery progress" : "Channel performance"}
              </h2>
              <span>Overview</span>
            </div>
            <div className={styles.channelSplit}>
              {role === "rider" ? (
                <>
                  <div className={styles.channelRow}>
                    <div className={styles.channelRowHeader}>
                      <span>Completed</span>
                      <strong>{loading ? "—" : summary.delivered_count}</strong>
                    </div>
                    <progress
                      className={styles.channelProgress}
                      aria-label="Completed delivery percentage"
                      max="100"
                      value={
                        summary.assigned_count
                          ? Math.min(
                              100,
                              (summary.delivered_count /
                                summary.assigned_count) *
                                100,
                            )
                          : 0
                      }
                    />
                  </div>
                  <div className={styles.channelRow}>
                    <div className={styles.channelRowHeader}>
                      <span>Active</span>
                      <strong>
                        {loading ? "—" : summary.out_for_delivery_count}
                      </strong>
                    </div>
                    <progress
                      className={`${styles.channelProgress} ${styles.channelProgressSecondary}`}
                      aria-label="Active delivery percentage"
                      max="100"
                      value={
                        summary.assigned_count
                          ? Math.min(
                              100,
                              (summary.out_for_delivery_count /
                                summary.assigned_count) *
                                100,
                            )
                          : 0
                      }
                    />
                  </div>
                </>
              ) : (
                <>
                  <div className={styles.channelRow}>
                    <div className={styles.channelRowHeader}>
                      <span>Shop / POS</span>
                      <strong>
                        {loading ? "—" : money(summary.shop_sales_minor)}
                      </strong>
                    </div>
                    <progress
                      className={styles.channelProgress}
                      aria-label="Shop and POS share of sales"
                      max="100"
                      value={shopPercent}
                    />
                  </div>
                  <div className={styles.channelRow}>
                    <div className={styles.channelRowHeader}>
                      <span>Online store</span>
                      <strong>
                        {loading ? "—" : money(summary.online_sales_minor)}
                      </strong>
                    </div>
                    <progress
                      className={`${styles.channelProgress} ${styles.channelProgressSecondary}`}
                      aria-label="Online store share of sales"
                      max="100"
                      value={onlinePercent}
                    />
                  </div>
                </>
              )}
            </div>
          </section>
        </div>
      )}
    </>
  );
}
