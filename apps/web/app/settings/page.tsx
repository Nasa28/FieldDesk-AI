"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { BudgetsCard } from "../../components/budgets-card";
import { ApiError, api } from "../../lib/api";
import { StoredSession, clearSession, loadSession } from "../../lib/auth";

export default function SettingsPage() {
  const router = useRouter();
  const [session, setSession] = useState<StoredSession | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setSession(loadSession());
  }, []);

  async function signOut() {
    setSigningOut(true);
    setError("");
    try {
      // Best-effort: even if the API call fails (e.g. token already expired
      // on the server), we still want to clear local state and redirect.
      await api("/v1/auth/logout", { method: "POST", skipUnauthorizedRedirect: true });
    } catch (err) {
      if (err instanceof ApiError && err.status !== 401) {
        setError(err.message);
      }
    } finally {
      clearSession();
      router.replace("/login");
    }
  }

  const apiUrl =
    (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) ||
    "http://localhost:8080";

  return (
    <div>
      <h1 className="page-title">Settings</h1>
      <p className="page-subtitle">
        Account, budgets, and runtime configuration.
      </p>

      <div className="card">
        <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
          Account
        </div>
        {session ? (
          <div className="grid two" style={{ marginBottom: 16 }}>
            <div>
              <div className="muted" style={{ fontSize: 12 }}>Tenant</div>
              <div>{session.tenant.name}</div>
              <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                <code>{session.tenant.slug}</code> ·{" "}
                <code style={{ fontSize: 11 }}>{session.tenant.id}</code>
              </div>
            </div>
            <div>
              <div className="muted" style={{ fontSize: 12 }}>Signed in as</div>
              <div>{session.user.full_name ?? session.user.email}</div>
              <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                {session.user.email} · <span className="pill">{session.user.role}</span>
              </div>
            </div>
          </div>
        ) : (
          <p className="muted">Not signed in.</p>
        )}
        <div className="toolbar" style={{ marginBottom: 0 }}>
          <button onClick={signOut} disabled={signingOut || !session}>
            {signingOut ? "Signing out…" : "Sign out"}
          </button>
        </div>
        {error && <p className="error" style={{ marginTop: 8 }}>{error}</p>}
      </div>

      <div className="card">
        <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
          API base URL
        </div>
        <div>{apiUrl}</div>
        <div className="muted" style={{ fontSize: 12, marginTop: 12 }}>
          Override with <code>NEXT_PUBLIC_API_URL</code> at build time.
        </div>
      </div>

      <BudgetsCard tenantId={session?.tenant.id ?? ""} />

      <div className="card">
        <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
          Deferred to a later slice
        </div>
        <ul style={{ margin: 0, paddingLeft: 20 }}>
          <li>Password reset / change-password flow.</li>
          <li>User invitation flow (today, signup creates a new tenant).</li>
          <li>
            <code>max_cost_per_ticket</code> enforcement — accepted by the API,
            not yet checked at runtime (needs the JSONB denormalization).
          </li>
          <li>Provider routing / model preferences.</li>
        </ul>
      </div>
    </div>
  );
}
