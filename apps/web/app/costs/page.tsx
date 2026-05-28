"use client";

import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import {
  defaultWindow,
  formatInt,
  formatTimestamp,
  formatUSD,
  toRFC3339,
  type TimeWindow,
} from "../../lib/dashboard";

type Rollup = {
  total_cost_usd: number;
  success_cost_usd: number;
  failed_cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  total_calls: number;
  successful_calls: number;
  failed_calls: number;
};

type ByKindRow = {
  kind: string;
  total_cost_usd: number;
  failed_cost_usd: number;
  total_calls: number;
  failed_calls: number;
};

type ByModelRow = {
  provider: string;
  model: string;
  total_cost_usd: number;
  failed_cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  total_calls: number;
  failed_calls: number;
};

type CostsResponse = {
  window: { from: string; to: string };
  rollup: Rollup;
  by_kind: ByKindRow[];
  by_model: ByModelRow[];
};

type ByTicketRow = {
  ticket_id: string;
  issue_summary?: string | null;
  customer_name?: string | null;
  status: string;
  total_cost_usd: number;
  failed_cost_usd: number;
  call_count: number;
  created_at: string;
};

type CostsByTicketResponse = {
  window: { from: string; to: string };
  ticket_count: number;
  avg_cost_per_ticket_usd: number;
  top_tickets: ByTicketRow[];
};

// Top-N tickets to fetch. The endpoint caps at 100 server-side; 10 is
// the dashboard-friendly default — operators who need more can deep-link.
const TOP_TICKETS_LIMIT = 10;

