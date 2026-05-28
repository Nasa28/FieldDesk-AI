export default function DashboardPage() {
  const cards = [
    { label: "Tickets today", value: "—" },
    { label: "Voice notes pending", value: "—" },
    { label: "Avg extraction latency", value: "—" },
    { label: "Cost today", value: "$—" },
    { label: "Job success rate", value: "—" },
    { label: "Awaiting human review", value: "—" },
  ];
  return (
    <div>
      <h1 className="page-title">Dashboard</h1>
      <p className="page-subtitle">High-level health of the FieldDesk AI pipeline.</p>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "16px" }}>
        {cards.map((c) => (
          <div key={c.label} className="card">
            <div style={{ color: "var(--muted)", fontSize: 12 }}>{c.label}</div>
            <div style={{ fontSize: 24, fontWeight: 600, marginTop: 4 }}>{c.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
