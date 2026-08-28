"use client";

import { useEffect } from "react";
import { ErrorState } from "@/components/ui/Feedback";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => console.error(error), [error]);
  return <ErrorState title="This page could not be loaded" description="Your data is safe. Try the request again, or return to the workspace navigation." onRetry={reset} />;
}
