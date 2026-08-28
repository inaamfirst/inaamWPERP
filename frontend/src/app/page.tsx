import { Suspense } from "react";
import { LoadingState } from "@/components/ui/Feedback";
import HomeClient from "./HomeClient";

export default function AdminDashboard() {
  return (
    <Suspense fallback={<LoadingState label="Loading workspace" />}>
      <HomeClient />
    </Suspense>
  );
}
