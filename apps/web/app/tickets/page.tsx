"use client";

import { useEffect, useState } from "react";
import { api, currentTenantId, saveTenantId } from "../../lib/api";

type Ticket = {
  id: string;
  status: string;
  customer_name?: string;
  customer_phone?: string;
  service_address?: string;
  trade_type?: string;
  issue_summary?: string;
  detailed_description?: string;
  priority?: string;
  required_skills: string[];
  confidence?: number;
  created_at: string;
};

type Draft = {
  customer_name: string;
  customer_phone: string;
  service_address: string;
  trade_type: string;
  issue_summary: string;
  detailed_description: string;
  priority: string;
  required_skills: string;
};

function draftFromTicket(ticket: Ticket): Draft {
  return {
    customer_name: ticket.customer_name ?? "",
    customer_phone: ticket.customer_phone ?? "",
    service_address: ticket.service_address ?? "",
    trade_type: ticket.trade_type ?? "",
    issue_summary: ticket.issue_summary ?? "",
    detailed_description: ticket.detailed_description ?? "",
    priority: ticket.priority ?? "normal",
    required_skills: (ticket.required_skills ?? []).join(", "),
  };
}

export default function TicketsPage() {
  const [tenantId, setTenantId] = useState("");
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    const stored = currentTenantId();
    setTenantId(stored);
    if (stored) {
      void load();
    }
  }, []);

  async function load() {
    setError("");
    if (tenantId.trim()) {
      saveTenantId(tenantId);
    }
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    const res = await api<{ tickets: Ticket[] }>(`/v1/tickets${query}`);
    setTickets(res.tickets);
    setDrafts(Object.fromEntries(res.tickets.map((t) => [t.id, draftFromTicket(t)])));
  }

  function updateDraft(id: string, patch: Partial<Draft>) {
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  }

  async function save(ticket: Ticket) {
    const draft = drafts[ticket.id];
    setBusy(ticket.id);
    setError("");
    try {
      await api<Ticket>(`/v1/tickets/${ticket.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          customer_name: draft.customer_name,
          customer_phone: draft.customer_phone,
          service_address: draft.service_address,
          trade_type: draft.trade_type,
          issue_summary: draft.issue_summary,
          detailed_description: draft.detailed_description,
          priority: draft.priority,
          required_skills: draft.required_skills
            .split(",")
            .map((v) => v.trim())
            .filter(Boolean),
        }),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save ticket.");
    } finally {
      setBusy(null);
    }
  }

  async function approve(ticket: Ticket) {
    setBusy(ticket.id);
    setError("");
    try {
      await api<Ticket>(`/v1/tickets/${ticket.id}/approve`, { method: "POST" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not approve ticket.");
    } finally {
      setBusy(null);
    }
  }

  async function reject(ticket: Ticket) {
    const reason = window.prompt("Reason") ?? "";
    setBusy(ticket.id);
    setError("");
    try {
      await api<Ticket>(`/v1/tickets/${ticket.id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason }),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reject ticket.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <h1 className="page-title">Tickets</h1>
      <div className="toolbar">
        <label className="field">
          <span>Tenant ID</span>
          <input value={tenantId} onChange={(e) => setTenantId(e.target.value)} />
        </label>
        <label className="field">
          <span>Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            <option value="draft">Draft</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>
        </label>
        <button disabled={!tenantId.trim()} onClick={() => void load()}>
          Refresh
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="stack">
        {tickets.map((ticket) => {
          const draft = drafts[ticket.id] ?? draftFromTicket(ticket);
          return (
            <div className="card" key={ticket.id}>
              <div className="toolbar">
                <span className="pill">{ticket.status}</span>
                <span className="muted">{ticket.id}</span>
                <button disabled={busy === ticket.id} onClick={() => void save(ticket)}>
                  Save
                </button>
                <button className="primary" disabled={busy === ticket.id} onClick={() => void approve(ticket)}>
                  Approve
                </button>
                <button disabled={busy === ticket.id} onClick={() => void reject(ticket)}>
                  Reject
                </button>
              </div>
              <div className="grid two">
                <label className="field">
                  <span>Customer</span>
                  <input value={draft.customer_name} onChange={(e) => updateDraft(ticket.id, { customer_name: e.target.value })} />
                </label>
                <label className="field">
                  <span>Phone</span>
                  <input value={draft.customer_phone} onChange={(e) => updateDraft(ticket.id, { customer_phone: e.target.value })} />
                </label>
                <label className="field">
                  <span>Address</span>
                  <input value={draft.service_address} onChange={(e) => updateDraft(ticket.id, { service_address: e.target.value })} />
                </label>
                <label className="field">
                  <span>Trade</span>
                  <input value={draft.trade_type} onChange={(e) => updateDraft(ticket.id, { trade_type: e.target.value })} />
                </label>
                <label className="field">
                  <span>Priority</span>
                  <select value={draft.priority} onChange={(e) => updateDraft(ticket.id, { priority: e.target.value })}>
                    <option value="low">Low</option>
                    <option value="normal">Normal</option>
                    <option value="high">High</option>
                    <option value="urgent">Urgent</option>
                  </select>
                </label>
                <label className="field">
                  <span>Skills</span>
                  <input value={draft.required_skills} onChange={(e) => updateDraft(ticket.id, { required_skills: e.target.value })} />
                </label>
              </div>
              <label className="field" style={{ marginTop: 12 }}>
                <span>Summary</span>
                <input value={draft.issue_summary} onChange={(e) => updateDraft(ticket.id, { issue_summary: e.target.value })} />
              </label>
              <label className="field" style={{ marginTop: 12 }}>
                <span>Description</span>
                <textarea value={draft.detailed_description} onChange={(e) => updateDraft(ticket.id, { detailed_description: e.target.value })} />
              </label>
            </div>
          );
        })}
        {tickets.length === 0 && <div className="card muted">No tickets.</div>}
      </div>
    </div>
  );
}
