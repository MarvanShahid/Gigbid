"use client";
import { useEffect, useState } from "react";
import { api, errorText, token } from "@/lib/client";
import { ErrorBox, Loading } from "@/components/States";

type Persona = { id: string; name?: string; title?: string; floor?: number; rate?: number };

export default function Onboarding() {
  const [personas, setPersonas] = useState<Persona[] | null>(null);
  const [persona, setPersona] = useState("ml_engineer");
  const [floor, setFloor] = useState(35);
  const [rate, setRate] = useState(45);
  const [budget, setBudget] = useState(120);
  const [minBudget, setMinBudget] = useState(300);
  const [market, setMarket] = useState<"gigsim" | "upwork_live">("gigsim");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  useEffect(() => { api.GET("/api/personas").then(({ data }) => setPersonas((data as Persona[]) || [])); }, []);

  async function upload(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    const r = await fetch("/api/portfolio/upload", { method: "POST", body: fd, headers: { Authorization: `Bearer ${token()}` } });
    const j = await r.json();
    if (!r.ok) setErr(errorText(j)); else setMsg(`Indexed ${j.new_chunks} new chunks from ${f.name}.`);
  }
  async function connectUpwork() {
    const { data, error } = await api.GET("/api/auth/upwork/start");
    if (error) return setErr(errorText(error));
    window.open((data as { authorization_url: string }).authorization_url, "_blank");
  }
  async function save() {
    const { error } = await api.PUT("/api/settings", { body: {
      persona, hourly_floor: floor, hourly_rate: rate, weekly_connects_budget: budget, marketplace: market,
      filters: { min_budget: minBudget, exclude_categories: [] }, onboarded: true } });
    if (error) return setErr(errorText(error));
    location.href = "/inbox";
  }
  if (!personas) return <Loading />;
  return (
    <div>
      <h1>Set up GigBid</h1>
      <ErrorBox msg={err} />{msg && <div className="banner info">{msg}</div>}
      <div className="panel">
        <h2>1. Whose portfolio?</h2>
        <div role="radiogroup" aria-label="Portfolio">
          {personas.map((p) => (
            <label key={p.id} style={{ color: "inherit" }}>
              <input type="radio" name="persona" value={p.id} checked={persona === p.id}
                onChange={() => { setPersona(p.id); if (p.floor) setFloor(p.floor); if (p.rate) setRate(p.rate); }} />{" "}
              {p.name} — {p.title} <span className="muted small">(demo persona)</span>
            </label>
          ))}
          <label style={{ color: "inherit" }}><input type="radio" name="persona" value="own" checked={persona === "own"}
            onChange={() => setPersona("own")} /> My own profile (upload below)</label>
        </div>
      </div>
      <div className="panel">
        <h2>2. Connect a marketplace</h2>
        <div className="row">
          <label style={{ color: "inherit" }}><input type="radio" checked={market === "gigsim"} onChange={() => setMarket("gigsim")} /> GigSim (simulator)</label>
          <label style={{ color: "inherit" }}><input type="radio" checked={market === "upwork_live"} onChange={() => setMarket("upwork_live")} /> Upwork (live, OAuth)</label>
          {market === "upwork_live" && <button type="button" onClick={connectUpwork}>Connect Upwork account</button>}
        </div>
        <p className="muted small">Live mode only creates drafts; you confirm every proposal on Upwork itself.</p>
      </div>
      <div className="panel">
        <h2>3. Upload portfolio</h2>
        <p className="muted small">CV (PDF), case studies (Markdown), READMEs or code. New files are indexed incrementally.</p>
        <input type="file" aria-label="Upload portfolio file" accept=".pdf,.md,.txt,.py,.ts,.js,.sql,.json" onChange={upload} />
      </div>
      <div className="panel">
        <h2>4. Rates, filters and budget</h2>
        <div className="grid2">
          <div><label htmlFor="floor">Hourly floor (USD)</label><input id="floor" type="number" value={floor} onChange={(e) => setFloor(+e.target.value)} /></div>
          <div><label htmlFor="rate">Target hourly rate (USD)</label><input id="rate" type="number" value={rate} onChange={(e) => setRate(+e.target.value)} /></div>
          <div><label htmlFor="budget">Weekly Connects budget</label><input id="budget" type="number" value={budget} onChange={(e) => setBudget(+e.target.value)} /></div>
          <div><label htmlFor="minb">Ignore jobs below (USD)</label><input id="minb" type="number" value={minBudget} onChange={(e) => setMinBudget(+e.target.value)} /></div>
        </div>
      </div>
      <button className="primary" onClick={save}>Save and open my inbox</button>
    </div>
  );
}
