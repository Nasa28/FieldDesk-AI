"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ApiError, api } from "../../lib/api";
import { AuthResponse, loadSession, saveSession } from "../../lib/auth";

type SignupBody = {
  tenant_name: string;
  tenant_slug?: string;
  email: string;
  password: string;
  full_name?: string;
};

export default function SignupPage() {
  const router = useRouter();
  const [tenantName, setTenantName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (loadSession()) {
      router.replace("/");
    }
  }, [router]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    const body: SignupBody = {
      tenant_name: tenantName.trim(),
      email: email.trim(),
      password,
    };
    if (fullName.trim()) body.full_name = fullName.trim();
    try {
      const resp = await api<AuthResponse>("/v1/auth/signup", {
        method: "POST",
        body: JSON.stringify(body),
        skipUnauthorizedRedirect: true,
      });
      saveSession(resp);
      router.replace("/");
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not create account";
      setError(message);
      setSubmitting(false);
    }
  }

  const passwordTooShort = password.length > 0 && password.length < 8;

  return (
    <div className="card" style={{ maxWidth: 420, margin: "0 auto" }}>
      <h1 className="page-title">Create account</h1>
      <p className="page-subtitle">
        Signup creates a new tenant with you as the admin. The slug is
        derived from the tenant name.
      </p>
      <form onSubmit={handleSubmit} className="stack" style={{ gap: 12 }}>
        <label className="field">
          <span>Tenant / company name</span>
          <input
            autoFocus
            value={tenantName}
            onChange={(e) => setTenantName(e.target.value)}
            placeholder="Acme Plumbing"
            required
          />
        </label>
        <label className="field">
          <span>Your full name (optional)</span>
          <input
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            placeholder="Jordan Smith"
          />
        </label>
        <label className="field">
          <span>Email</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label className="field">
          <span>Password (min 8 chars)</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
          />
          {passwordTooShort && (
            <span className="error" style={{ fontSize: 12 }}>
              Password must be at least 8 characters.
            </span>
          )}
        </label>
        {error && <p className="error" style={{ margin: 0 }}>{error}</p>}
        <button
          type="submit"
          className="primary"
          disabled={
            submitting ||
            !tenantName.trim() ||
            !email.trim() ||
            password.length < 8
          }
        >
          {submitting ? "Creating account…" : "Create account"}
        </button>
      </form>
      <p className="muted" style={{ marginTop: 16, fontSize: 13 }}>
        Already have an account? <Link href="/login" style={{ textDecoration: "underline" }}>Sign in</Link>.
      </p>
    </div>
  );
}
