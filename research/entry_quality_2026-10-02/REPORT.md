# Entry Quality research — backup `trading_lab_20261002_162728.dump`

Research only. No production code, config, database, or V1 model was changed.

## Verdict
**RESEARCH STRATEGY/SIGNAL EDGE + COST STRUCTURE. KEEP V1 as shadow-only (no V2, no XGBoost).**

- None of the 36 model configurations (LR, RF, HGB, XGB × 2 feature sets × 2 targets × 3 walk-forward folds) produced positive OOS expectancy in any fold.
- Tree models overfit: train AUC 0.92–0.96 vs OOS 0.50–0.52.
- Signed forward returns after entry are ~0 bps at every horizon from 1 to 60 minutes, while round-trip friction is ~13.5 bps. Frictionless expectancy is +0.08 bps (PF 1.009).
- The bottleneck is that the signals have no edge relative to their cost. The classifier is not the bottleneck.

## Reproduce
1. Restore the dump into an ISOLATED Postgres (this run: throwaway cluster on 127.0.0.1:55432, db `trading_lab_research_20261002`).
2. Use a venv with pandas 2.2.3, numpy 2.1.1, scikit-learn 1.7.2, xgboost 3.2.0, psycopg2-binary, pyarrow and pytest.
3. Run `extract.py` → `audit.py` → `baseline.py` → `entry_exit.py` → `segments.py` → `costs.py` → `features.py` → `pytest test_leakage.py` → `v1_rules.py` → `models.py` → `post.py`.
4. `features.py` imports the production V1 modules from `backend/` (path hard-coded), so the V1 scores match production exactly.

Script outputs from this run are in `outputs/`.

## Splits (UTC, by signal-bar time; 2h purge/embargo)
| Fold | Train | Validation | True OOS |
|---|---|---|---|
| WF1 | 09-27 08:11 → 09-28 17:41 | 09-28 20:04 → 09-29 13:53 | 09-29 16:01 → 09-30 11:55 |
| WF2 | 09-27 08:11 → 09-29 13:53 | 09-29 16:01 → 09-30 09:51 | 09-30 12:00 → 10-01 07:55 |
| FINAL | 09-27 08:11 → 09-30 11:55 | 09-30 14:03 → 10-01 11:56 | 10-01 14:00 → 10-02 15:30 |

The FINAL validation and OOS windows start after V1's whole dataset (which ends 09-30 13:52), so V1 never saw them.

## Data anomalies found
- **202 generation-rollover trades were settled at a stale price of 123.36** (the last close at that level was 2026-09-27 20:14). This hit the gen 1→2, 2→3 and 3→4 rollovers, where SOL was trading at ~118.8. The trades are 140–383 bps off market, and **189 of them have `closed_at < opened_at`**. They produced −$34.03 of corrupted net P&L.
- The gen 4→5 and 5→6 rollovers are clean.
- All 87 agents whose `realized_pnl` differs from the sum of their trades' `net_pnl` hold one of these trades.
- 159 agents have `balance − (start + realized_pnl)` ≠ 0. The difference is small (median $0.007) and the cause was not found.
- 2 take-profit exits filled 12–17 bps outside their bar.
- 36 trades have no `trade_analytics` row.
- No orphan trades, duplicate trades, overlapping positions, future timestamps, OHLC violations, candle gaps, or broken net-P&L identities were found. The identity checked was `net = gross − fees − funding`.
