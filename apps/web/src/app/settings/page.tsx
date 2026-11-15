"use client";
import { useCallback, useEffect, useState } from "react";
import { api, errorText } from "@/lib/client";
import { ErrorBox, Loading } from "@/components/States";

type Any = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
type Mem = Record<string, Any[]>;
type Search = { name: string; query: string; category: string | null; every_hours: number };

export default function Settings() {
  const [s, setS] = useState<Any | null>(null);
  const [mem, setMem] = useState<Mem>({});
  const [conn, setConn] = useState<Any>({});
  const [err, setErr] = useState("");
  const [saved, setSaved] = useState(false);
  const load = useCallback(async () => {
    const a = await api.GET("/api/settings"); setS(a.data as Any);
    const m = await api.GET("/api/memory"); setMem((m.data as Mem) || {});
    const c = await api.GET("/api/auth/connections"); setConn((c.data as Any) || {});
  }, []);
  useEffect(() => { load(); }, [load]);
  async function save() {
    if (!s) return;
    const { error } = await api.PUT("/api/settings", { body: {
      autonomy: s.autonomy, weekly_connects_budget: +s.weekly_connects_budget, hourly_floor: +s.hourly_floor,
      hourly_rate: +s.hourly_rate, saved_searches: s.saved_searches } });
    if (error) setErr(errorText(error)); else { setSaved(true); setTimeout(() => setSaved(false), 2000); }
  }
  async function forget(ns: string, key: string) {
    await api.DELETE("/api/memory/{namespace}/{key}", { params: { path: { namespace: ns, key } } });
    load();
  }
  if (!s) return <Loading what="Loading settings" />;
  const set = (k: string, v: unknown) => setS({ ...s, [k]: v });
  const searches = s.saved_searches as Search[];
  const upd = (i: number, patch: Partial<Search>) => set("saved_searches", searches.map((y, j) => (j === i ? { ...y, ...patch } : y)));
  return (
    <div><h1>Settings</h1><ErrorBox msg={err} />
      <div className="panel"><h2>Autonomy and budgets</h2>
        <label htmlFor="aut">Autonomy</label>
        <select id="aut" value={s.autonomy} onChange={(e) => set("autonomy", e.target.value)}>
          <option value="suggest">Suggest only (I confirm skips)</option>
          <option value="auto_skip">Auto-skip low-fit jobs</option>
        </select>
        <p className="muted small">GigBid can never send a proposal or message without your approval, at any setting.</p>
        <div className="grid2">
          <div><label htmlFor="wcb">Weekly Connects budget</label>
            <input id="wcb" type="number" value={s.weekly_connects_budget} onChange={(e) => set("weekly_connects_budget", e.target.value)} /></div>
          <div><label htmlFor="hf">Hourly floor</label>
            <input id="hf" type="number" value={s.hourly_floor} onChange={(e) => set("hourly_floor", e.target.value)} /></div>
        </div>
      </div>
      <div className="panel"><h2>Saved searches</h2>
        {searches.map((x, i) => (
          <div className="row" key={i} style={{ marginBottom: 6 }}>
            <input aria-label="Search name" value={x.name} onChange={(e) => upd(i, { name: e.target.value })} />
            <input aria-label="Keywords" placeholder="keywords" value={x.query} onChange={(e) => upd(i, { query: e.target.value })} />
            <label htmlFor={`ev${i}`} style={{ margin: 0 }}>every</label>
            <input id={`ev${i}`} type="number" min={1} max={48} style={{ width: 70 }} value={x.every_hours}
              onChange={(e) => upd(i, { every_hours: +e.target.value })} /> h
            <button onClick={() => set("saved_searches", searches.filter((_, j) => j !== i))}>Remove</button>
          </div>))}
        <button onClick={() => set("saved_searches", [...searches, { name: "New search", query: "", category: null, every_hours: 4 }])}>Add search</button>
      </div>
      <div className="row"><button className="primary" onClick={save}>Save settings</button>{saved && <span role="status">Saved.</span>}</div>
      <div className="panel" style={{ marginTop: 14 }}><h2>Connected accounts</h2>
        <p>GigSim: {conn.gigsim ? "connected" : "–"} · Upwork: {conn.upwork ? "connected (tokens encrypted)" : "not connected"}</p></div>
      <div className="panel" data-testid="memory"><h2>What GigBid has learned</h2>
        <p className="muted small">Only promoted knowledge is used when writing. A style rule needs the same edit in two different
          drafts; outcome notes need three outcomes in a category. Delete anything you do not want used.</p>
        {(["style", "outcome", "style_candidates"] as const).map((ns) => (
          <div key={ns}>
            <h3>{ns === "style" ? "Style rules (from your edits)" : ns === "outcome" ? "Outcome memory" : "Candidates (not used yet)"}</h3>
            {(mem[ns] || []).length === 0 ? <p className="muted small">Nothing yet.</p> : (
              <ul>{(mem[ns] || []).map((m) => (
                <li key={m.key}>
                  {m.rule || (m.category && `${m.category}: reply rate ${Math.round(m.reply_rate * 100)}% over ${m.n}. ${(m.insights || []).join("; ")}`) || m.key}
                  {m.count ? <span className="muted small"> (seen in {m.count} edit{m.count > 1 ? "s" : ""})</span> : null}{" "}
                  <button onClick={() => forget(ns, m.key)} aria-label={`Delete ${m.key}`}>Delete</button>
                </li>))}</ul>)}
          </div>))}
      </div>
    </div>
  );
}
