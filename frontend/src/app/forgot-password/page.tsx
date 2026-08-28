"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { ApiError, fetchApi } from "@/lib/api";
import styles from "../auth.module.css";

export default function ForgotPasswordPage() {
  const [workspace, setWorkspace] = useState("");
  const [usernameOrEmail, setUsernameOrEmail] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setMessage("");
    setError("");
    setLoading(true);
    try {
      await fetchApi("/auth/password-reset/request", {
        method: "POST",
        body: JSON.stringify({
          workspace_slug: workspace.trim().toLowerCase(),
          username_or_email: usernameOrEmail.trim(),
        }),
      });
      setMessage(
        "If the account exists and email delivery is configured, a reset link will be sent."
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setError("Password-reset email delivery is not configured. Contact an administrator.");
      } else if (err instanceof ApiError && err.status === 429) {
        setError("Too many reset requests. Please try again later.");
      } else {
        setError("We could not process the reset request. Please check the details and try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className={styles.container} id="main-content">
      <section className={styles.card} aria-labelledby="forgot-password-title">
        <header className={styles.header}>
          <h1 id="forgot-password-title">Reset your password</h1>
          <p>Enter your workspace and login ID or email address.</p>
        </header>

        {message && <div className={styles.message} role="status">{message}</div>}
        {error && <div className={styles.error} role="alert">{error}</div>}

        <form onSubmit={handleSubmit} className={styles.form}>
          <div className={styles.inputGroup}>
            <label htmlFor="workspace">Workspace slug</label>
            <input
              id="workspace"
              value={workspace}
              onChange={(event) => setWorkspace(event.target.value)}
              autoComplete="organization"
              required
            />
          </div>
          <div className={styles.inputGroup}>
            <label htmlFor="username-or-email">Login ID or email</label>
            <input
              id="username-or-email"
              value={usernameOrEmail}
              onChange={(event) => setUsernameOrEmail(event.target.value)}
              autoComplete="username"
              required
            />
          </div>
          <button type="submit" disabled={loading} className={styles.button}>
            {loading ? "Sending..." : "Send reset link"}
          </button>
        </form>

        <nav className={styles.links} aria-label="Authentication links">
          <Link href="/login">Back to sign in</Link>
          <Link href="/register">Register as a vendor</Link>
        </nav>
      </section>
    </main>
  );
}
