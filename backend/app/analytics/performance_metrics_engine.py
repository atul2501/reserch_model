"""Pure trade-statistics engine feeding PerformanceMetric snapshots.

`app/models/metrics.py::PerformanceMetric`/`FitnessScore` were defined with
exactly this shape in mind but have never had a writer — this module is the
calculation half; `app/analytics/performance_metrics_service.py` is the DB
I/O half that persists it and feeds `app/analytics/fitness_engine.py`.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass
class TradeStatsResult:
    win_rate: float | None
    loss_rate: float | None
    profit_factor: float | None
    expectancy: float | None
    average_trade: float | None
    average_winner: float | None
    average_loser: float | None
    largest_win: float | None
    largest_loss: float | None
    consecutive_wins: int | None
    consecutive_losses: int | None
    sharpe_like: float | None
    sortino_like: float | None
    average_holding_seconds: float | None
    return_volatility: float | None


def compute_trade_stats(net_pnls: list[float], holding_seconds: list[int]) -> TradeStatsResult:
    n = len(net_pnls)
    if n == 0:
        return TradeStatsResult(
            win_rate=None, loss_rate=None, profit_factor=None, expectancy=None,
            average_trade=None, average_winner=None, average_loser=None,
            largest_win=None, largest_loss=None, consecutive_wins=None, consecutive_losses=None,
            sharpe_like=None, sortino_like=None, average_holding_seconds=None, return_volatility=None,
        )

    wins = [p for p in net_pnls if p > 0]
    losses = [p for p in net_pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    mean_pnl = statistics.mean(net_pnls)
    stdev_pnl = statistics.pstdev(net_pnls) if n > 1 else 0.0
    downside = [p for p in net_pnls if p < 0]
    downside_dev = statistics.pstdev(downside) if len(downside) > 1 else 0.0

    consecutive_wins, consecutive_losses = _max_streaks(net_pnls)

    return TradeStatsResult(
        win_rate=len(wins) / n,
        loss_rate=len(losses) / n,
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else None,
        expectancy=mean_pnl,
        average_trade=mean_pnl,
        average_winner=(sum(wins) / len(wins)) if wins else None,
        average_loser=(sum(losses) / len(losses)) if losses else None,
        largest_win=max(net_pnls),
        largest_loss=min(net_pnls),
        consecutive_wins=consecutive_wins,
        consecutive_losses=consecutive_losses,
        sharpe_like=(mean_pnl / stdev_pnl) if stdev_pnl > 0 else None,
        sortino_like=(mean_pnl / downside_dev) if downside_dev > 0 else None,
        average_holding_seconds=statistics.mean(holding_seconds) if holding_seconds else None,
        return_volatility=stdev_pnl,
    )


def _max_streaks(net_pnls: list[float]) -> tuple[int, int]:
    """Longest consecutive-win and consecutive-loss streaks, in trade order.
    Flat trades (net_pnl == 0) break both streaks."""
    best_win_streak = current_win_streak = 0
    best_loss_streak = current_loss_streak = 0
    for pnl in net_pnls:
        if pnl > 0:
            current_win_streak += 1
            current_loss_streak = 0
        elif pnl < 0:
            current_loss_streak += 1
            current_win_streak = 0
        else:
            current_win_streak = 0
            current_loss_streak = 0
        best_win_streak = max(best_win_streak, current_win_streak)
        best_loss_streak = max(best_loss_streak, current_loss_streak)
    return best_win_streak, best_loss_streak
