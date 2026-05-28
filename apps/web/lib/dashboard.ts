// Shared formatting and window-defaulting helpers for the cost/metrics/logs/failures
// pages. The API enforces both defaults and bounds; these mirror them on the client
// so the inputs always show valid values.

export type TimeWindow = { from: string; to: string };

export function defaultWindow(): TimeWindow {
  const now = new Date();
  const past = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
  return { from: toLocalInput(past), to: toLocalInput(now) };
}

// <input type="datetime-local"> wants "YYYY-MM-DDTHH:mm" in the user's local zone.
function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

// Convert "YYYY-MM-DDTHH:mm" (local) into an RFC3339 UTC string for the API.
export function toRFC3339(localValue: string): string {
  if (!localValue) return "";
  const d = new Date(localValue);
  if (Number.isNaN(d.getTime())) return "";
  return d.toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function formatUSD(n: number): string {
  if (!Number.isFinite(n)) return "$0";
  if (n === 0) return "$0.0000";
  // Show enough decimals to see fractions of a cent — embeddings can run
  // at $0.0001 per call and would otherwise round to "$0.00".
  const abs = Math.abs(n);
  if (abs >= 1) return `$${n.toFixed(2)}`;
  if (abs >= 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(6)}`;
}

export function formatInt(n: number): string {
  if (!Number.isFinite(n)) return "0";
  return n.toLocaleString();
}

export function formatPct(fraction: number): string {
  if (!Number.isFinite(fraction)) return "0%";
  return `${(fraction * 100).toFixed(1)}%`;
}

export function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

export function formatMS(ms: number): string {
  if (!Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}
