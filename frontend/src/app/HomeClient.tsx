"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { dashboardHome } from "@/lib/navigation";

export default function HomeClient() {
  const { user, permissions, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !user) router.replace("/login");
    if (!isLoading && user?.must_change_password) router.replace("/change-password");
    if (!isLoading && user && !user.must_change_password) {
      router.replace(dashboardHome(user, permissions));
    }
  }, [isLoading, permissions, router, user]);

  return <main className="loadingState" id="main-content" role="status">Opening your workspace…</main>;
}
