export default function AILogsPage() {
  return (
    <div>
      <h1 className="page-title">AI Logs</h1>
      <p className="page-subtitle">Every model call: provider, model, tokens, latency, cost, success.</p>
      <div className="card">No model calls logged yet.</div>
    </div>
  );
}
