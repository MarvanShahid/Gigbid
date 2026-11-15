"use client";
import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { api, ApprovalOut, errorText, money } from "@/lib/client";
import EvidenceHover from "@/components/EvidenceHover";
import { Empty, ErrorBox, Loading } from "@/components/States";

type Any = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export default function Studio({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [ap, setAp] = useState<ApprovalOut | null | undefined>(undefined);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [answers, setAnswers] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");
  const [done, setDone] = useState("");
  const load = useCallback(async () => {
    const { data, error } = await api.GET("/api/approvals", { params: { query: { kind: "proposal" } } });
    if (error) return setErr(errorText(error));
    const a = data.find((x) => x.subject === id) || null;
    setAp(a);
    if (a) { const dr = a.payload.draft as Any; setText(dr.cover_letter); setAnswers(dr.answers || []); }
  }, [id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {   // after a decision, poll until the graph asks again (edit) or finishes
    if (!done) return;
    const t = setInterval(async () => {
      const { data } = await api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } });
      if (data && data.approval_id && done === "edit") { setDone(""); setEditing(false); load(); }
      if (data && ["submitted", "rejected", "blocked"].includes(data.status)) setDone(`final:${data.status}`);
    }, 1000);
    return () => clearInterval(t);
  }, [done, id, load]);
  async function decide(action: "approve" | "edit" | "reject" | "regenerate", extra: Any = {}) {
    if (!ap) return;
    setErr("");
    const { error } = await api.POST("/api/approvals/{approval_id}/decision",
      { params: { path: { approval_id: ap.id } }, body: { action, ...extra } });
    if (error) return setErr(errorText(error));
    setDone(action === "regenerate" ? "edit" : action);
  }
  if (ap === undefined) return <Loading what="Loading draft" />;
  if (done.startsWith("final:")) return <div className="panel" data-testid="studio-result"><h1>Proposal {done.slice(6)}</h1>
    <p>{done === "final:submitted" ? "Submitted exactly once to the marketplace." : "Nothing was sent."}</p>
    <Link href="/pipeline">Open pipeline</Link> · <Link href="/inbox">Back to inbox</Link></div>;
  if (done) return <Loading what={done === "edit" ? "Re-checking your edit with the Compliance Guard" : "Applying your decision"} />;
  if (!ap) return <Empty>No proposal waiting for approval on this job. <Link href={`/jobs/${id}`}>Open the job</Link></Empty>;
  const p = ap.payload as Any;
  const ver = p.verification || {};
  const crit = (p.critiques || []) as Any[];
  return (
    <div>
      <h1>Proposal studio — {p.title}</h1>
      <ErrorBox msg={err} />
      <div className="grid2">
        <div className="panel">
          <h2>Cover letter {editing ? "(editing)" : <span className="muted small">— hover a highlighted claim to see its evidence</span>}</h2>
          {editing ? (<>
            <label htmlFor="letter">Cover letter</label>
            <textarea id="letter" value={text} onChange={(e) => setText(e.target.value)} />
            {answers.map((a, i) => (<div key={i}><label htmlFor={`ans${i}`}>{`Answer ${i + 1}`}</label>
              <textarea id={`ans${i}`} style={{ minHeight: 60 }} value={a}
                onChange={(e) => setAnswers(answers.map((x, j) => (j === i ? e.target.value : x)))} /></div>))}
          </>) : (<>
            <EvidenceHover text={p.draft.cover_letter} evidence={p.evidence}
              onRegenerate={(i) => decide("regenerate", { paragraph: i })} />
            {(p.draft.answers as string[]).length > 0 && <><h3>Screening answers</h3>
              {(p.draft.answers as string[]).map((a, i) => <div key={i} className="small" style={{ marginBottom: 6 }}>
                <EvidenceHover text={a} evidence={p.evidence} testId="answer-view" /></div>)}</>}
          </>)}
          <div className="row" style={{ marginTop: 12 }}>
            {!editing ? (<>
              <button className="primary" onClick={() => decide("approve")} data-testid="approve">Approve and submit</button>
              <button onClick={() => setEditing(true)} data-testid="edit">Edit</button>
            </>) : (<>
              <button className="primary" onClick={() => decide("edit", { text, answers })} data-testid="save-edit">Save edit (re-check)</button>
              <button onClick={() => setEditing(false)}>Cancel</button>
            </>)}
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            <input aria-label="Reason for rejecting" placeholder="Reason for rejecting" value={reason}
              onChange={(e) => setReason(e.target.value)} style={{ flex: 1 }} />
            <button className="danger" onClick={() => decide("reject", { reason })} disabled={!reason.trim()} data-testid="reject">Reject</button>
          </div>
        </div>
        <div>
          <div className="panel" data-testid="dry-run">
            <h2>What will be sent (dry run)</h2>
            <p><strong>{money(p.preview.bid_amount)}</strong> bid · <strong>{p.preview.connects_cost}</strong> Connects
              {p.preview.balance_after != null && <> · balance after: {p.preview.balance_after}</>}</p>
            <p className="small muted">Marketplace: {p.preview.marketplace}. Citation markers are removed before sending.</p>
            <details><summary>Exact text</summary><p className="small" style={{ whiteSpace: "pre-wrap" }}>{p.preview.cover_letter}</p></details>
          </div>
          <div className="panel">
            <h2>Critic</h2>
            {crit.map((c, i) => <div key={i} className="small"><span className={`badge ${c.passed ? "pass" : "blocked"}`}>round {c.round}: {c.passed ? "passed" : "sent back"}</span>
              <ul>{(c.issues as Any[]).map((x, j) => <li key={j}><strong>{x.kind}</strong>: {x.detail}</li>)}</ul></div>)}
            <h2>Claim verification</h2>
            <p className="small">Unsupported claims: {ver.unsupported_before ?? 0} before → <strong>{ver.unsupported_after ?? 0}</strong> after
              (of {ver.claims_before ?? 0} claims)</p>
            {(ver.changes || []).map((c: Any, i: number) => <p key={i} className="small muted">{c.action}: “{c.claim}”</p>)}
            <h2>Compliance Guard</h2>
            <p><span className={`badge ${p.compliance?.status}`}>{p.compliance?.status}</span></p>
            <ul className="small">{(p.compliance?.violations || []).map((v: Any, i: number) => <li key={i}>{v.rule}: “{v.match}”</li>)}</ul>
          </div>
          <div className="panel"><h2>Price rationale</h2><ul className="small">{(p.price.rationale as string[]).map((r, i) => <li key={i}>{r}</li>)}</ul></div>
        </div>
      </div>
    </div>
  );
}
