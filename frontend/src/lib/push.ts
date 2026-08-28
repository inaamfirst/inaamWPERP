import { fetchApi } from "./api";

export type PushConfig = { enabled: boolean; public_key: string | null };
export type PushSubscriptionRecord = {
  id: string;
  endpoint: string;
  expiration_at: string | null;
  user_agent: string | null;
  device_label: string | null;
  is_active: boolean;
  last_seen_at: string | null;
  created_at: string;
  updated_at: string;
};

type BrowserSubscriptionJson = {
  endpoint?: string;
  expirationTime?: number | null;
  keys?: { p256dh?: string; auth?: string };
};

export function isPushSupported(): boolean {
  return typeof window !== "undefined"
    && "Notification" in window
    && "serviceWorker" in navigator
    && "PushManager" in window;
}

export function urlBase64ToUint8Array(value: string): Uint8Array {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const normalized = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(normalized);
  return Uint8Array.from(raw, (character) => character.charCodeAt(0));
}

export async function getPushConfig(): Promise<PushConfig> {
  return await fetchApi("/push/config") as PushConfig;
}

export async function getPushSubscriptions(): Promise<PushSubscriptionRecord[]> {
  return await fetchApi("/push/subscriptions") as PushSubscriptionRecord[];
}

export async function enablePush(): Promise<PushSubscriptionRecord> {
  if (!isPushSupported()) throw new Error("This browser does not support push notifications.");
  const config = await getPushConfig();
  if (!config.enabled || !config.public_key) {
    throw new Error("Browser push notifications are not configured on this ERP server.");
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Browser notification permission was not granted.");
  const registration = await navigator.serviceWorker.register("/push-sw.js");
  const subscription = await registration.pushManager.getSubscription()
    || await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(config.public_key) as unknown as BufferSource,
    });
  const serialized = subscription.toJSON() as BrowserSubscriptionJson;
  if (!serialized.endpoint || !serialized.keys?.p256dh || !serialized.keys.auth) {
    throw new Error("The browser returned an incomplete push subscription.");
  }
  return await fetchApi("/push/subscriptions", {
    method: "POST",
    body: JSON.stringify({
      endpoint: serialized.endpoint,
      keys: serialized.keys,
      expirationTime: serialized.expirationTime ?? null,
      user_agent: navigator.userAgent,
    }),
  }) as PushSubscriptionRecord;
}

export async function disablePush(): Promise<void> {
  if (!isPushSupported()) return;
  const registration = await navigator.serviceWorker.getRegistration("/push-sw.js");
  const subscription = await registration?.pushManager.getSubscription();
  if (!subscription) return;
  const records = await getPushSubscriptions();
  const record = records.find((item) => item.endpoint === subscription.endpoint);
  if (record) {
    await fetchApi(`/push/subscriptions/${encodeURIComponent(record.id)}`, { method: "DELETE" });
  }
  await subscription.unsubscribe();
}

export async function sendPushTest(): Promise<void> {
  await fetchApi("/push/test", { method: "POST", body: JSON.stringify({}) });
}
