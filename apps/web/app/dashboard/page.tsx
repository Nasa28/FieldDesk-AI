"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, currentTenantId } from "../../lib/api";
import {
  formatInt,
  formatMS,
  formatPct,
  formatUSD,
  toRFC3339,
  type TimeWindow,
} from "../../lib/dashboard";

type JobMetrics = {
  total_jobs: number;
  pending_jobs: number;
  processing_jobs: number;
  retrying_jobs: number;
  needs_review_jobs: number;
  succeeded_jobs: number;
  failed_jobs: number;
  retried_jobs: number;
};

type LatencyRow = {
  kind: string;
  sample_calls: number;
  p50_ms: number;
  p95_ms: number;
  max_ms: number;
};

type MetricsResponse = {
  jobs: JobMetrics;
  job_success_rate: number;
  job_failure_rate: number;
  job_needs_review_rate: number;
  job_retry_rate: number;
  latency_by_kind: LatencyRow[];
};

type CostsResponse = {
  rollup: {
    total_cost_usd: number;
    failed_cost_usd: number;
    total_calls: number;
  };
};

export default function DashboardPage() {
  const [tenantConfigured, setTenantConfigured] = useState<boolean | null>(null);
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [costs, setCosts] = useState<CostsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setTenantConfigured(Boolean(currentTenantId()));
  }, []);

  async function load() {
    const window = todayWindow();
    const params = new URLSearchParams({
      from: toRFC3339(window.from),
      to: toRFC3339(window.to),
    });
    setLoading(true);
    setError("");
    try {
      const [metricsRes, costsRes] = await Promise.all([
        api<MetricsResponse>(`/v1/admin/metrics?${params}`),
        api<CostsResponse>(`/v1/admin/costs?${params}`),
      ]);
      setMetrics(metricsRes);
      setCosts(costsRes);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load dashboard.");
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
        <h1 className="page-title">Dashboard</h1>
      </div>
    );
  }
  if (!tenantConfigured) {
    return <NoTenant />;
  }

  const llmLatency = metrics?.latency_by_kind.find((row) => row.kind === "llm");
  const transcriptionLatency = metrics?.latency_by_kind.find((row) => row.kind === "transcription");
  const cards = [
    { label: "Cost today", value: formatUSD(costs?.rollup.total_cost_usd ?? 0) },
    { label: "Failed cost today", value: formatUSD(costs?.rollup.failed_cost_usd ?? 0), accent: (costs?.rollup.failed_cost_usd ?? 0) > 0 },
    { label: "Model calls today", value: formatInt(costs?.rollup.total_calls ?? 0) },
    { label: "Job success rate", value: formatPct(metrics?.job_success_rate ?? 0) },
    { label: "Job failure rate", value: formatPct(metrics?.job_failure_rate ?? 0), accent: (metrics?.job_failure_rate ?? 0) > 0 },
    { label: "Needs review jobs", value: formatInt(metrics?.jobs.needs_review_jobs ?? 0), accent: (metrics?.jobs.needs_review_jobs ?? 0) > 0 },
    { label: "Retrying jobs", value: formatInt(metrics?.jobs.retrying_jobs ?? 0), accent: (metrics?.jobs.retrying_jobs ?? 0) > 0 },
    { label: "LLM p95 latency", value: llmLatency ? formatMS(llmLatency.p95_ms) : "—" },
    { label: "Transcription p95 latency", value: transcriptionLatency ? formatMS(transcriptionLatency.p95_ms) : "—" },
  ];

  return (
    <div>
      <h1 className="page-title">Dashboard</h1>
      <p className="page-subtitle">High-level health of the FieldDesk AI pipeline today.</p>
      <div className="toolbar">
        <button className="primary" disabled={loading} onClick={() => void load()}>
          {loading ? "Loading…" : "Refresh"}
        </button>
        {error && <span className="error">{error}</span>}
      </div>
      <div className="grid two">
        {cards.map((card) => (
          <Metric key={card.label} {...card} />
        ))}
      </div>
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

function todayWindow(): TimeWindow {
  const now = new Date();
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  return { from: toLocalInput(start), to: toLocalInput(now) };
}

function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

function NoTenant() {
  return (
    <div>
      <h1 className="page-title">Dashboard</h1>
      <p className="page-subtitle">Set a tenant ID first.</p>
      <div className="card">
        <Link href="/settings">Open Settings →</Link>
      </div>
    </div>
  );
}
