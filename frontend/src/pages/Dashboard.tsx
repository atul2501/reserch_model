import { api } from "../lib/api";
import { usePolling } from "../hooks/usePolling";
import { Panel } from "../components/Panel";
import { StatTile } from "../components/StatTile";
import { StatusDot } from "../components/StatusDot";
import type { LeaderboardEntry } from "../types/api";

const REGIME_TONE: Record<string, "positive" | "negative" | "warning" | "neutral"> = {
  TREND_UP: "positive",
  BREAKOUT: "positive",
  TREND_DOWN: "negative",
  BREAKDOWN: "negative",
  HIGH_VOLATILITY: "warning",
  LOW_VOLATILITY: "neutral",
  RANGE: "neutral",
  UNCERTAIN: "neutral",
};

function fmtUsd(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
}

function fmtPct(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  return `${(n * 100).toFixed(2)}%`;
}

export function Dashboard() {
  const { data: health } = usePolling(api.health, 10_000);
  const { data: market, error: marketError } = usePolling(api.market, 5_000);
  const { data: population } = usePolling(api.population, 10_000);
  const { data: leaderboard } = usePolling(() => api.leaderboard(25), 10_000);

  return (
    <div className="min-h-screen bg-[#0a0e14] text-slate-200">
      <header className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold tracking-wide text-slate-100">
            EVOLUTIONARY TRADING LAB
          </span>
          <span className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] uppercase text-slate-500">
            {health?.trading_mode ?? "…"}
          </span>
        </div>
        <div className="flex items-center gap-4 text-[11px] text-slate-500">
          <span className="flex items-center gap-1.5">
            <StatusDot ok={health?.database_ok ?? null} /> DB
          </span>
          <span className="flex items-center gap-1.5">
            <StatusDot ok={health?.hyperliquid_configured ?? null} /> Hyperliquid
          </span>
          <span className="flex items-center gap-1.5">
            <StatusDot ok={health?.ollama_configured ?? null} /> Ollama
          </span>
          <span className="flex items-center gap-1.5">
            <StatusDot ok={health?.market_data_stale === false} />
            Market data {health?.market_data_stale ? "stale" : "fresh"}
          </span>
        </div>
      </header>

      <main className="grid grid-cols-1 gap-3 p-4 lg:grid-cols-3">
        <Panel title="Market" className="lg:col-span-1">
          {marketError && <p className="text-xs text-rose-400">No market data yet — is the worker running?</p>}
          {market && (
            <div className="grid grid-cols-2 gap-4">
              <StatTile label={market.symbol} value={fmtUsd(market.close_price)} />
              <StatTile
                label="Regime"
                value={market.regime}
                tone={REGIME_TONE[market.regime] ?? "neutral"}
                sub={`${(market.regime_confidence * 100).toFixed(0)}% confidence`}
              />
              <StatTile label="Volatility pct." value={fmtPct(market.volatility_percentile)} />
              <StatTile label="Volume ratio" value={market.volume_ratio.toFixed(2) + "x"} />
            </div>
          )}
        </Panel>

        <Panel title="Population" className="lg:col-span-2">
          {population && (
            <div className="grid grid-cols-3 gap-4 sm:grid-cols-6">
              <StatTile label="Generation" value={`Gen ${population.generation}`} />
              <StatTile label="Target" value={String(population.target_size)} />
              <StatTile label="Active" value={String(population.active_count)} tone="positive" />
              <StatTile label="Dead" value={String(population.dead_count)} tone={population.dead_count > 0 ? "negative" : "neutral"} />
              <StatTile label="Professional" value={String(population.professional_count)} />
              <StatTile
                label="Population equity"
                value={fmtUsd(population.total_equity)}
                sub={`of ${fmtUsd(population.total_capital_allocated)} allocated`}
              />
            </div>
          )}
        </Panel>

        <Panel title="Leaderboard" className="lg:col-span-3">
          <LeaderboardTable rows={leaderboard ?? []} />
        </Panel>
      </main>

      <footer className="px-4 pb-4 text-[11px] text-slate-600">
        Agent detail drill-down, evolution tree, and the AI council feed are not wired up yet —
        see README "Known gaps". This view polls the REST API every 5–10s; no websocket/SSE push yet.
      </footer>
    </div>
  );
}

function LeaderboardTable({ rows }: { rows: LeaderboardEntry[] }) {
  if (rows.length === 0) {
    return <p className="text-xs text-slate-500">No active agents yet — run scripts/bootstrap_population.py.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[12px]">
        <thead>
          <tr className="text-[10px] uppercase tracking-wider text-slate-500">
            <th className="py-1 pr-3">Rank</th>
            <th className="py-1 pr-3">Agent</th>
            <th className="py-1 pr-3">Family</th>
            <th className="py-1 pr-3">Equity</th>
            <th className="py-1 pr-3">ROI</th>
            <th className="py-1 pr-3">Max DD</th>
            <th className="py-1 pr-3">Trades</th>
            <th className="py-1 pr-3">Status</th>
          </tr>
        </thead>
        <tbody className="font-mono-num">
          {rows.map((row) => (
            <tr key={row.agent.id} className="border-t border-slate-900 hover:bg-slate-900/40">
              <td className="py-1 pr-3 text-slate-500">{row.rank}</td>
              <td className="py-1 pr-3 text-slate-200">{row.agent.identifier}</td>
              <td className="py-1 pr-3 text-slate-400">{row.strategy_family}</td>
              <td className="py-1 pr-3">{fmtUsd(row.agent.equity)}</td>
              <td className={`py-1 pr-3 ${row.agent.roi >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                {fmtPct(row.agent.roi)}
              </td>
              <td className="py-1 pr-3 text-amber-400">{fmtPct(row.agent.max_drawdown)}</td>
              <td className="py-1 pr-3">{row.agent.trade_count}</td>
              <td className="py-1 pr-3 text-slate-500">{row.agent.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
