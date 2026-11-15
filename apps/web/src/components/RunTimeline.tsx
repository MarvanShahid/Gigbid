"use client";
import { useEffect, useState } from "react";
import { token } from "@/lib/client";

type Ev = { t: number; kind: string; node: string; label: string; detail: string };

/** Live node-by-node progress, streamed from the LangGraph run over Server-Sent Events. */
export default function RunTimeline({ runId, initial = [] }: { runId: string; initial?: Ev[] }) {
  const [events, setEvents] = useState<Ev[]>(initial);
  const [done, setDone] = useState<string | null>(null);
  useEffect(() => {
    setEvents([]);
    const es = new EventSource(`/api/runs/${runId}/stream?token=${encodeURIComponent(token() || "")}`);
    es.addEventListener("node", (m) => setEvents((x) => [...x, JSON.parse((m as MessageEvent).data)]));
    es.addEventListener("done", (m) => { setDone(JSON.parse((m as MessageEvent).data).status); es.close(); });
    es.onerror = () => es.close();
    return () => es.close();
  }, [runId]);
  const t0 = events[0]?.t;
  return (
    <div>
      <ol className="timeline" data-testid="run-timeline" aria-live="polite">
        {events.map((e, i) => (
          <li key={i}>
            <span className="t">+{t0 ? (e.t - t0).toFixed(1) : "0.0"}s</span>
            <strong className={e.kind === "error" ? "badge high" : ""}>{e.label}</strong>
            {e.detail ? <span className="muted"> — {e.detail}</span> : null}
          </li>
        ))}
      </ol>
      {done ? <p className="muted">Run finished: {done}</p> : <p className="muted"><span className="spinner" /> running…</p>}
    </div>
  );
}
