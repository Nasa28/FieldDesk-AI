"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, currentTenantId } from "../../lib/api";
import {
  defaultWindow,
  formatInt,
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

export default function CostsPage() {
  const [range, setRange] = useState<TimeWindow>(defaultWindow());
  const [data, setData] = useState<CostsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [tenantConfigured, setTenantConfigured] = useState<boolean | null>(null);

  useEffect(() => {
    setTenantConfigured(Boolean(currentTenantId()));
  }, []);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        from: toRFC3339(range.from),
        to: toRFC3339(range.to),
      });
      const res = await api<CostsResponse>(`/v1/admin/costs?${params}`);
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load costs.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (tenantConfigured) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantConfigured]);

  if (tenantConfigured === null) {
    return (
      <div>
        <h1 className="page-title">Costs</h1>
      </div>
    );
  }
  if (!tenantConfigured) {
    return <NoTenant />;
  }

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

function NoTenant() {
  return (
    <div>
      <h1 className="page-title">Costs</h1>
      <p className="page-subtitle">
        Your session does not have a tenant associated with it yet. Sign
        out and back in to refresh.
      </p>
      <div className="card">
        <Link href="/settings">Open Settings →</Link>
      </div>
    </div>
  );
}
