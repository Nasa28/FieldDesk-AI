"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { loadSession, type StoredSession } from "../lib/auth";

type UserRole = StoredSession["user"]["role"];
type NavItem = { href: string; label: string; roles?: UserRole[] };

const NAV_GROUPS: { title: string | null; items: NavItem[] }[] = [
  {
    title: "Workflow",
    items: [
      { href: "/assistant", label: "Assistant" },
      { href: "/tickets", label: "Tickets" },
      { href: "/knowledge", label: "Knowledge Base" },
      { href: "/review-queue", label: "Review Queue", roles: ["admin"] },
    ],
  },
  {
    title: "Insights",
    items: [
      { href: "/dashboard", label: "Dashboard", roles: ["admin"] },
    ],
  },
  {
    title: "Admin",
    items: [
      { href: "/ai-logs", label: "AI Logs", roles: ["admin"] },
      { href: "/costs", label: "Costs", roles: ["admin"] },
      { href: "/failures", label: "Failures", roles: ["admin"] },
      { href: "/settings", label: "Settings", roles: ["admin"] },
    ],
  },
];

// Paths that intentionally render outside the authed sidebar shell. Adding
// a route here also bypasses the AuthGate redirect. That is the point:
// /login and /signup obviously can't require a session, and they should
// look like a stand-alone form, not a "dashboard with a form in it."
const PUBLIC_PATHS = new Set<string>(["/login", "/signup"]);

function isActivePath(pathname: string, href: string): boolean {
  if (href === "/assistant") {
    return pathname === "/assistant" || pathname === "/voice" || pathname === "/voice-notes";
  }
  return pathname === href;
}

function initialOpenGroups(): Record<string, boolean> {
  const groups: Record<string, boolean> = {};
  for (const group of NAV_GROUPS) {
    if (group.title) groups[group.title] = true;
  }
  return groups;
}

function canShowItem(item: NavItem, role: UserRole): boolean {
  return !item.roles || item.roles.includes(role);
}

function canAccessPath(pathname: string, role: UserRole): boolean {
  if (role === "admin") return true;
  return ["/", "/assistant", "/voice", "/voice-notes", "/tickets", "/knowledge"].some((path) => {
    if (path === "/") return pathname === "/";
    return pathname === path || pathname.startsWith(`${path}/`);
  });
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isPublic = PUBLIC_PATHS.has(pathname ?? "");
  const [ready, setReady] = useState(false);
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(initialOpenGroups);
  const [session, setSession] = useState<StoredSession | null>(null);
  const role = session?.user.role ?? "member";

  useEffect(() => {
    if (isPublic) {
      setSession(null);
      setReady(true);
      return;
    }
    // We trust localStorage on mount; the real validation happens on the
    // first API call. If the stored token is expired the api.ts handler
    // will clear it and bounce back here.
    const storedSession = loadSession();
    if (!storedSession) {
      router.replace("/login");
      return;
    }
    setSession(storedSession);
    if (!canAccessPath(pathname ?? "", storedSession.user.role)) {
      setReady(false);
      router.replace("/assistant");
      return;
    }
    setReady(true);
  }, [isPublic, pathname, router]);

  useEffect(() => {
    if (!pathname) return;
    setOpenGroups((current) => {
      let changed = false;
      const next = { ...current };
      for (const group of NAV_GROUPS) {
        if (!group.title) continue;
        const hasActiveItem = group.items
          .filter((item) => canShowItem(item, role))
          .some((item) => isActivePath(pathname, item.href));
        if (hasActiveItem && next[group.title] === false) {
          next[group.title] = true;
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [pathname, role]);

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
    // null beats rendering a half-shell and then yanking it.
    return null;
  }

  if (session && !canAccessPath(pathname ?? "", role)) {
    return null;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">FieldDesk AI</div>
        <nav>
          {NAV_GROUPS.map((group, i) => {
            const items = group.items.filter((item) => canShowItem(item, role));
            if (items.length === 0) return null;
            if (!group.title) {
              return (
                <div key={`group-${i}`} className="nav-group">
                  {items.map((item) => {
                    const active = isActivePath(pathname ?? "", item.href);
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        className={`nav-link${active ? " active" : ""}`}
                        aria-current={active ? "page" : undefined}
                      >
                        {item.label}
                      </Link>
                    );
                  })}
                </div>
              );
            }
            const title = group.title;
            const open = openGroups[title] ?? true;
            return (
              <div key={title} className="nav-group">
                <button
                  type="button"
                  className="nav-group-trigger"
                  aria-expanded={open}
                  onClick={() =>
                    setOpenGroups((current) => ({
                      ...current,
                      [title]: !(current[title] ?? true),
                    }))
                  }
                >
                  <span>{title}</span>
                  <span className={`nav-group-chevron${open ? " open" : ""}`} aria-hidden />
                </button>
                {open && (
                  <div className="nav-group-items">
                    {items.map((item) => {
                      const active = isActivePath(pathname ?? "", item.href);
                      return (
                        <Link
                          key={item.href}
                          href={item.href}
                          className={`nav-link${active ? " active" : ""}`}
                          aria-current={active ? "page" : undefined}
                        >
                          {item.label}
                        </Link>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </nav>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}
