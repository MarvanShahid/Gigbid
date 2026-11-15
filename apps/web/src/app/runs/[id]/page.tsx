"use client";
import { use, useEffect, useState } from "react";
import { api, RunOut } from "@/lib/client";
import RunTimeline from "@/components/RunTimeline";
import { Loading } from "@/components/States";

type PerNode = Record<string, { tokens: number; cost_usd: number; ms: number }>;

export default function RunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [run, setRun] = useState<RunOut | null>(null);
  const [per, setPer] = useState<PerNode>({});
  useEffect(() => {
    api.GET("/api/runs/{run_id}", { params: { path: { run_id: id } } }).then(({ data }) => setRun(data || null));
  }, [id]);
  useEffect(() => {
    if (!run) return;
    api.GET("/api/runs/traces/{trace_id}", { params: { path: { trace_id: run.trace_id } } })
      .then(({ data }) => setPer(((data as { per_node?: PerNode })?.per_node) || {}));
  }, [run]);
  if (!run) return <Loading what="Loading run" />;
  return (
    <div>
      <h1>Run {run.id} <span className="muted small">({run.kind} · {run.subject})</span></h1>
      <div className="row panel">
        <span>trace <code>{run.trace_id}</code></span>
        {run.trace_url && <a href={run.trace_url} target="_blank" rel="noreferrer">Open full trace</a>}
        <span>{run.tokens} tokens · ${run.cost_usd.toFixed(4)}</span>
      </div>
      <div className="grid2">
        <div className="panel"><h2>Live progress</h2><RunTimeline runId={run.id} /></div>
        <div className="panel"><h2>Per node</h2>
          <table><thead><tr><th>Node / span</th><th>ms</th><th>tokens</th><th>USD</th></tr></thead>
            <tbody>{Object.entries(per).filter(([, v]) => v.ms || v.tokens).map(([k, v]) => (
              <tr key={k}><td>{k}</td><td>{v.ms.toFixed(0)}</td><td>{v.tokens}</td><td>{v.cost_usd.toFixed(5)}</td></tr>))}</tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
