"use client";
import { useCallback, useEffect, useState } from "react";
import { api, ApprovalOut, errorText } from "@/lib/client";

import { Empty, ErrorBox, Loading } from "@/components/States";

type Msg = { from: string; text: string; at: number };
type Thread = { id: string; proposal_id: string; messages: Msg[]; approval_id?: string | null; needs_reply?: boolean };
type Payload = { reply: { text: string }; slots?: { label: string }[]; intent?: { intent: string }; injection_detected?: boolean };

export default function Messages() {
  const [threads, setThreads] = useState<Thread[] | null>(null);
  const [aps, setAps] = useState<ApprovalOut[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [edit, setEdit] = useState("");
  const [slot, setSlot] = useState(0);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");
  const load = useCallback(async () => {
    const t = await api.GET("/api/messages");
    if (!t.data) return setErr(t.response.status === 503 ? "Marketplace unavailable" : "Could not load messages");
    setThreads((t.data as { threads: Thread[] }).threads);
    const a = await api.GET("/api/approvals", { params: { query: { kind: "message" } } });
    setAps(a.data || []);
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 4000); return () => clearInterval(t); }, [load]);
  const cur = threads?.find((t) => t.id === sel) || null;
  const ap = aps.find((a) => a.subject === sel) || null;
  const p = ap?.payload as Payload | undefined;
  useEffect(() => { if (p) setEdit(p.reply.text); }, [ap?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  async function draft(id: string) {
    await api.POST("/api/messages/{thread_id}/draft", { params: { path: { thread_id: id } } });
    load();
  }
  async function decide(action: "approve" | "edit" | "reject") {
    if (!ap || !p) return;
    const slots = p.slots || [];
    const body = action === "approve" ? { action, slot: (slots[slot] as Record<string, unknown>) || null }
      : action === "edit" ? { action, text: edit } : { action, reason };
    const { error } = await api.POST("/api/approvals/{approval_id}/decision", { params: { path: { approval_id: ap.id } }, body });
    if (error) setErr(errorText(error));
    setTimeout(load, 800);
  }
  if (!threads) return <Loading what="Loading messages" />;
  return (
    <div>
      <h1>Messages</h1>
      <ErrorBox msg={err} />
      {threads.length === 0 ? <Empty>No client conversations yet. Replies appear here after you submit proposals.</Empty> : (
        <div className="grid2">
          <div className="panel" style={{ padding: 0 }}>
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {threads.map((t) => (
                <li key={t.id}><button style={{ width: "100%", textAlign: "left", border: 0, borderBottom: "1px solid var(--line)", borderRadius: 0 }}
                  onClick={() => setSel(t.id)} aria-pressed={sel === t.id}>
                  <strong>{t.id}</strong>{" "}
                  {t.approval_id ? <span className="badge watch">reply waiting for approval</span> : t.needs_reply ? <span className="badge high">needs reply</span> : null}
                  <div className="muted small">{t.messages[t.messages.length - 1]?.text.slice(0, 90)}</div>
                </button></li>
              ))}
            </ul>
          </div>
          <div className="panel">
            {!cur ? <p className="muted">Pick a conversation.</p> : (<>
              {cur.messages.map((m, i) => <p key={i}><strong>{m.from}:</strong> {m.text}</p>)}
              {ap && p ? (<div data-testid="reply-approval">
                <h3>Suggested reply <span className="badge">{p.intent?.intent}</span>
                  {p.injection_detected && <span className="badge high">injection ignored</span>}</h3>
                <label htmlFor="reply">Reply</label>
                <textarea id="reply" value={edit} onChange={(e) => setEdit(e.target.value)} style={{ minHeight: 100 }} />
                {(p.slots || []).length > 0 && (<><label htmlFor="slot">Interview slot to hold</label>
                  <select id="slot" value={slot} onChange={(e) => setSlot(+e.target.value)}>
                    {(p.slots || []).map((s, i) => <option key={i} value={i}>{s.label}</option>)}</select></>)}
                <div className="row" style={{ marginTop: 10 }}>
                  {edit === p.reply.text ? <button className="primary" onClick={() => decide("approve")}>Approve and send</button>
                    : <button className="primary" onClick={() => decide("edit")}>Save edit (re-check)</button>}
                  <input aria-label="Reason for rejecting" placeholder="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
                  <button className="danger" onClick={() => decide("reject")}>Reject</button>
                </div>
              </div>) : cur.needs_reply ? <button className="primary" onClick={() => draft(cur.id)}>Draft a reply</button> : null}
            </>)}
          </div>
        </div>
      )}
    </div>
  );
}
