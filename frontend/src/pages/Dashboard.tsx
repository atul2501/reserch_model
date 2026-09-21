import { api } from "../lib/api";
import { usePolling } from "../hooks/usePolling";
import { Panel } from "../components/Panel";
import { StatTile } from "../components/StatTile";
import { StatusDot } from "../components/StatusDot";
import { Badge, type BadgeTone } from "../components/Badge";
import type { AgentStatus, LeaderboardEntry } from "../types/api";

const REGIME_TONE: Record<string, BadgeTone> = {
  TREND_UP: "green",
  BREAKOUT: "green",
  TREND_DOWN: "red",
  BREAKDOWN: "red",
  HIGH_VOLATILITY: "amber",
  LOW_VOLATILITY: "neutral",
  RANGE: "neutral",
  UNCERTAIN: "neutral",
};

const STATUS_TONE: Record<AgentStatus, BadgeTone> = {
  ACTIVE: "green",
  PAUSED: "amber",
  DEAD: "neutral",
};

function fmtUsd(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 2 });
}

function fmtPct(n: number | null | undefined) {
  if (n === null || n === undefined) return "—";
  return `${(n * 100).toFixed(2)}%`;
}

function healthTone(ok: boolean | null | undefined): BadgeTone {
  if (ok === null || ok === undefined) return "neutral";
  return ok ? "green" : "red";
}

export function Dashboard() {
  const { data: health } = usePolling(api.health, 10_000);
  const { data: market, error: marketError } = usePolling(api.market, 5_000);
  const { data: population } = usePolling(api.population, 10_000);
  const { data: leaderboard } = usePolling(() => api.leaderboard(500, true), 10_000);

  const marketFresh = health?.market_data_stale === false;

  return (
    <div className="min-h-screen bg-bg text-text">
      <header className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-2 border-b border-line bg-surface/80 px-4 py-2.5 backdrop-blur-md">
        <div className="flex flex-wrap items-center gap-3">
          <span className="h-2 w-2 rounded-sm bg-accent-blue" aria-hidden />
          <span className="text-sm font-semibold tracking-wide text-text-strong">
            EVOLUTIONARY TRADING LAB
          </span>
          <span className="rounded border border-line px-1.5 py-0.5 text-[10px] uppercase text-muted">
            {health?.trading_mode ?? "…"}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={healthTone(health?.database_ok)}>
            <StatusDot ok={health?.database_ok ?? null} /> DB
          </Badge>
          <Badge tone={healthTone(health?.hyperliquid_configured)}>
            <StatusDot ok={health?.hyperliquid_configured ?? null} /> Hyperliquid
          </Badge>
          <Badge tone={healthTone(health?.ollama_configured)}>
            <StatusDot ok={health?.ollama_configured ?? null} /> Ollama
          </Badge>
          <Badge tone={healthTone(marketFresh)}>
            <StatusDot ok={marketFresh} /> {health?.market_data_stale ? "Stale" : "Fresh"}
          </Badge>
        </div>
      </header>

      <main className="grid grid-cols-1 gap-3 p-4 lg:grid-cols-3">
        <Panel title="Market" accent="blue" className="lg:col-span-1">
          {marketError && <p className="text-xs text-accent-red">No market data yet — is the worker running?</p>}
          <div className="grid grid-cols-2 gap-2.5">
            <StatTile label={market?.symbol ?? "SOL"} value={fmtUsd(market?.close_price)} loading={!market} />
            <StatTile
              label="Regime"
              value={market ? <Badge tone={REGIME_TONE[market.regime] ?? "neutral"}>{market.regime}</Badge> : ""}
              sub={market ? `${(market.regime_confidence * 100).toFixed(0)}% confidence` : undefined}
              loading={!market}
            />
            <StatTile label="Volatility pct." value={fmtPct(market?.volatility_percentile)} loading={!market} />
            <StatTile label="Volume ratio" value={market ? market.volume_ratio.toFixed(2) + "x" : "—"} loading={!market} />
          </div>
        </Panel>

        <Panel title="Population" accent="purple" className="lg:col-span-2">
          <div className="grid grid-cols-3 gap-2.5 sm:grid-cols-6">
            <StatTile label="Generation" value={population ? `Gen ${population.generation}` : "—"} loading={!population} />
            <StatTile label="Target" value={String(population?.target_size ?? "—")} loading={!population} />
            <StatTile label="Active" value={String(population?.active_count ?? "—")} tone="positive" loading={!population} />
            <StatTile
              label="Dead"
              value={String(population?.dead_count ?? "—")}
              tone={population && population.dead_count > 0 ? "negative" : "neutral"}
              loading={!population}
            />
            <StatTile label="Professional" value={String(population?.professional_count ?? "—")} loading={!population} />
            <StatTile
              label="Population equity"
              value={fmtUsd(population?.total_equity)}
              sub={population ? `of ${fmtUsd(population.total_capital_allocated)} allocated` : undefined}
              loading={!population}
            />
          </div>
        </Panel>

        <Panel title="Leaderboard" accent="green" className="lg:col-span-3">
          <LeaderboardTable rows={leaderboard ?? []} />
        </Panel>
      </main>

      <footer className="px-4 pb-4 text-[11px] uppercase tracking-wide text-muted-2">
        Agent detail drill-down, evolution tree, and the AI council feed are not wired up yet —
        see README "Known gaps". This view polls the REST API every 5–10s; no websocket/SSE push yet.
      </footer>
    </div>
  );
}

function LeaderboardTable({ rows }: { rows: LeaderboardEntry[] }) {
  if (rows.length === 0) {
    return <p className="text-xs text-muted">No active agents yet — run scripts/bootstrap_population.py.</p>;
  }
  return (
    <div className="max-h-[420px] overflow-auto rounded-lg border border-line">
      <table className="w-full text-left text-[12px]">
        <thead className="sticky top-0 z-[1] bg-surface-2">
          <tr className="text-[10px] uppercase tracking-wider text-muted-2">
            <th className="px-3 py-2">Rank</th>
            <th className="px-3 py-2">Agent</th>
            <th className="px-3 py-2">Family</th>
            <th className="px-3 py-2">Equity</th>
            <th className="px-3 py-2">ROI</th>
            <th className="px-3 py-2">Max DD</th>
            <th className="px-3 py-2">Trades</th>
            <th className="px-3 py-2">Status</th>
          </tr>
        </thead>
        <tbody className="font-mono-num">
          {rows.map((row) => (
            <tr
              key={row.agent.id}
              className="border-t border-line hover:bg-surface-2 hover:shadow-[inset_2px_0_0_var(--color-accent-blue)]"
            >
              <td className="px-3 py-1.5 text-muted">{row.rank}</td>
              <td className="px-3 py-1.5 text-text-strong">{row.agent.identifier}</td>
              <td className="px-3 py-1.5 text-muted">{row.strategy_family ?? "—"}</td>
              <td className="px-3 py-1.5">{fmtUsd(row.agent.equity)}</td>
              <td className={`px-3 py-1.5 ${row.agent.roi >= 0 ? "text-accent-green" : "text-accent-red"}`}>
                {fmtPct(row.agent.roi)}
              </td>
              <td className="px-3 py-1.5 text-accent-amber">{fmtPct(row.agent.max_drawdown)}</td>
              <td className="px-3 py-1.5">{row.agent.trade_count}</td>
              <td className="px-3 py-1.5">
                <Badge tone={STATUS_TONE[row.agent.status]}>{row.agent.status}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
