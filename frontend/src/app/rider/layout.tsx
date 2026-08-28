import WorkspaceGuard from "@/components/WorkspaceGuard";

export default function RiderLayout({ children }: { children: React.ReactNode }) {
  return <WorkspaceGuard workspace="rider">{children}</WorkspaceGuard>;
}
