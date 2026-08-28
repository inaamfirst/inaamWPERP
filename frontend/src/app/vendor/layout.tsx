import WorkspaceGuard from "@/components/WorkspaceGuard";

export default function VendorLayout({ children }: { children: React.ReactNode }) {
  return <WorkspaceGuard workspace="vendor">{children}</WorkspaceGuard>;
}
