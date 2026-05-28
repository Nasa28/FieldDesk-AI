export default function ReviewQueuePage() {
  return (
    <div>
      <h1 className="page-title">Review Queue</h1>
      <p className="page-subtitle">
        Tickets and AI outputs flagged for human review (low confidence, schema failures,
        sensitive content).
      </p>
      <div className="card">Nothing waiting for review.</div>
    </div>
  );
}