export default function CostsPage() {
  const [range, setRange] = useState<TimeWindow>(defaultWindow());
  const [data, setData] = useState<CostsResponse | null>(null);
  const [byTicket, setByTicket] = useState<CostsByTicketResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        from: toRFC3339(range.from),
        to: toRFC3339(range.to),
      });
      const byTicketParams = new URLSearchParams(params);
      byTicketParams.set("limit", String(TOP_TICKETS_LIMIT));
      // Parallel: both endpoints scan ai_model_calls but on different
      // indexes (created_at vs ticket_id), so no point serializing.
      const [costsRes, byTicketRes] = await Promise.all([
        api<CostsResponse>(`/v1/admin/costs?${params}`),
        api<CostsByTicketResponse>(`/v1/admin/costs/by-ticket?${byTicketParams}`),
      ]);
      setData(costsRes);
      setByTicket(byTicketRes);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load costs.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <h1 className="page-title">Costs</h1>
      <p className="page-subtitle">
        Spend per <code>ai_model_calls</code> row, broken down by kind and by
        model. Successful and failed cost are separated — failed calls still
        cost money.
      </p>

      <div className="toolbar">
        <label className="field">
          <span>From</span>
          <input
            type="datetime-local"
            value={range.from}
            onChange={(e) => setRange({ ...range, from: e.target.value })}
          />
        </label>
        <label className="field">
          <span>To</span>
          <input
            type="datetime-local"
            value={range.to}
            onChange={(e) => setRange({ ...range, to: e.target.value })}
          />
        </label>
        <button className="primary" disabled={loading} onClick={() => void load()}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {data && (
        <>
          <div className="grid two">
            <Metric label="Total cost" value={formatUSD(data.rollup.total_cost_usd)} />
            <Metric label="Failed cost" value={formatUSD(data.rollup.failed_cost_usd)} accent={data.rollup.failed_cost_usd > 0} />
            <Metric label="Successful cost" value={formatUSD(data.rollup.success_cost_usd)} />
            <Metric label="Total calls" value={formatInt(data.rollup.total_calls)} />
            <Metric label="Input tokens" value={formatInt(data.rollup.input_tokens)} />
            <Metric label="Output tokens" value={formatInt(data.rollup.output_tokens)} />
          </div>

          <h2 className="page-subtitle" style={{ marginTop: 24 }}>By kind</h2>
          <div className="card" style={{ padding: 0 }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Kind</th>
                  <th>Total cost</th>
                  <th>Failed cost</th>
                  <th>Calls</th>
                  <th>Failed calls</th>
                </tr>
              </thead>
              <tbody>
                {data.by_kind.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted" style={{ padding: 16 }}>
                      No calls in this range.
                    </td>
                  </tr>
                )}
                {data.by_kind.map((row) => (
                  <tr key={row.kind}>
                    <td>{row.kind}</td>
                    <td>{formatUSD(row.total_cost_usd)}</td>
                    <td className={row.failed_cost_usd > 0 ? "error" : "muted"}>
                      {formatUSD(row.failed_cost_usd)}
                    </td>
                    <td>{formatInt(row.total_calls)}</td>
                    <td className={row.failed_calls > 0 ? "error" : "muted"}>
                      {formatInt(row.failed_calls)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h2 className="page-subtitle" style={{ marginTop: 24 }}>By provider / model</h2>
          <div className="card" style={{ padding: 0 }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Model</th>
                  <th>Total cost</th>
                  <th>Failed cost</th>
                  <th>Input tok</th>
                  <th>Output tok</th>
                  <th>Calls</th>
                </tr>
              </thead>
              <tbody>
                {data.by_model.length === 0 && (
                  <tr>
                    <td colSpan={7} className="muted" style={{ padding: 16 }}>
                      No calls in this range.
                    </td>
                  </tr>
                )}
                {data.by_model.map((row) => (
                  <tr key={`${row.provider}::${row.model}`}>
                    <td>{row.provider}</td>
                    <td>{row.model}</td>
                    <td>{formatUSD(row.total_cost_usd)}</td>
                    <td className={row.failed_cost_usd > 0 ? "error" : "muted"}>
                      {formatUSD(row.failed_cost_usd)}
                    </td>
                    <td>{formatInt(row.input_tokens)}</td>
                    <td>{formatInt(row.output_tokens)}</td>
                    <td>{formatInt(row.total_calls)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {byTicket && (
        <>
          <h2 className="page-subtitle" style={{ marginTop: 24 }}>By ticket</h2>
          <div className="grid two">
            <Metric
              label="Tickets with attributed spend"
              value={formatInt(byTicket.ticket_count)}
            />
            <Metric
              label="Avg cost per ticket"
              value={formatUSD(byTicket.avg_cost_per_ticket_usd)}
            />
          </div>
          <div className="card" style={{ padding: 0, marginTop: 16 }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Ticket</th>
                  <th>Status</th>
                  <th>Total cost</th>
                  <th>Failed cost</th>
                  <th>Calls</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {byTicket.top_tickets.length === 0 && (
                  <tr>
                    <td colSpan={6} className="muted" style={{ padding: 16 }}>
                      No tickets with attributed spend in this range.
                    </td>
                  </tr>
                )}
                {byTicket.top_tickets.map((row) => (
                  <tr key={row.ticket_id}>
                    <td>
                      <div>{row.issue_summary || row.customer_name || "(no summary)"}</div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        <code>{row.ticket_id.slice(0, 8)}</code>
                        {row.customer_name && row.issue_summary
                          ? ` · ${row.customer_name}`
                          : ""}
                      </div>
                    </td>
                    <td><span className="pill">{row.status}</span></td>
                    <td>{formatUSD(row.total_cost_usd)}</td>
                    <td className={row.failed_cost_usd > 0 ? "error" : "muted"}>
                      {formatUSD(row.failed_cost_usd)}
                    </td>
                    <td>{formatInt(row.call_count)}</td>
                    <td className="muted">{formatTimestamp(row.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function Metric({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="card" style={{ margin: 0 }}>
      <div className="muted" style={{ fontSize: 12 }}>{label}</div>
      <div
        style={{
          fontSize: 24,
          fontWeight: 600,
          marginTop: 4,
          color: accent ? "#ff8f8f" : undefined,
        }}
      >
        {value}
      </div>
    </div>
  );
}

