# Autonomous Evolutionary Crypto Trading Laboratory

A research platform for crypto-perpetual strategies: **500 independent agents**, each with its own
$100 paper account and strategy DNA, competing on a shared, closed-candle market feed. Strategies are
evaluated, stress-tested, validated on protected out-of-sample data, bred, and promoted under
champion/challenger governance — reproducibly and with every decision auditable.

> **It does not trade real money.** `TRADING_MODE=paper` is the default; `shadow` measures execution
> against the real order book without sending orders; live order execution is deliberately **not
> implemented** (see [docs/security.md](docs/security.md)). Never use real capital with this code.

Docs: [architecture](docs/architecture.md) · [security & launch checklist](docs/security.md) · [runbook](docs/runbook.md)

## What it does

```
Hyperliquid (WS + REST) -> confirmed candle -> features/regime -> AI council (context)
   -> 500 DNA strategies -> Risk Engine -> sizing/margin -> paper|shadow execution -> PnL / equity / death
                                                   |
        scheduled research: evaluate -> fitness -> correlation -> regime -> adversarial
                  -> select -> crossover/mutation -> candidate validation -> new generation
                  -> protected OOS lockbox -> champion/challenger promotion
```

* **Closed candles only** — decisions never see a forming bar; gaps are backfilled or new entries halt.
* **Real strategy DNA** — declared indicators/periods, direction, family logic, sizing, stops, trailing,
  cooldowns and daily limits all change runtime behaviour, identically in the live loop and the backtester.
* **Realistic paper execution** — fees, size-aware slippage, latency, partial fills, rejects, funding
  from exchange settlements, cross-margin, liquidation, conservative OHLC assumptions.
* **AI council as context** — 8 analysts + judge with a quorum, deadlines and fail-closed behaviour; it
  shapes size/veto but never bypasses the Risk Engine and is never applied to a different candle.
* **Scientific validation** — experiment registry, dataset fingerprints, walk-forward, adversarial
  scenarios, regime classification, correlation-aware fitness, a once-only OOS lockbox, reality-gap tracking.
* **Safety & audit** — worker lease, DB-level idempotency, immutable snapshots, kill switch, role-based API,
  metrics, health checks, a dashboard that shouts when the worker stops.

## Quick start

```bash
./run.sh start        # venv, deps, migrations, bootstrap population, then worker + research + API
./run.sh status | logs | stop
# dashboard: http://127.0.0.1:8000/   (API keys required — see below)
```

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp ../.env.example .env                     # fill OLLAMA_* ; secrets never go in git
python -m scripts.hash_api_key me viewer    # -> add the printed API_KEYS entry to .env
alembic upgrade head
python -m scripts.bootstrap_population
python -m scripts.run_cycle                 # trading worker (single instance via DB lease)
python -m scripts.run_research              # scheduled evolution (only acts when its gates pass)
uvicorn app.main:app                        # API + dashboard (127.0.0.1:8000)
```

**Production** uses PostgreSQL: `DATABASE_URL=postgresql+asyncpg://…` then `alembic upgrade head`
(SQLite remains the default for local development and tests). systemd units are in `docs/systemd/`.

## Configuration highlights

| Setting | Default | Meaning |
|---|---|---|
| `TRADING_MODE` | `paper` | `paper` / `shadow` (never sends orders) / `live` (blocked) |
| `AGENT_COUNT`, `AGENT_STARTING_BALANCE` | 500, 100 | population size, fresh balance per generation |
| `COUNCIL_MIN_SUCCESSFUL_ANALYSTS` | 6 | of 8; fewer => INCOMPLETE, no new trades |
| `COUNCIL_INTERVAL_CANDLES` | 5 | council runs every Nth candle; other candles are `NOT_RUN` (never a stale reuse) |
| `MAX_LEVERAGE`, `MAX_POSITION_SIZE` | 5, 0.5 | position size bounds **margin**; leverage is a real multiplier |
| `MAX_EXPOSURE_MULTIPLE`, `MAX_LOSS_PER_TRADE_FRACTION` | 2.0, 0.05 | gross exposure cap; loss-at-stop cap |
| `EVOLUTION_ENABLED`, `EVOLUTION_INTERVAL_HOURS` | true, 24 | scheduled research cadence |
| `API_AUTH_REQUIRED`, `API_KEYS` | true, — | fail-closed API auth; roles viewer/researcher/operator/admin |

All settings are documented in [.env.example](.env.example).

## Tests

```bash
cd backend
.venv/bin/python -m pytest -q                                            # SQLite
DATABASE_URL=postgresql+asyncpg://user@host/db .venv/bin/python -m pytest -q   # PostgreSQL
```

The suite covers: closed-candle integrity, gap recovery, the worker scheduler/lease/cycle recovery,
dynamic indicators, every strategy family, sizing, execution realism, margin/liquidation, funding,
stops/trailing, cooldown/limits, council integration & failure modes, Ollama 401/403/429/timeout/5xx/
malformed, WebSocket transport, OOS lockbox, evolution pipeline, promotion evidence, adversarial
scenarios, shadow mode, live gates, API auth/roles, migrations (SQLite + PostgreSQL), dashboard script,
and a 500-agent performance test.

## Known limitations (honest list)

* Live trading is **not implemented** and must stay blocked; the launch checklist in
  [docs/security.md](docs/security.md) is entirely open.
* Order-flow strategies use a bar-based imbalance *proxy* (no tape / L2 history is stored).
* Paper and backtest both fill at the next bar's open (parity is tested); SHADOW fills against the live book.
  The backtest applies no latency drift / random rejects / partial fills (adversarial scenarios add them).
* Shadow uses one shared book snapshot per cycle; it does not deplete liquidity between agents.
* The council runs on its cadence; on candles where it is not due it is explicitly *not required* (`NOT_RUN`).
  When it is required, any failure (quorum, judge, timeout, malformed, wrong candle) blocks new entries.
* After an outage longer than `MAX_CATCHUP_BARS` skipped bars are not *decided* on, but open positions are still
  protected on every one of them (stop/take-profit/trailing/funding replay).
* The sealed OOS holdout ages: research uses only data before it until an operator renews it.
* Agent fitness still aggregates paper and shadow trades per agent (positions/orders are venue-tagged, agents are not).
* `backend/.env` was committed in the past: **rotate all keys** and purge history (see security doc).
