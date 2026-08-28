import { Suspense } from "react";
import UnifiedHomeDashboard from "@/components/UnifiedHomeDashboard";
import { LoadingState } from "@/components/ui/Feedback";

export default function AdminDashboard() {
  return <Suspense fallback={<LoadingState label="Loading overview" />}><UnifiedHomeDashboard /></Suspense>;
}
