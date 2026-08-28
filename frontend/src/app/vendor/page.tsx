import { Suspense } from "react";
import UnifiedHomeDashboard from "@/components/UnifiedHomeDashboard";
import PushNotificationSettings from "@/components/PushNotificationSettings";

export default function VendorDashboard() {
  return <><Suspense fallback={<div className="loadingState">Loading workspace…</div>}><UnifiedHomeDashboard /></Suspense><PushNotificationSettings /></>;
}
