import type { ReactNode } from "react";

export function Panel({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded border border-slate-800 bg-slate-950/60 ${className}`}>
      <header className="border-b border-slate-800 px-3 py-2">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{title}</h2>
      </header>
      <div className="p-3">{children}</div>
    </section>
  );
}
