"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, RunOut } from "@/lib/client";
import { Empty, Loading } from "@/components/States";

export default function Runs() {
  const [runs, setRuns] = useState<RunOut[] | null>(null);
  useEffect(() => {
    const f = () => api.GET("/api/runs").then(({ data }) => setRuns(data || []));
    f();
    const t = setInterval(f, 4000);
    return () => clearInterval(t);
  }, []);
  if (!runs) return <Loading what="Loading runs" />;
  return (
    <div><h1>Agent runs</h1>
      {runs.length === 0 ? <Empty>No runs yet.</Empty> : (
        <div className="panel" style={{ padding: 0 }}><table className="responsive">
          <thead><tr><th>Run</th><th>Kind</th><th>Subject</th><th>Status</th><th>Tokens</th><th>Cost</th><th>Started</th></tr></thead>
          <tbody>{runs.map((r) => (<tr key={r.id}>
            <td data-label="Run"><Link href={`/runs/${r.id}`}>{r.id}</Link></td><td data-label="Kind">{r.kind}</td>
            <td data-label="Subject">{r.subject}</td><td data-label="Status">{r.status}</td><td data-label="Tokens">{r.tokens}</td>
            <td data-label="Cost">${r.cost_usd.toFixed(4)}</td>
            <td data-label="Started">{new Date(r.started * 1000).toLocaleTimeString()}</td></tr>))}</tbody>
        </table></div>)}
    </div>
  );
}
