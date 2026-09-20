// Mirrors backend/app/schemas/api.py — kept in sync by hand since this is a
// small surface; a generated OpenAPI client would be the next step if the
// API grows (see docs/README "Known gaps").

export type AgentStatus = "ACTIVE" | "PAUSED" | "DEAD";
export type MarketRegime =
  | "TREND_UP"
  | "TREND_DOWN"
  | "RANGE"
  | "HIGH_VOLATILITY"
  | "LOW_VOLATILITY"
  | "BREAKOUT"
  | "BREAKDOWN"
  | "UNCERTAIN";

export interface AgentSummary {
  id: string;
  identifier: string;
  generation: number;
  status: AgentStatus;
  strategy_version_id: string;
  balance: number;
  equity: number;
  starting_balance: number;
  roi: number;
  realized_pnl: number;
  max_drawdown: number;
  trade_count: number;
  is_professional: boolean;
  best_milestone_multiple: number;
  fitness: number | null;
  created_at: string;
}

export interface AgentDetail extends AgentSummary {
  fees_paid: number;
  funding_paid: number;
  peak_equity: number;
  death_timestamp: string | null;
  death_reason: string | null;
  final_equity: number | null;
  final_pnl: number | null;
}

export interface LeaderboardEntry {
  rank: number;
  agent: AgentSummary;
  strategy_family: string;
}

export interface MarketSnapshot {
  symbol: string;
  close_price: number;
  regime: MarketRegime;
  regime_confidence: number;
  candle_open_time: number;
  volatility_percentile: number;
  volume_ratio: number;
}

export interface PopulationSummary {
  generation: number;
  target_size: number;
  active_count: number;
  dead_count: number;
  professional_count: number;
  total_equity: number;
  total_realized_pnl: number;
  total_capital_allocated: number;
}

export interface SystemHealth {
  database_ok: boolean;
  hyperliquid_configured: boolean;
  ollama_configured: boolean;
  trading_mode: string;
  market_data_stale: boolean | null;
  last_candle_age_seconds: number | null;
}
