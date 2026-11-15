"use client";
import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { api, errorText, JobDetail, money, pct } from "@/lib/client";
import RiskBadge from "@/components/RiskBadge";
import { ErrorBox, Loading } from "@/components/States";

type Any = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export default function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [d, setD] = useState<JobDetail | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(async () => {
    const { data, error } = await api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } });
    if (error) setErr(errorText(error)); else setD(data);
  }, [id]);
  useEffect(() => { load(); const t = setInterval(load, 4000); return () => clearInterval(t); }, [load]);
  async function draftAnyway() {
    await api.POST("/api/jobs/{job_id}/analyse", { params: { path: { job_id: id }, query: { force_bid: true } } });
    load();
  }
  if (err) return <ErrorBox msg={err} />;
  if (!d) return <Loading what="Loading job" />;
  const s = d.summary as Any;
  const spec = s.spec as Any | undefined, risk = s.risk as Any | undefined, fit = s.fit as Any | undefined;
  const price = s.price as Any | undefined, dec = s.decision as Any | undefined, brief = s.brief as Any | undefined;
  const ev = new Map(((s.evidence || []) as Any[]).map((e) => [e.id, e]));
  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1>{d.title || d.job_id}</h1>
        <div className="row">
          {d.approval_id && <Link className="btn primary" href={`/studio/${d.job_id}`}>Open proposal studio</Link>}
          {dec && dec.action !== "bid" && !risk?.is_scam && <button onClick={draftAnyway}>Draft anyway</button>}
          {d.runs[0] && <Link className="btn" href={`/runs/${d.runs[0].id}`}>Agent run</Link>}
        </div>
      </div>
      <div className="row panel">
        <span>Status: <strong>{d.status}</strong></span>
        {dec && <span className={`badge ${dec.action}`}>{dec.action}</span>}
        <RiskBadge level={d.risk_level} score={d.risk} /><span>fit {pct(d.fit)}</span>
        <span>price {money(d.price)}</span><span>{d.connects ?? "–"} Connects</span>
      </div>
      {d.job && (
        <details className="panel" open={!!risk?.injection_detected || !!risk?.is_scam}>
          <summary><strong>Original post</strong> <span className="muted small">(untrusted text: shown as data, never followed)</span></summary>
          <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", margin: "8px 0 0" }}>{(d.job as Any).description}</pre>
        </details>
      )}
      {dec && <div className="panel"><h2>Bid or skip — why</h2><ul>{(dec.reasons as string[]).map((r, i) => <li key={i}>{r}</li>)}</ul></div>}
      <div className="grid2">
        <div className="panel">
          <h2>JobSpec</h2>
          {spec ? (<>
            <p>{spec.summary}</p>
            <p className="small muted">Budget {money(spec.budget_amount)} ({spec.budget_type}) · timeline {spec.timeline_weeks ?? "?"} weeks · source {spec.source}</p>
            {spec.hidden_needs?.length > 0 && <><h3>Hidden needs</h3><ul>{spec.hidden_needs.map((h: string, i: number) => <li key={i}>{h}</li>)}</ul></>}
            {spec.screening_questions?.length > 0 && <><h3>Screening questions</h3><ul>{spec.screening_questions.map((h: string, i: number) => <li key={i}>{h}</li>)}</ul></>}
          </>) : <p className="muted">Not analysed yet.</p>}
        </div>
        <div className="panel">
          <h2>Risk report</h2>
          {risk ? (<>
            <p><RiskBadge level={risk.level} score={risk.score} /> client quality {pct(risk.client_quality)}
              {risk.injection_detected && <span className="badge high" style={{ marginLeft: 6 }}>prompt injection removed</span>}</p>
            <ul>{(risk.flags as Any[]).map((f, i) => <li key={i}><span className="badge">{f.kind}</span> “{f.evidence}”</li>)}</ul>
          </>) : <p className="muted">–</p>}
          {brief && (<><h3>Client brief (X4)</h3><ul className="small">{(brief.signals as string[]).map((x, i) => <li key={i}>{x}</li>)}</ul>
            {brief.talking_points?.length > 0 && <p className="small"><strong>Angles:</strong> {(brief.talking_points as string[]).join(" ")}</p>}</>)}
        </div>
      </div>
      <div className="panel">
        <h2>Requirement → evidence</h2>
        {fit ? (
          <table className="responsive">
            <thead><tr><th>Requirement</th><th>Strength</th><th>Portfolio evidence that proves it</th></tr></thead>
            <tbody>{(fit.matrix as Any[]).map((m, i) => (
              <tr key={i}><td data-label="Requirement">{m.requirement}</td>
                <td data-label="Strength"><span className={`badge ${m.strength}`}>{m.strength}</span></td>
                <td data-label="Evidence">{m.evidence_ids.length ? m.evidence_ids.map((eid: string) => {
                  const e = ev.get(eid);
                  return <div key={eid} className="small"><span className="badge">{e?.type ?? "item"}</span> {e?.title ?? eid}
                    <div className="muted">{e?.text?.slice(0, 160)}</div></div>;
                }) : <span className="muted">nothing in the portfolio</span>}</td></tr>))}</tbody>
          </table>
        ) : <p className="muted">–</p>}
      </div>
      {price && <div className="panel"><h2>Price rationale</h2><p><strong>{money(price.amount)}</strong> · {price.connects_cost} Connects (${price.connects_usd}) ·
        expected value ${price.expected_value_usd}</p><ul>{(price.rationale as string[]).map((r, i) => <li key={i}>{r}</li>)}</ul></div>}
    </div>
  );
}
