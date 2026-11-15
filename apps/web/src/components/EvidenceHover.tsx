"use client";
type Ev = { id: string; type: string; title?: string | null; text: string; source?: string; project?: string | null };

const CITE = /\s*\[((?:[a-f0-9]{12})(?:\s*,\s*[a-f0-9]{12})*)\]/g;

/** Renders a draft; every cited claim shows its portfolio evidence on hover or keyboard focus. */
export default function EvidenceHover({ text, evidence, onRegenerate, testId = "draft-view" }:
  { text: string; evidence: Ev[]; onRegenerate?: (i: number) => void; testId?: string }) {
  const byId = new Map(evidence.map((e) => [e.id, e]));
  const sentences = text.split(/(?<=[.!?])\s+(?=[A-Z0-9"'(])/);
  return (
    <div data-testid={testId}>
      {sentences.map((s, i) => {
        const ids = [...s.matchAll(CITE)].flatMap((m) => m[1].split(",").map((x) => x.trim()));
        const plain = s.replace(CITE, "");
        return (
          <span key={i} className="sentence">
            {ids.length ? (
              <span className="cite" tabIndex={0} aria-label={`claim backed by ${ids.length} evidence item(s)`}>
                {plain}
                <span className="pop" role="tooltip">
                  {ids.map((id) => {
                    const e = byId.get(id);
                    return (
                      <span key={id} style={{ display: "block", marginBottom: 6 }}>
                        <span className="badge">{e?.type ?? "evidence"}</span> <strong>{e?.title ?? id}</strong>
                        <br />{e ? e.text.slice(0, 280) : "evidence not loaded"}
                        <br /><span className="muted small">{(e?.source ?? id).replace(/^.*?data[\\/]personas[\\/]/, "")}</span>
                      </span>
                    );
                  })}
                </span>
              </span>
            ) : <span>{plain}</span>}
            {onRegenerate && (
              <button className="regen" type="button" onClick={() => onRegenerate(i)}
                aria-label={`Regenerate sentence ${i + 1}`}>↻</button>
            )}{" "}
          </span>
        );
      })}
    </div>
  );
}
