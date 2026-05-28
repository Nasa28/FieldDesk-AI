import { clearSession } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

export type ApiOptions = RequestInit & {
  // skipUnauthorizedRedirect: callers that already handle 401 inline (login,
  // signup) opt out of the global redirect so a wrong-password attempt
  // doesn't bounce the user back to /login while they're submitting it.
  skipUnauthorizedRedirect?: boolean;
};

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export async function api<T = unknown>(path: string, init: ApiOptions = {}): Promise<T> {
  const { skipUnauthorizedRedirect, ...fetchInit } = init;
  const headers = new Headers(fetchInit.headers);
  if (fetchInit.body && !(fetchInit.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (typeof window !== "undefined") {
    const token = window.localStorage.getItem("fielddesk.token");
    const tenantId = window.localStorage.getItem("fielddesk.tenant_id");
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    } else if (tenantId) {
      headers.set("X-Tenant-ID", tenantId);
    }
  }
  const res = await fetch(`${API_URL}${path}`, {
    ...fetchInit,
    headers,
  });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    let code = "http_error";
    try {
      const body = await res.json();
      message = body.message ?? body.error ?? message;
      code = body.error ?? code;
    } catch {
      // Keep the HTTP status text when the response is not JSON.
    }
    if (res.status === 401 && !skipUnauthorizedRedirect && typeof window !== "undefined") {
      // Token expired or invalid mid-session. Clear it and bounce to login;
      // the login page itself sets skipUnauthorizedRedirect so a wrong
      // password doesn't loop here.
      clearSession();
      if (window.location.pathname !== "/login") {
        window.location.assign("/login");
      }
    }
    throw new ApiError(res.status, code, message);
  }
  return (await res.json()) as T;
}

