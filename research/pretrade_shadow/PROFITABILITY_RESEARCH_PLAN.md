# Profitability Research Plan: Finding a Real, Cost-Adjusted, Out-of-Sample Edge

**Status as of 2026-10-03: NO DEPLOYABLE EDGE.**

The registry holds 31 prior experiments, every one NO EDGE or WEAK EDGE, and 1 new experiment (NEEDS_MORE_DATA). This plan describes the system built to search for an edge *without repeating that work*, and the next experiment.

## 1. What was built

| Component | Where | Purpose |
|---|---|---|
| Experiment registry | `backend/app/edge_research/registry.py`; data in `research/edge_registry/experiments.jsonl` | Append-only record of every experiment. **Refuses** exact repeats and re-tuned variants of failed hypotheses (model shopping) unless new data **and** a written justification exist. Exact replication on ≥ 3 days of *new* data is allowed, because that is genuine OOS confirmation. |
| Prior research seeds | `backend/app/edge_research/seeds.py` | The last 25 days of research as 31 registry entries, each with its result and source report. Reproducing them is refused. |
| Walk-forward | `backend/app/edge_research/walkforward.py` | Expanding train → validation → OOS, ≥ 1 h embargo, label purging, multiple consecutive non-overlapping OOS windows. Leakage is asserted in code. |
| Evaluation gate | `backend/app/edge_research/evaluate.py` | Trading metrics on **net** returns and the objective status labels (section 2). |
| Runner | `backend/app/edge_research/experiments.py` | Only two models: **rule** and closed-form **ridge**. A cost-aware target: trade only when the predicted gross move exceeds the measured cost. Selection level chosen on **validation only**, with thresholds from the **train** distribution. |
| Datasets | `backend/app/edge_research/datasets.py` | 1m bars with causal BTC features; strategy signals (signed, next-open entry); microstructure on a 15 s grid (BBO imbalance, microprice, aggressor flow 10/60 s, trade intensity, BTC 10/60 s lead). Every feature uses data timestamped ≤ decision time. |
| Microstructure collector | `backend/scripts/collect_microstructure.py` | Separate process, public WebSocket: SOL/BTC trades (aggressor side), SOL/BTC BBO, SOL l2Book. Hourly gzip files. No database, no keys. |
| Proposer | `backend/app/edge_research/proposer.py` | Chooses the next experiment from evidence: replicate a positive result first, otherwise the first untested library hypothesis whose data requirement is met, otherwise **collect that data**. |
| CLI | `python -m scripts.edge_research seed\|propose\|run <H>\|list` | |
| Shadow dataset and export | `backend/app/pretrade/dataset.py`, `report.py`, `assemble.py`; `python -m scripts.export_pretrade_shadow` | One row per shadow candidate with forward returns, MFE/MAE, measured costs, the paper outcome and the council view. |
| Dashboards | `/pretrade-shadow`, `/research-lab` | See `DASHBOARD.md`. |

**Tested**, `tests/test_edge_research.py`, 20 tests, including:

- a **positive control**: a synthetic real edge *is* found (ROBUST OOS EDGE);
- a **negative control**: pure noise is rejected;
- a **weak-edge control**: a gross edge consumed by costs is labelled WEAK EDGE;
- an **OOS-isolation test**: flipping only the OOS outcomes leaves the validation choice unchanged.

A framework that can never say "yes" would be as useless as one that always does.

## 2. Objective status definitions

All of these are computed on pooled and per-window **out-of-sample** trades, **net** of measured cost.

| Status | Requirements | Decision |
|---|---|---|
| **ROBUST OOS EDGE** | ≥ 4 OOS windows, each with ≥ 30 trades; ≥ 200 independent bars; pooled net > 0 **and** block-bootstrap 95% CI lower bound > 0; one-sided p < 0.05 **after Bonferroni** over every non-seed experiment run; net PF ≥ 1.10; ≥ 75% of windows positive; no window > 50% of total net P&L; neighbouring selection levels also net-positive | ACCEPTED_FOR_SHADOW |
| **OOS POSITIVE** | Enough windows/trades, pooled net > 0, net PF > 1.0, ≥ 60% of windows positive | PROMISING (must replicate on new data) |
| **PROMISING** | Pooled OOS net > 0 but not enough evidence | NEEDS_MORE_DATA |
| **WEAK EDGE** | Gross OOS mean > 0 with clustered t ≥ 2, but net ≤ 0 | REJECTED (does not survive costs) |
| **NO EDGE** | Anything else | OOS_FAILED if validation looked positive (overfit), else REJECTED |

**Guards:**

- **Too little data is never a rejection.** With fewer than 4 OOS windows available the decision is NEEDS_MORE_DATA, which does not block re-running.
- **A hypothesis that rarely fires and loses on ample data is a rejection.**
- **Statistics are suppressed on too few clusters.** t-stats and CIs need ≥ 5 independent two-hour blocks; otherwise they are blank.

**Cost** is the round trip **measured from paper fills** (`measured_paper_trades(n=…)`; 14.1 bps in the latest run: fees 8.8 + slippage 5.3). It falls back to the configured fee schedule only when no trades exist, and says so.

## 3. What has already been tested (seeded; will be refused if repeated)

