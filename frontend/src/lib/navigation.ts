import { getCanonicalHome } from "./access-policy";
import { getWorkspaceRole } from "./permissions";

export type DashboardUser = {
  role_names?: string[];
  must_change_password?: boolean;
};

export function dashboardHome(user: DashboardUser, permissions: readonly string[] = []): string {
  return getCanonicalHome(getWorkspaceRole(user), permissions);
}
