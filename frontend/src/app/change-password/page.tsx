"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { ApiError, fetchApi } from "@/lib/api";
import styles from "../auth.module.css";

export default function ChangePasswordPage() {
  const { user, checkAuth } = useAuth();
  const router = useRouter();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (newPassword !== confirmPassword) {
      setError("New passwords do not match.");
      return;
    }
    setSaving(true);
    try {
      await fetchApi("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      await checkAuth();
      router.replace(user ? "/" : "/login");
    } catch (err: unknown) {
      setError(err instanceof ApiError ? String(err.data?.detail || err.message) : "Unable to change password.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className={styles.container} id="main-content">
      <section className={styles.card} aria-labelledby="change-password-title">
        <div className={styles.header}>
          <h1 id="change-password-title">Change your password</h1>
          <p>A password change is required before opening your workspace.</p>
        </div>
        {error && <div className={styles.error} role="alert">{error}</div>}
        <form onSubmit={submit} className={styles.form}>
          <div className={styles.inputGroup}>
            <label htmlFor="current-password">Current password</label>
            <input id="current-password" type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required />
          </div>
          <div className={styles.inputGroup}>
            <label htmlFor="new-password">New password</label>
            <input id="new-password" type="password" minLength={8} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required />
          </div>
          <div className={styles.inputGroup}>
            <label htmlFor="confirm-password">Confirm new password</label>
            <input id="confirm-password" type="password" minLength={8} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} required />
          </div>
          <button type="submit" disabled={saving} className={styles.button}>{saving ? "Saving..." : "Save password"}</button>
        </form>
      </section>
    </main>
  );
}
