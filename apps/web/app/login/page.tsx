"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ApiError, api } from "../../lib/api";
import { AuthResponse, loadSession, saveSession } from "../../lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [tenantSlug, setTenantSlug] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
    try {
      const resp = await api<AuthResponse>("/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({
          tenant_slug: tenantSlug.trim(),
          email: email.trim(),
          password,
        }),
        skipUnauthorizedRedirect: true,
      });
      saveSession(resp);
      router.replace("/");
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not log in";
      setError(message);
      setSubmitting(false);
    }
  }

  return (
    <div className="card" style={{ maxWidth: 420, margin: "0 auto" }}>
      <h1 className="page-title">Sign in</h1>
      <p className="page-subtitle">
        Use the tenant slug + email + password you created on signup.
      </p>
      <form onSubmit={handleSubmit} className="stack" style={{ gap: 12 }}>
        <label className="field">
          <span>Tenant slug</span>
          <input
            autoFocus
            value={tenantSlug}
            onChange={(e) => setTenantSlug(e.target.value)}
            placeholder="acme-plumbing"
            required
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
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <p className="error" style={{ margin: 0 }}>{error}</p>}
        <button
          type="submit"
          className="primary"
          disabled={submitting || !tenantSlug.trim() || !email.trim() || !password}
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="muted" style={{ marginTop: 16, fontSize: 13 }}>
        No account yet? <Link href="/signup" style={{ textDecoration: "underline" }}>Create one</Link>.
      </p>
    </div>
  );
}
