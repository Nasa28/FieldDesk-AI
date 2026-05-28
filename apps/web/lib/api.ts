const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
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
    ...init,
    headers,
  });
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      message = body.message ?? body.error ?? message;
    } catch {
      // Keep the HTTP status text when the response is not JSON.
    }
    throw new Error(message);
  }
  return (await res.json()) as T;
}

export function saveTenantId(tenantId: string) {
  window.localStorage.setItem("fielddesk.tenant_id", tenantId.trim());
}

export function currentTenantId() {
  if (typeof window === "undefined") {
    return "";
  }
  return window.localStorage.getItem("fielddesk.tenant_id") ?? "";
}
