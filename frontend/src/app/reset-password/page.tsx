"use client";

import { FormEvent, Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ApiError, fetchApi } from "@/lib/api";
import styles from "../auth.module.css";

function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setMessage("");
    setError("");
    if (!token) {
      setError("This reset link is invalid or expired.");
      return;
    }
    if (password !== confirmation) {
      setError("The passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      await fetchApi("/auth/password-reset/confirm", {
        method: "POST",
        body: JSON.stringify({ token, new_password: password }),
      });
      setMessage("Your password has been reset. You can now sign in.");
      setPassword("");
      setConfirmation("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError("Too many reset attempts. Please try again later.");
      } else {
        setError("This reset link is invalid or expired.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className={styles.container} id="main-content">
      <section className={styles.card} aria-labelledby="reset-password-title">
        <header className={styles.header}>
          <h1 id="reset-password-title">Choose a new password</h1>
          <p>Use at least 8 characters for your new password.</p>
        </header>

        {message && <div className={styles.message} role="status">{message}</div>}
        {error && <div className={styles.error} role="alert">{error}</div>}

        {!message && (
          <form onSubmit={handleSubmit} className={styles.form}>
            <div className={styles.inputGroup}>
              <label htmlFor="new-password">New password</label>
              <input
                id="new-password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                minLength={8}
                maxLength={128}
                autoComplete="new-password"
                required
              />
            </div>
            <div className={styles.inputGroup}>
              <label htmlFor="confirm-password">Confirm new password</label>
              <input
                id="confirm-password"
                type="password"
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                minLength={8}
                maxLength={128}
                autoComplete="new-password"
                required
              />
            </div>
            <button type="submit" disabled={loading} className={styles.button}>
              {loading ? "Resetting..." : "Reset password"}
            </button>
          </form>
        )}

        <nav className={styles.links} aria-label="Authentication links">
          <Link href="/login">Back to sign in</Link>
          <Link href="/forgot-password">Request another link</Link>
        </nav>
      </section>
    </main>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<main className={styles.container}>Loading...</main>}>
      <ResetPasswordForm />
    </Suspense>
  );
}
