export function StatTile({
  label,
  value,
  tone = "neutral",
  sub,
}: {
  label: string;
  value: string;
  tone?: "neutral" | "positive" | "negative" | "warning";
  sub?: string;
}) {
  const toneClass = {
    neutral: "text-slate-200",
    positive: "text-emerald-400",
    negative: "text-rose-400",
    warning: "text-amber-400",
  }[tone];

  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wider text-slate-500">{label}</span>
      <span className={`font-mono-num text-lg font-medium ${toneClass}`}>{value}</span>
      {sub && <span className="text-[11px] text-slate-600">{sub}</span>}
    </div>
  );
}
