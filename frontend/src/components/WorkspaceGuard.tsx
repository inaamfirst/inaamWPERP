"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import DashboardLayout from "@/components/DashboardLayout";
import { AccessDenied, LoadingState } from "@/components/ui/Feedback";
import { useAuth } from "@/contexts/AuthContext";
import {
  canAccessPolicy,
  getCanonicalHome,
  getPolicyForPath,
  workspaceForRole,
  type WorkspaceId,
} from "@/lib/access-policy";
import { getWorkspaceRole } from "@/lib/permissions";

export default function WorkspaceGuard({
  workspace,
  children,
}: {
  workspace: WorkspaceId;
  children: React.ReactNode;
}) {
  const { user, permissions, isLoading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const role = getWorkspaceRole(user);
  const canonicalHome = getCanonicalHome(role, permissions);
  const correctWorkspace = workspaceForRole(role) === workspace;
  const policy = getPolicyForPath(pathname);
  const permitted = Boolean(policy && policy.workspace === workspace && canAccessPolicy(policy, permissions));

  useEffect(() => {
    if (isLoading) return;
    if (!user) {
      router.replace("/login");
      return;
    }
    if (user.must_change_password) {
      router.replace("/change-password");
      return;
    }
    if (!correctWorkspace) router.replace(canonicalHome);
  }, [canonicalHome, correctWorkspace, isLoading, router, user]);

  if (isLoading || !user || user.must_change_password || !correctWorkspace) {
    return <LoadingState label="Opening your workspace" />;
  }

  return (
    <DashboardLayout>
      {permitted ? children : <AccessDenied returnTo={canonicalHome} />}
    </DashboardLayout>
  );
}
