"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { loadSession } from "../lib/auth";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/tickets", label: "Tickets" },
  { href: "/voice-notes", label: "Voice Notes" },
  { href: "/review-queue", label: "Review Queue" },
  { href: "/documents", label: "Documents" },
  { href: "/knowledge", label: "Knowledge Base" },
  { href: "/ai-logs", label: "AI Logs" },
  { href: "/costs", label: "Costs" },
  { href: "/failures", label: "Failures" },
  { href: "/settings", label: "Settings" },
];

// Paths that intentionally render OUTSIDE the authed sidebar shell. Adding
// a route here also bypasses the AuthGate redirect — that's the point:
// /login and /signup obviously can't require a session, and they should
// look like a stand-alone form, not a "dashboard with a form in it."
const PUBLIC_PATHS = new Set<string>(["/login", "/signup"]);

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isPublic = PUBLIC_PATHS.has(pathname ?? "");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (isPublic) {
      setReady(true);
      return;
    }
    // We trust localStorage on mount; the real validation happens on the
    // first API call. If the stored token is expired the api.ts handler
    // will clear it and bounce back here.
    if (!loadSession()) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [isPublic, pathname, router]);

  if (isPublic) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "40px 16px",
        }}
      >
        <div style={{ width: "100%", maxWidth: 480 }}>
          <div
            className="brand"
            style={{ textAlign: "center", marginBottom: 24 }}
          >
            FieldDesk AI
          </div>
          {children}
        </div>
      </div>
    );
  }

  if (!ready) {
    // Brief blank flash while the redirect to /login resolves. Rendering
    // null beats rendering a half-shell + then yanking it.
    return null;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">FieldDesk AI</div>
        <nav>
          {NAV_ITEMS.map((item) => (
            <Link key={item.href} href={item.href} className="nav-link">
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}
