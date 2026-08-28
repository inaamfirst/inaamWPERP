import Link from "next/link";
import { AlertCircle, Inbox, LockKeyhole, RefreshCw } from "lucide-react";
import styles from "./ui.module.css";

type FeedbackProps = {
  title: string;
  description?: string;
  action?: React.ReactNode;
};

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className={styles.loadingState} role="status" aria-live="polite">
      <span className={styles.spinner} aria-hidden="true" />
      <span>{label}…</span>
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <span className={`${styles.skeleton} ${className}`} aria-hidden="true" />;
}

export function EmptyState({ title, description, action }: FeedbackProps) {
  return (
    <section className={styles.feedbackState} aria-labelledby="empty-state-title">
      <Inbox aria-hidden="true" />
      <h2 id="empty-state-title">{title}</h2>
      {description && <p>{description}</p>}
      {action}
    </section>
  );
}

export function ErrorState({
  title = "Something went wrong",
  description,
  onRetry,
}: FeedbackProps & { onRetry?: () => void }) {
  return (
    <section className={styles.feedbackState} role="alert" aria-labelledby="error-state-title">
      <AlertCircle aria-hidden="true" />
      <h2 id="error-state-title">{title}</h2>
      {description && <p>{description}</p>}
      {onRetry && (
        <button className={styles.primaryButton} type="button" onClick={onRetry}>
          <RefreshCw aria-hidden="true" /> Retry
        </button>
      )}
    </section>
  );
}

export function AccessDenied({ returnTo = "/" }: { returnTo?: string }) {
  return (
    <section className={styles.feedbackState} role="alert" aria-labelledby="access-denied-title">
      <LockKeyhole aria-hidden="true" />
      <h1 id="access-denied-title">You don’t have access to this page</h1>
      <p>Your account is signed in, but this area is not included in your assigned permissions.</p>
      <Link className={styles.primaryButton} href={returnTo}>Return to your workspace</Link>
    </section>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className={styles.pageHeader}>
      <div>
        {eyebrow && <p className={styles.eyebrow}>{eyebrow}</p>}
        <h1>{title}</h1>
        {description && <p className={styles.pageDescription}>{description}</p>}
      </div>
      {actions && <div className={styles.pageActions}>{actions}</div>}
    </header>
  );
}
