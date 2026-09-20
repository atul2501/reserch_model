import type { ReactNode } from "react";

type Tone = "neutral" | "positive" | "negative" | "warning";

const TONE_TO_ACCENT: Record<Tone, string> = {
  neutral: "blue",
  positive: "green",
  negative: "red",
  warning: "amber",
};

export function StatTile({
  label,
  value,
  tone = "neutral",
  sub,
  loading = false,
}: {
  label: string;
  value: ReactNode;
  tone?: Tone;
  sub?: string;
  loading?: boolean;
}) {
  const accent = TONE_TO_ACCENT[tone];

  if (loading) {
    return (
      <div className={`stat-card stat-card--${accent}`}>
        <div className="skeleton mb-3 h-[9px] w-3/5" />
        <div className="skeleton mb-2.5 h-5 w-2/5" />
        <div className="skeleton h-[9px] w-3/4" />
      </div>
    );
  }

  return (
    <div className={`stat-card stat-card--${accent}`}>
      <div className="flex flex-col gap-0.5">
        <span className="text-[10px] uppercase tracking-wider text-muted">{label}</span>
        <span className="font-mono-num text-lg font-medium text-text-strong">{value}</span>
        {sub && <span className="text-[11px] text-muted-2">{sub}</span>}
      </div>
    </div>
  );
}
