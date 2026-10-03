# Pre-trade shadow export

Generated 2026-10-03T03:48:46.765382+00:00 - dataset version `shadow_dataset_v1` - 1979 candidates over 41 shadow bars.

**HYPOTHETICAL SHADOW DATA - NOT REAL P&L. Shadow never placed an order.**

Cost model: fee 8.79 + slippage 5.32 = **14.11 bps** round trip (measured_paper_trades(n=282)).

Gate-pass, 10 min: gross -6.550145458781241 bps -> **net -20.65539358104138 bps** (n=271).

Warnings: SINGLE WINDOW: fewer than 2 days of shadow data - no time-stability evidence

## Information boundary

Every gate input was recorded at decision time. Outcome columns (return_*, mfe_*, mae_*) were measured afterwards from confirmed candles strictly after the signal bar and are NULL until the horizon has passed. High/low are never used as fill prices.

## Data dictionary (shadow_decisions.csv)

| column | meaning |
|---|---|
| `decision_id` | agent_id:signal_bar_open_ms - unique per shadow candidate |
| `timestamp` | wall-clock ms when the shadow decision was created (UTC epoch ms) |
| `bar_time` | signal bar OPEN time (UTC epoch ms); its close (bar_time+60000) is the information cutoff |
| `symbol` | instrument |
| `agent_id` | agent (paper population) |
| `generation` | agent generation |
| `strategy` | strategy family of the agent's DNA |
| `direction` | LONG/SHORT signalled by the strategy |
| `signal_strength` | family setup strength (0..1) recorded by the strategy engine |
| `regime` | rule-based regime of the signal bar |
| `entry_price` | entry observation: real best bid/ask MID at the shadow execution point (entry_price_source=l2_mid), else signal-bar close |
| `gate_pass` | ExecutionGate verdict (would trade) |
| `gate_reasons` | JSON list of gate rejection reasons |
| `decision_age_ms` | validation time minus information cutoff |
| `price_drift_bps` | signed move from signal close to execution point (+ = in the trade's favour) |
| `spread_bps` | measured best ask-bid spread at the execution point (NULL if the book read failed) |
| `estimated_cost_bps` | round-trip fee+slippage MEASURED from the paper trades actually booked (see cost_source) |
| `council_called` | an LLM council snapshot existed at decision time |
| `council_direction` | its bias |
| `council_confidence` | its confidence |
| `council_agrees` | council direction == strategy direction |
| `council_age_ms` | decision time minus the council's information cutoff |
| `paper_traded` | the EXISTING paper path placed an entry for the same agent+bar |
| `paper_direction` | its side |
| `paper_entry_price` | its fill |
| `paper_exit_price` | its exit |
| `paper_pnl` | its realised net P&L (USD) |
| `paper_net_bps` | its realised net P&L per unit notional (bps) |
| `return_1m_bps` | signed (in `direction`) return from entry_price to the close of the bar 1 min after the signal bar; NULL until that bar closed |
| `return_5m_bps` | signed (in `direction`) return from entry_price to the close of the bar 5 min after the signal bar; NULL until that bar closed |
| `return_10m_bps` | signed (in `direction`) return from entry_price to the close of the bar 10 min after the signal bar; NULL until that bar closed |
| `return_30m_bps` | signed (in `direction`) return from entry_price to the close of the bar 30 min after the signal bar; NULL until that bar closed |
| `return_60m_bps` | signed (in `direction`) return from entry_price to the close of the bar 60 min after the signal bar; NULL until that bar closed |
| `mfe_1m_bps` | best signed excursion over the next 1 bars (high/low; measurement only, never a fill) |
| `mfe_5m_bps` | best signed excursion over the next 5 bars (high/low; measurement only, never a fill) |
| `mfe_10m_bps` | best signed excursion over the next 10 bars (high/low; measurement only, never a fill) |
| `mfe_30m_bps` | best signed excursion over the next 30 bars (high/low; measurement only, never a fill) |
| `mfe_60m_bps` | best signed excursion over the next 60 bars (high/low; measurement only, never a fill) |
| `mae_1m_bps` | worst signed excursion over the next 1 bars |
| `mae_5m_bps` | worst signed excursion over the next 5 bars |
| `mae_10m_bps` | worst signed excursion over the next 10 bars |
| `mae_30m_bps` | worst signed excursion over the next 30 bars |
| `mae_60m_bps` | worst signed excursion over the next 60 bars |
| `fee_bps` | measured round-trip fees (bps) |
| `slippage_bps` | measured round-trip slippage (bps) |
| `net_return_1m_bps` | return_1m_bps minus estimated_cost_bps |
| `net_return_5m_bps` | return_5m_bps minus estimated_cost_bps |
| `net_return_10m_bps` | return_10m_bps minus estimated_cost_bps |
| `net_return_30m_bps` | return_30m_bps minus estimated_cost_bps |
| `net_return_60m_bps` | return_60m_bps minus estimated_cost_bps |

Additional audit columns (risk reasons, latency stamps, versions, bid/ask, book timestamps) follow the documented ones.
