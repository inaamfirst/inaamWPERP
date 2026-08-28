import WorkspaceGuard from "@/components/WorkspaceGuard";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <WorkspaceGuard workspace="admin">{children}</WorkspaceGuard>;
}
