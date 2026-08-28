import { EmptyState } from "@/components/ui/Feedback";
import Link from "next/link";

export default function NotFound() {
  return <EmptyState title="Page not found" description="The page may have moved or is no longer available." action={<Link href="/">Return to workspace</Link>} />;
}
