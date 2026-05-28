import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "FieldDesk AI",
  description: "Voice-to-ticket system for field service teams.",
};

const navItems = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/tickets", label: "Tickets" },
  { href: "/voice-notes", label: "Voice Notes" },
  { href: "/review-queue", label: "Review Queue" },
  { href: "/documents", label: "Documents" },
  { href: "/ai-logs", label: "AI Logs" },
  { href: "/costs", label: "Costs" },
  { href: "/failures", label: "Failures" },
  { href: "/settings", label: "Settings" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="app-shell">
          <aside className="sidebar">
            <div className="brand">FieldDesk AI</div>
            <nav>
              {navItems.map((item) => (
                <Link key={item.href} href={item.href} className="nav-link">
                  {item.label}
                </Link>
              ))}
            </nav>
          </aside>
          <main className="content">{children}</main>
        </div>
      </body>
    </html>
  );
}
