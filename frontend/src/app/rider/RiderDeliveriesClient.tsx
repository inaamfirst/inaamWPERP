"use client";

import { useEffect, useMemo, useState } from "react";
import RiderDeliveryCard from "./RiderDeliveryCard";
import { fetchApi } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import type { Delivery } from "@/lib/delivery";
import styles from "@/components/commerce.module.css";

type Mode = "active" | "today" | "history";

export default function RiderDeliveriesClient({ mode }: { mode: Mode }) {
  const { permissions } = useAuth();
  const canUpdate = permissions.includes("delivery.update_assigned");
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [error, setError] = useState("");

  async function load() {
    try {
      setDeliveries(await fetchApi("/delivery/rider/assignments") as Delivery[]);
    } catch {
      setError("Unable to load deliveries.");
    }
  }

  // This effect synchronizes the view with the remote delivery API.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { void load(); }, []);

  async function updateStatus(delivery: Delivery, status: string) {
    const reason = status === "failed" ? window.prompt("Why did this delivery fail?") : undefined;
    if (status === "failed" && !reason) return;
    try {
      await fetchApi(`/delivery/rider/assignments/${delivery.id}/status`, { method: "POST", body: JSON.stringify({ status, reason }) });
      await load();
    } catch {
      setError("The delivery status could not be updated.");
    }
  }

  const visible = useMemo(() => deliveries.filter((delivery) => {
    const terminal = ["delivered", "failed", "cancelled"].includes(delivery.status);
    if (mode === "active") return !terminal;
    if (mode === "history") return terminal;
    const today = new Date().toDateString();
    return new Date(delivery.created_at).toDateString() === today;
  }), [deliveries, mode]);
  const title = mode === "history" ? "Delivery history" : mode === "today" ? "Today's deliveries" : "Assigned deliveries";

  return (
    <>
      <div className={styles.pageHeader}><div><div className={styles.eyebrow}>Rider operations</div><h1 className={styles.pageTitle}>{title}</h1><p className={styles.pageSubtitle}>Customer and delivery details for orders assigned to your account.</p></div></div>
      {error && <div className={styles.error}>{error}</div>}
      {visible.length === 0 ? <div className={styles.panel}><div className={styles.empty}>No deliveries found.</div></div> : visible.map((delivery) => <RiderDeliveryCard key={delivery.id} delivery={delivery} onStatusChange={mode === "history" || !canUpdate ? undefined : updateStatus} />)}
    </>
  );
}