| Area | Experiments | Result |
|---|---|---|
| ML entry-quality filters | V1 logistic; logistic V2; random forest; hist-gradient-boosting; XGBoost (v1 / extended features) | NO EDGE, OOS_FAILED. Best OOS −10.7 bps; trees overfit (train AUC ~0.95, OOS ~0.5). |
| Existing strategy signals, fixed holds | traded and all signals at 1–60 min | NO EDGE. −11.7 to −14.4 bps net; mid-price edge ≈ 0. |
| Filters | minimum expected move, top confidence, cooldowns | NO EDGE |
| Structure | strategy × regime × side (40 combos) | 0 combos stable above cost |
| Order flow | candle-colour flow-imbalance proxy; order_flow family | NO EDGE / OOS_FAILED (positive only in the last, drifting window) |
| Exits | ATR stop/target grid, trailing, fixed time | NO EDGE: exits cannot create an edge entries lack |
| Search | walk-forward over ~16k rules | OOS_FAILED: −21.4 bps pooled; a different "best" rule every fold |
| LLM | council directional calls | NO EDGE: 48% accuracy |
| Cross-asset | BTC 1m residual lead | WEAK EDGE: +0.7–0.9 bps gross, mostly intra-minute |
| Latency | removing the LLM wait | no economic change (−13.52 → −13.43 bps) |

**Conclusion carried forward.** Candle-derived signals on 1-minute SOL hold about 0 bps of edge against about 14 bps of cost. **Do not spend more time on them.**

## 4. The information gap and the hypothesis library

The system has only public 1m OHLCV. What it lacks, and what can actually be obtained in real time, is microstructure (book imbalance, microprice, aggressor flow, trade intensity, spread dynamics) and seconds-level cross-asset moves.

The library (`proposer.LIBRARY`), in order of new information:

| Key | Hypothesis | Data needed |
|---|---|---|
| **H1-MICRO-1M** | BBO imbalance, microprice offset and aggressor flow (10/60 s) predict SOL's mid over 1 min by more than cost | ≥ 7 days microstructure |
| H2-MICRO-5M | The same at 5 min (larger moves vs fixed cost) | ≥ 7 days microstructure |
| H3-BTC-LEAD-SEC | BTC's 10–60 s move not yet in SOL predicts SOL's next minute | ≥ 7 days microstructure |
| H4-CANDLE-BTC-RIDGE | Cost-aware ridge on SOL+BTC 1m returns/volatility at 5 min | ≥ 4 days BTC coverage |

Why 7 days: 2 days of training, 1 day of validation and 4 one-day OOS windows are the minimum for the ROBUST gate.

## 5. Next experiment (single highest value)

**Run the microstructure collector continuously for ≥ 7 days, ideally the same 14 days as the shadow run, then run `H1-MICRO-1M`.**

```
python -m scripts.collect_microstructure            # its own service on EC2; no DB, public data only
python -m scripts.edge_research propose             # will say RUN H1-MICRO-1M once >= 7 days exist
python -m scripts.edge_research run H1-MICRO-1M
```

**Why this, and not anything else:**

- Every candle-only idea is exhausted and seeded.
- The forensic audit's top recommendation was new information.
- BTC lead-lag exists but lives inside the minute.
- The proposer independently returns `COLLECT_DATA: H1-MICRO-1M` from the registry.

A pipeline check ran H1 on the ~13 minutes collected so far. The result was correctly **NEEDS_MORE_DATA** (0 OOS windows), not a rejection.

**Evidence that would count as success**, and only then: H1 or H2 reaches ROBUST OOS EDGE, then replicates on ≥ 3 new days (exact replication is allowed by the registry), then passes ≥ 2 weeks in shadow, then paper validation. Never skip a stage.

**What would end this line of research:** H1–H3 all fail on ≥ 7 days with enough trades. The proposer would then return **STOP**: "no deployable edge; new information sources are required". Candidates beyond that are liquidation streams, funding/OI events, and passive-fill (maker) execution data. The last could cut cost from ~14 to ~3–8 bps, but its fill rate must be measured before it is assumed.

## 6. The self-directed research loop

```
shadow data + microstructure data
   → proposer: is a positive result waiting for replication? → REPLICATE
   → else first library hypothesis not refused by the registry
        → data sufficient? → RUN (train → validation → 4+ OOS windows, measured cost) → objective gate → registry
        → else → COLLECT_DATA (exact shortfall shown in /research-lab)
   → nothing left → STOP: NO DEPLOYABLE EDGE
```

**This is not "train until it looks profitable".**

- The models are fixed.
- Thresholds are chosen only on validation.
- Repeats are refused.
- The multiple-testing correction gets stricter with every experiment run.
- **Nothing is ever deployed automatically.** The best possible outcome is ACCEPTED_FOR_SHADOW.

## 7. Entry Quality V1

Entry Quality V1 is a **frozen historical baseline** (`app/analytics/entry_quality_model.py`, shadow-only, not in the execution path). It is seeded in the registry as `SEED-EQ-V1` (OOS_FAILED), and the new framework makes it redundant.

**Archive later (not done here):**
1. Remove `/entry-quality` from the navigation and stop computing its audit.
2. Move the module and its tests under `research/archive/entry_quality_v1/`.
3. Keep `research/entry_quality_2026-10-02/` (its training/evaluation artefacts), which is required for reproducibility.

Nothing was deleted in this task.
