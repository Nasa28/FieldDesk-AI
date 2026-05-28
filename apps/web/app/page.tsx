import Link from "next/link";

export default function Home() {
  return (
    <div>
      <h1 className="page-title">FieldDesk AI</h1>
      <p className="page-subtitle">Voice-to-ticket system for field service teams.</p>
      <div className="card">
        <p>Go to the <Link href="/dashboard">dashboard</Link> to get started.</p>
      </div>
    </div>
  );
}
