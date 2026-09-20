export function StatusDot({ ok }: { ok: boolean | null }) {
  const color = ok === null ? "bg-muted-2" : ok ? "bg-accent-green" : "bg-accent-red";
  return <span className={`inline-block h-1.5 w-1.5 rounded-full ${color}`} />;
}
