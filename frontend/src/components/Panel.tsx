import type { ReactNode } from "react";

type Accent = "blue" | "green" | "red" | "amber" | "purple";

// Full literal class strings, not interpolated (`bg-accent-${accent}`) —
// Tailwind's build-time scanner needs the complete class name to appear
// verbatim in source to generate it; a runtime-interpolated string would
// silently produce no background color at all.
const ACCENT_BAR_CLASSES: Record<Accent, string> = {
  blue: "bg-accent-blue",
  green: "bg-accent-green",
  red: "bg-accent-red",
  amber: "bg-accent-amber",
  purple: "bg-accent-purple",
};

export function Panel({
  title,
  children,
  className = "",
  accent = "blue",
}: {
  title: string;
  children: ReactNode;
  className?: string;
  accent?: Accent;
}) {
  return (
    <section className={`rounded-lg border border-line bg-surface ${className}`}>
      <header className="flex items-center gap-2 border-b border-line px-3 py-2">
        <span className={`h-3 w-[3px] rounded-full ${ACCENT_BAR_CLASSES[accent]}`} aria-hidden />
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-muted">{title}</h2>
      </header>
      <div className="p-3">{children}</div>
    </section>
  );
}
