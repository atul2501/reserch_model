export function StatusDot({ ok }: { ok: boolean | null }) {
  const color = ok === null ? "bg-slate-600" : ok ? "bg-emerald-400" : "bg-rose-500";
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />;
}
