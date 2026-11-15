"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, errorText, JobCard, money, pct } from "@/lib/client";
import RiskBadge from "@/components/RiskBadge";
import { Empty, ErrorBox, Loading } from "@/components/States";

export default function Inbox() {
  const [jobs, setJobs] = useState<JobCard[] | null>(null);
  const [filter, setFilter] = useState("all");
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const { data, error } = await api.GET("/api/jobs", { params: { query: { q: q || undefined } } });
    if (error) setErr(errorText(error)); else { setErr(""); setJobs(data); }
  }, [q]);
  useEffect(() => { load(); const id = setInterval(load, 4000); return () => clearInterval(id); }, [load]);
  async function scout() {
    setBusy(true);
    const { data, error } = await api.POST("/api/jobs/scout");
    setBusy(false);
    if (error) setErr(errorText(error)); else setMsg(data.detail);
    load();
  }
  async function act(id: string, what: "analyse" | "skip") {
    const r = what === "analyse"
      ? await api.POST("/api/jobs/{job_id}/analyse", { params: { path: { job_id: id } } })
      : await api.POST("/api/jobs/{job_id}/skip", { params: { path: { job_id: id } } });
    if (r.error) setErr(errorText(r.error));
    load();
  }
  const shown = (jobs || []).filter((j) => filter === "all" ? j.status !== "duplicate"
    : filter === "approve" ? j.status === "awaiting_approval" : j.recommendation === filter);
  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>Job inbox</h1>
        <button className="primary" onClick={scout} disabled={busy}>{busy ? "Scouting…" : "Scout now"}</button>
      </div>
      <ErrorBox msg={err} />{msg && <div className="banner info" role="status">{msg}</div>}
      <div className="row panel">
        <label htmlFor="f" style={{ margin: 0 }}>Show</label>
        <select id="f" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">All</option><option value="approve">Waiting for my approval</option>
          <option value="bid">Recommended: bid</option><option value="watch">Watch</option><option value="skip">Skip</option>
        </select>
        <input aria-label="Search titles" placeholder="Search titles" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {jobs === null ? <Loading what="Loading jobs" /> : shown.length === 0 ? (
        <Empty>No jobs yet. Press <strong>Scout now</strong> to run your saved searches.</Empty>
      ) : (
        <div className="panel" style={{ padding: 0 }}>
          <table className="responsive">
            <thead><tr><th>Job</th><th>Fit</th><th>Risk</th><th>Action</th><th>Price</th><th>Connects</th><th>Status</th><th /></tr></thead>
            <tbody>
              {shown.map((j) => (
                <tr key={j.job_id} data-testid={`job-${j.job_id}`}>
                  <td data-label="Job"><Link href={`/jobs/${j.job_id}`}>{j.title || j.job_id}</Link>
                    <div className="muted small">{j.category} · budget {money(j.budget)}</div></td>
                  <td data-label="Fit">{pct(j.fit)}</td>
                  <td data-label="Risk"><RiskBadge level={j.risk_level} score={j.risk} /></td>
                  <td data-label="Action">{j.recommendation ? <span className={`badge ${j.recommendation}`}>{j.recommendation}</span> : "–"}</td>
                  <td data-label="Price">{money(j.price)}</td>
                  <td data-label="Connects">{j.connects ?? "–"}</td>
                  <td data-label="Status">{j.status === "analysing" ? <><span className="spinner" /> analysing</> : j.status}
                    {j.error && <div className="small" style={{ color: "var(--bad)" }}>{j.error}</div>}</td>
                  <td data-label="">
                    <div className="row">
                      {j.status === "awaiting_approval" && <Link className="btn primary" href={`/studio/${j.job_id}`}>Review</Link>}
                      {["new", "queued", "failed", "watch"].includes(j.status) && <button onClick={() => act(j.job_id, "analyse")}>Analyse</button>}
                      {!["skipped", "submitted", "duplicate"].includes(j.status) && <button onClick={() => act(j.job_id, "skip")}>Skip</button>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
