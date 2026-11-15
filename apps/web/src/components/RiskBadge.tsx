export default function RiskBadge({ level, score }: { level?: string | null; score?: number | null }) {
  if (!level) return <span className="badge">not analysed</span>;
  return <span className={`badge ${level}`} title={`risk score ${score?.toFixed(2)}`}>risk {level}</span>;
}
