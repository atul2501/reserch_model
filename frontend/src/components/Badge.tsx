import type { ReactNode } from "react";

export type BadgeTone = "blue" | "green" | "red" | "amber" | "purple" | "neutral";

const TONE_CLASSES: Record<BadgeTone, string> = {
  blue: "text-accent-blue bg-accent-blue-dim",
  green: "text-accent-green bg-accent-green-dim",
  red: "text-accent-red bg-accent-red-dim",
  amber: "text-accent-amber bg-accent-amber-dim",
  purple: "text-accent-purple bg-accent-purple-dim",
  neutral: "text-muted bg-surface-3",
};

export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}
