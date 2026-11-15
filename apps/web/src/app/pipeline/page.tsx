"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, errorText, money, Schemas } from "@/lib/client";
import { ErrorBox, Loading } from "@/components/States";

type Stage = Schemas["StageIn"]["stage"];
type Card = { id: number; job_id: string; title: string; category: string; stage: Stage; bid: number | null; connects: number };

export default function Pipeline() {
  const [b, setB] = useState<Schemas["PipelineOut"] | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const load = useCallback(async () => {
    const { data, error } = await api.GET("/api/pipeline");
    if (error) setErr(errorText(error)); else setB(data);
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);
  async function sync() {
    const { data, error } = await api.POST("/api/pipeline/sync");
    if (error) return setErr(errorText(error));
    const d = data as { moved: number; threads_needing_reply: string[] };
    setMsg(`${d.moved} cards moved; ${d.threads_needing_reply.length} client replies being drafted`);
    load();
  }
  async function move(id: number, stage: Stage) {
    await api.PATCH("/api/pipeline/{card_id}", { params: { path: { card_id: id } }, body: { stage } });
    load();
  }
  if (!b) return <Loading what="Loading pipeline" />;
  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between" }}><h1>Pipeline</h1>
        <button onClick={sync}>Sync with marketplace</button></div>
      <ErrorBox msg={err} />{msg && <div className="banner info" role="status">{msg}</div>}
      <div className="kanban" data-testid="kanban">
        {b.stages.map((st) => (
          <section className="col" key={st} aria-label={st}>
            <h3 style={{ textTransform: "capitalize" }}>{st} <span className="muted small">({b.cards.filter((c) => c.stage === st).length})</span></h3>
            {(b.cards as Card[]).filter((c) => c.stage === st).map((c) => (
              <div className="card" key={c.id}>
                <Link href={`/jobs/${c.job_id}`}>{c.title || c.job_id}</Link>
                <div className="muted">{c.category} · {money(c.bid)} · {c.connects} Connects</div>
                <label htmlFor={`mv${c.id}`} className="small">Move to</label>
                <select id={`mv${c.id}`} value={c.stage} onChange={(e) => move(c.id, e.target.value as Stage)}>
                  {b.stages.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
            ))}
          </section>
        ))}
      </div>
    </div>
  );
}
