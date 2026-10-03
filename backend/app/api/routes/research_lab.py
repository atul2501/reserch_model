"""RESEARCH LAB API: experiment registry, leaderboard (by OOS NET expectancy), failures, data sufficiency and the
proposed next experiment. Read-only; nothing here can train, deploy or trade."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from app.core.config import BACKEND_DIR, get_settings

router = APIRouter(prefix="/api/research-lab", tags=["research-lab"])


def _dir(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else BACKEND_DIR / q


def _days_covered(hours: dict) -> float:
    return max(hours.values(), default=0) / 24.0


def data_sufficiency() -> dict:
    from app.edge_research.datasets import coverage
    from app.pretrade.dataset import load_records

    s = get_settings()
    rec = load_records(_dir(s.pretrade_shadow_dir))
    cand = rec[rec.record_type == "candidate"] if len(rec) and "record_type" in rec else rec
    shadow_days = ((cand.decision_ms.max() - cand.decision_ms.min()) / 86_400_000) if len(cand) else 0.0
    micro = coverage(_dir(s.microstructure_dir)) if _dir(s.microstructure_dir).exists() else {}
    book_hours = max(micro.get("SOL:bbo", 0), micro.get("SOL:l2Book", 0))
    flow_hours = micro.get("SOL:trades", 0)
    btc_hours = max(micro.get("BTC:bbo", 0), micro.get("BTC:trades", 0))
    micro_days = min(book_hours, flow_hours) / 24.0
    return dict(
        shadow_observations=int(len(cand)), independent_signal_bars=int(cand.signal_bar_open_time_ms.nunique()) if len(cand) else 0,
        shadow_days_collected=float(shadow_days), oos_windows_available_1d=int(max(0, shadow_days - 3)),
        order_book_coverage_hours=book_hours, trade_flow_coverage_hours=flow_hours, btc_coverage_hours=btc_hours,
        microstructure_days=micro_days, microstructure_files=micro,
        requirement="4 independent 1-day OOS windows need >= 7 days (2 train + 1 validation + 4 OOS)",
    )


@router.get("/summary")
async def research_lab_summary():
    from app.edge_research.proposer import propose
    from app.edge_research.registry import ExperimentRegistry

    reg = ExperimentRegistry()
    recs = reg.all()
    real = [r for r in recs if not r.get("seed")]
    suff = data_sufficiency()

    def row(r):
        return dict(experiment_id=r.get("experiment_id"), date=str(r.get("date"))[:19], seed=bool(r.get("seed")),
                    hypothesis=r.get("hypothesis"), model=r.get("model"), horizon_min=r.get("horizon_min"),
                    features=r.get("features"), oos_trades=r.get("oos_trades"), oos_net_expectancy_bps=r.get("oos_net_expectancy_bps"),
                    oos_profit_factor=r.get("oos_profit_factor"), oos_total_net_bps=r.get("oos_total_net_bps"),
                    status=r.get("status"), decision=r.get("decision"), warnings=r.get("warnings", []),
                    evidence=r.get("evidence"))
    ranked = sorted([r for r in recs if r.get("oos_net_expectancy_bps") is not None],
                    key=lambda r: -(r.get("oos_net_expectancy_bps") or -1e9))
    robust = [r for r in real if r.get("status") == "ROBUST OOS EDGE"]
    best = robust[0] if robust else (max(real, key=lambda r: r.get("oos_net_expectancy_bps") or -1e9) if real else None)
    proposal = propose(reg, data_days={"microstructure": suff["microstructure_days"], "shadow": suff["shadow_days_collected"],
                                       "candles_btc": suff["btc_coverage_hours"] / 24.0})
    return dict(
        current_status=dict(
            deployable_edge="YES (ROBUST OOS EDGE - shadow only)" if robust else "NO",
            best_verified_experiment=row(best) if best else None,
            experiments_run=len(real), seeded_prior_experiments=len(recs) - len(real),
            last_experiment=row(real[-1]) if real else None,
            note="'Best' = best VERIFIED out-of-sample NET expectancy, never training/validation score, AUC or win rate."),
        leaderboard=[row(r) for r in ranked],
        failures=[row(r) for r in recs if r.get("decision") in ("REJECTED", "OOS_FAILED")],
        data_sufficiency=suff, next_experiment=proposal,
        rules=["No model shopping: models are limited to rule and ridge.",
               "Thresholds are chosen on validation only; OOS windows are never used for any choice.",
               "An experiment equivalent to an earlier failure is refused unless it runs on new data with a written justification.",
               "Nothing here can trade. The best possible outcome is ACCEPTED_FOR_SHADOW."],
    )
