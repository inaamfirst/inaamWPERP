"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { ApiError, fetchApi } from "@/lib/api";
import styles from "../auth.module.css";

export default function LoginPage() {
  const [workspace, setWorkspace] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const { checkAuth } = useAuth();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const response = await fetchApi("/auth/login", {
        method: "POST",
        body: JSON.stringify({
          workspace_slug: workspace,
          username,
          password,
          supports_refresh: true,
        }),
      });

      if (response) {
        const authenticatedUser = await checkAuth();
        router.replace(authenticatedUser?.must_change_password ? "/change-password" : "/");
      }
    } catch (err: unknown) {
      const detail = err instanceof ApiError ? String(err.data?.detail || "") : "";
      const normalized = detail.toLowerCase();
      if (err instanceof ApiError && err.status === 429) {
        setError("Too many sign-in attempts. Please try again later.");
      } else if (normalized.includes("pending")) {
        setError("Your account is awaiting administrator approval.");
      } else if (
        normalized.includes("paused") ||
        normalized.includes("stopped") ||
        normalized.includes("not active")
      ) {
        setError("Your vendor account is currently unavailable. Contact an administrator.");
      } else {
        setError("Unable to sign in with those credentials.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className={styles.container} id="main-content">
      <section className={styles.card} aria-labelledby="login-title">
        <div className={styles.header}>
          <h1 id="login-title">Welcome Back</h1>
          <p>Sign in to your ERP dashboard</p>
        </div>

        {error && <div className={styles.error} role="alert">{error}</div>}

        <form onSubmit={handleLogin} className={styles.form}>
          <div className={styles.inputGroup}>
            <label htmlFor="workspace">Workspace Slug</label>
            <input
              id="workspace"
              type="text"
              value={workspace}
              onChange={(e) => setWorkspace(e.target.value)}
              placeholder="e.g. platform"
              required
            />
          </div>

          <div className={styles.inputGroup}>
            <label htmlFor="username">Username or Email</label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>

          <div className={styles.inputGroup}>
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <button type="submit" disabled={loading} className={styles.button}>
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </form>

        <div className={styles.links}>
          <Link href="/forgot-password">Forgot password?</Link>
          <Link href="/register">Request an account</Link>
        </div>
      </section>
    </main>
  );
}
