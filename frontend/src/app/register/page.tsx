"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { ApiError, fetchApi } from "@/lib/api";
import styles from "../auth.module.css";
import registerStyles from "./register.module.css";

type RegistrationMode = "vendor" | "staff";

function apiErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "Registration could not be completed.";
  if (error.status === 429) return "Too many registration attempts. Please try again later.";
  const detail = error.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  return "Please check the form and try again.";
}

export default function RegisterPage() {
  const [mode, setMode] = useState<RegistrationMode>("vendor");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [fullName, setFullName] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);

  function switchMode(nextMode: RegistrationMode) {
    setMode(nextMode);
    setError("");
    setSubmitted(false);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (password !== confirmation) {
      setError("Password and confirmation do not match.");
      return;
    }
    setLoading(true);
    try {
      const payload = mode === "vendor"
        ? {
            workspace_slug: "staging",
            business_name: businessName,
            contact_name: fullName || null,
            email,
            phone: phone || null,
            username,
            password,
          }
        : {
            workspace_slug: "staging",
            username,
            email,
            password,
            full_name: fullName || null,
          };
      await fetchApi(mode === "vendor" ? "/auth/register/vendor" : "/auth/register/user", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setSubmitted(true);
    } catch (caught) {
      setError(apiErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  if (submitted) {
    return (
      <main className={styles.container} id="main-content">
        <section className={styles.card} aria-labelledby="registration-success-title">
          <div className={styles.header}>
            <h1 id="registration-success-title">Request received</h1>
            <p>Your {mode} account is pending administrator approval.</p>
          </div>
          <div className={styles.message} role="status">
            You cannot sign in until an administrator approves this request.
          </div>
          <div className={styles.links}>
            <Link href="/login">Return to sign in</Link>
            <button type="button" className={registerStyles.linkButton} onClick={() => setSubmitted(false)}>
              Submit another request
            </button>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className={styles.container} id="main-content">
      <section className={styles.card} aria-labelledby="register-title">
        <div className={styles.header}>
          <h1 id="register-title">Request an account</h1>
          <p>Choose an account type for the staging workspace.</p>
        </div>

        <div className={registerStyles.switcher} role="tablist" aria-label="Account type">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "vendor"}
            className={`${registerStyles.switchButton} ${mode === "vendor" ? registerStyles.selected : ""}`}
            onClick={() => switchMode("vendor")}
          >
            Vendor
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "staff"}
            className={`${registerStyles.switchButton} ${mode === "staff" ? registerStyles.selected : ""}`}
            onClick={() => switchMode("staff")}
          >
            Staff
          </button>
        </div>

        {error && <div className={styles.error} role="alert">{error}</div>}

        <form onSubmit={submit} className={styles.form}>
          <div className={registerStyles.workspace}>
            <strong>Workspace</strong>
            <span>staging</span>
          </div>

          {mode === "vendor" && (
            <div className={styles.inputGroup}>
              <label htmlFor="business-name">Business name</label>
              <input id="business-name" value={businessName} onChange={(event) => setBusinessName(event.target.value)} required minLength={2} autoComplete="organization" />
            </div>
          )}

          <div className={styles.inputGroup}>
            <label htmlFor="full-name">{mode === "vendor" ? "Contact name" : "Full name"}</label>
            <input id="full-name" value={fullName} onChange={(event) => setFullName(event.target.value)} autoComplete="name" />
          </div>

          <div className={styles.inputGroup}>
            <label htmlFor="registration-email">Email</label>
            <input id="registration-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required autoComplete="email" />
          </div>

          {mode === "vendor" && (
            <div className={styles.inputGroup}>
              <label htmlFor="phone">Phone (optional)</label>
              <input id="phone" type="tel" value={phone} onChange={(event) => setPhone(event.target.value)} autoComplete="tel" />
            </div>
          )}

          <div className={styles.inputGroup}>
            <label htmlFor="registration-username">Username</label>
            <input id="registration-username" value={username} onChange={(event) => setUsername(event.target.value)} required minLength={3} pattern="[A-Za-z0-9_.-]+" autoComplete="username" />
          </div>

          <div className={styles.inputGroup}>
            <label htmlFor="registration-password">Password</label>
            <input id="registration-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={8} autoComplete="new-password" />
          </div>

          <div className={styles.inputGroup}>
            <label htmlFor="registration-confirmation">Confirm password</label>
            <input id="registration-confirmation" type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} required minLength={8} autoComplete="new-password" />
          </div>

          <p className={styles.help}>An administrator will review your request before you can sign in. Roles and permissions are assigned during approval.</p>
          <button type="submit" disabled={loading} className={styles.button}>
            {loading ? "Submitting..." : `Request ${mode === "vendor" ? "vendor" : "staff"} account`}
          </button>
        </form>

        <div className={styles.links}>
          <Link href="/login">Already have an account? Sign in</Link>
        </div>
      </section>
    </main>
  );
}
