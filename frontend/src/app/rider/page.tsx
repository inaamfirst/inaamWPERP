import { Suspense } from "react";
import UnifiedHomeDashboard from "@/components/UnifiedHomeDashboard";

export default function RiderDashboard() {
  return <Suspense fallback={<div className="loadingState">Loading workspace…</div>}><UnifiedHomeDashboard /></Suspense>;
}
