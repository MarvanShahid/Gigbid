"use client";
import { useEffect, useState } from "react";
import { api, pct } from "@/lib/client";
import { ErrorBox, Loading } from "@/components/States";

type A = {
  totals: Record<string, number>;
  by_category: { category: string; sent: number; replied: number; hired: number; connects: number; reply_rate: number; hire_rate: number }[];
  latency: { p50_s: number | null; p95_s: number | null; n: number };
  cost: { usd_per_job: number; usd_per_proposal: number };
  top_rejection_reasons: [string, number][];
};

export default function Analytics() {
  const [a, setA] = useState<A | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.GET("/api/analytics").then(({ data, response }) => (data ? setA(data as A) : setErr(`Could not load analytics (${response.status})`)));
  }, []);
  if (err) return <ErrorBox msg={err} />;
  if (!a) return <Loading what="Loading analytics" />;
  const max = Math.max(1, ...a.by_category.map((c) => c.connects));
  return (
    <div><h1>Analytics</h1>
      <div className="row panel">{Object.entries(a.totals).map(([k, v]) => (
        <div key={k} style={{ minWidth: 120 }}><div className="muted small">{k.replaceAll("_", " ")}</div>
          <strong style={{ fontSize: 20 }}>{v}</strong></div>))}</div>
      <div className="panel"><h2>Reply and hire rate by category</h2>
        <table className="responsive"><thead><tr><th>Category</th><th>Sent</th><th>Reply rate</th><th>Hire rate</th><th>Connects spent vs replies</th></tr></thead>
          <tbody>{a.by_category.map((c) => (
            <tr key={c.category}><td data-label="Category">{c.category}</td><td data-label="Sent">{c.sent}</td>
              <td data-label="Reply">{pct(c.reply_rate)}</td><td data-label="Hire">{pct(c.hire_rate)}</td>
              <td data-label="Connects"><div className="bar" style={{ width: `${(c.connects / max) * 100}%` }} aria-hidden />
                <span className="small">{c.connects} Connects → {c.replied} replies</span></td></tr>))}</tbody></table></div>
      <div className="grid2">
        <div className="panel"><h2>Cost and latency</h2>
          <p>p50 {a.latency.p50_s?.toFixed(1) ?? "–"}s · p95 {a.latency.p95_s?.toFixed(1) ?? "–"}s per job ({a.latency.n} runs)</p>
          <p>${a.cost.usd_per_job.toFixed(4)} per job analysed · ${a.cost.usd_per_proposal.toFixed(4)} per proposal</p></div>
        <div className="panel"><h2>Top rejection reasons</h2>
          <ol>{a.top_rejection_reasons.map(([r, n]) => <li key={r}>{r} ({n})</li>)}</ol></div>
      </div>
    </div>
  );
}
