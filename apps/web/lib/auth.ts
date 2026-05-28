// Auth state lives in localStorage; there's no server-side session because
// the API treats the bearer token as the source of truth. We mirror the
// tenant id alongside the token so the existing X-Tenant-ID fallback in
// api.ts stays useful for dev (and so the rest of the UI can read the
// tenant id synchronously without re-fetching /me).

const TOKEN_KEY = "fielddesk.token";
const TENANT_ID_KEY = "fielddesk.tenant_id";
const SESSION_KEY = "fielddesk.session";

export type SessionTenant = {
  id: string;
  slug: string;
  name: string;
};

export type SessionUser = {
  id: string;
  email: string;
  full_name: string | null;
  role: "admin" | "member";
};

export type AuthResponse = {
  token: string;
  expires_at: string;
  tenant: SessionTenant;
  user: SessionUser;
};

export type StoredSession = {
  token: string;
  expires_at: string;
  tenant: SessionTenant;
  user: SessionUser;
};

export function saveSession(resp: AuthResponse): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, resp.token);
  window.localStorage.setItem(TENANT_ID_KEY, resp.tenant.id);
  window.localStorage.setItem(
    SESSION_KEY,
    JSON.stringify({
      token: resp.token,
      expires_at: resp.expires_at,
      tenant: resp.tenant,
      user: resp.user,
    } satisfies StoredSession),
  );
}

export function loadSession(): StoredSession | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(SESSION_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StoredSession;
  } catch {
    // Corrupt session blob (hand-edited, version skew). Clear it so the
    // UI doesn't ping-pong between "logged in" and 401.
    clearSession();
    return null;
  }
}

export function clearSession(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(SESSION_KEY);
  // Leave TENANT_ID_KEY alone: a user who just logged out of one tenant
  // might re-log into the same one, and the dev X-Tenant-ID fallback
  // shouldn't be silently cleared by logout.
}

export function currentToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(TOKEN_KEY) ?? "";
}
