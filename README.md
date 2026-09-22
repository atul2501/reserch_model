# Autonomous Evolutionary Crypto Trading Laboratory

A strategy discovery and evaluation platform for SOL perpetuals on Hyperliquid. It is
**not** an LLM trading bot — the core principle is:

```
Market Intelligence -> AI Research Council -> Strategy DNA -> Deterministic Trading Engine
    -> Risk Engine -> Execution -> Scientific Evaluation -> Evolution -> New Candidates
```

Ollama is the research brain (strategy analyst, judge, evolutionary researcher). The
trading, risk, and execution logic is deterministic and fully auditable — Ollama never
places a trade or overrides the risk engine.

## Status: this is a working foundation, not a finished product

This repository was built from zero in one focused implementation pass, then migrated
from Postgres to a single local SQLite file so the whole stack runs with zero external
services. Everything described below as "built" has been exercised against a real
database (originally Postgres, now SQLite — the ~525-agent population was carried over
via `scripts/migrate_postgres_to_sqlite.py`) and (where applicable) the real
Hyperliquid public API — not just written and assumed correct. Everything under "Known
gaps" is an honest TODO, not a stub pretending to be finished (see
`app/execution/live_adapter.py` for the canonical example of how this codebase prefers
"raises NotImplementedError with a clear reason" over a fake implementation).

### What's built and verified

- **Config / logging / database** — Pydantic settings, structured JSON logging with
  secret redaction, async SQLAlchemy + Alembic, SQLite (`aiosqlite`/`sqlite3`). A single
  squashed migration applies and rolls back cleanly (the `orders`/`decisions` circular
  reference is resolved by only one side carrying a real FK constraint, rather than
  Postgres's deferred `ALTER TABLE ADD CONSTRAINT`, which SQLite doesn't support).
- **Market data pipeline** — `HyperliquidClient` fetches real 1m SOL candles from
  Hyperliquid's public `/info` endpoint (verified live). `MarketDataService` upserts
  idempotently, detects gaps, and flags stale data.
- **Feature engine** — trend/momentum/volatility/structure/volume/price-action
  features computed with pandas, plus a deterministic regime classifier. Covered by a
  look-ahead-bias regression test (truncated series must match the full series at the
  same index).
- **Strategy DNA** — a strict Pydantic schema (entry/exit rule sets, risk profile,
  sizing, stops, cooldowns) that both the mutation/crossover engine and an Ollama
  strategy-proposal prompt must produce valid instances of.
- **Initial population factory** — generates a configurable, diverse mix of 10
  strategy families (momentum, trend-following, breakout, mean-reversion, volatility,
  market-structure, VWAP, scalping, order-flow, hybrid) rather than 500 clones.
  Deterministic given a seed.
- **Deterministic rule engine** — evaluates DNA against a `MarketContext` with no
  network calls, fast enough to run for hundreds of agents per candle.
- **Risk engine** — hard blockers (stale data, non-positive equity, drawdown/daily-loss
  limits, duplicate positions, abnormal volatility) and soft reductions (leverage,
  position size), fully unit tested.
- **Execution engine** — `PaperExecutionAdapter` (fees, slippage, latency simulated;
  tested to make zero real network calls) and `ShadowExecutionAdapter`. The router
  refuses to construct a live adapter unless every safety gate in `.env` passes.
- **PnL / fitness engines** — trade PnL always nets fees/funding/slippage. Fitness is
  a weighted composite (return, risk, consistency, robustness, OOS, drawdown penalty),
  not raw PnL — tested to rank a disciplined lower-return strategy above a
  high-return/high-drawdown one.
- **Agent lifecycle** — `$100` starting capital per agent, independent balances,
  permanent death at `equity <= 0`, milestone multiples that never downgrade,
  `GENxx-AGyyyy` identifiers that are never reused. All tested, including population
  extinction detection.
- **Backtesting** — event-driven, fills happen at the *next* bar's open (never the
  signal bar's own close), chronological train/validation/final-test splits, and a
  walk-forward runner that reports every window, not just the best one.
- **AI council** — 8 analyst prompts + a deterministic Python vote-tally/consensus
  engine + an Ollama judge invoked only on weak consensus. Every response is validated
  against a Pydantic schema; malformed responses never reach the trading engine.
- **OllamaClient** — external API only (never localhost), bearer auth, timeout,
  retry/backoff, bounded concurrency, structured logging, and tests for timeout / 429 /
  malformed JSON / schema-mismatch handling.
- **Evolution primitives** — mutation, crossover, DNA-distance/diversity scoring, and
  champion/challenger promotion criteria (a challenger can never win purely on
  short-term PnL).
- **Decision loop** — the full per-candle path (shared context -> per-agent signal ->
  risk check -> paper fill -> position/trade/PnL update -> full `Decision` audit row)
  is wired together and integration-tested end-to-end, including mark-to-market of
  open positions every candle.
- **API + dashboard** — `/api/system/health`, `/api/market`, `/api/population`,
  `/api/agents`, `/api/agents/{id}`, `/api/leaderboard`. A single unstyled static page
  (`backend/app/static/index.html`, served by FastAPI at `/`) polls these and was
  visually verified against live data.
- **End-to-end run**: `bootstrap_population.py` created a real diverse population in
  Postgres, `run_cycle.py --once` fetched a live SOL candle from Hyperliquid, computed
  features/regime, ran the decision loop for every active agent, and produced real
  `Decision`/`Order`/`Position` rows with fees correctly deducted — observed directly
  in the database, not just asserted in a test.

### Known gaps (interfaces exist; implementation does not — see section 57's rule)

- **Live Hyperliquid execution** — `HyperliquidLiveExecutionAdapter` is interface-only
  and raises `NotImplementedError`. Real order placement needs EIP-712 signing, nonce
  management, and fill-resolution via websocket user events. Do not attempt to make
  this "work" by faking a fill — see the module docstring for the exact remaining work.
- **Realtime dashboard push** — the frontend polls REST every 5-10s. WebSocket/SSE
  (spec section 34) is not implemented; `usePolling` is the documented seam to swap in.
- **Dashboard depth** — agent detail drill-down, the evolution/generation tree page,
  and the AI council feed page are not built. Their API/data model already exists
  (`AgentDetail`, `CouncilDecision`/`CouncilAnalysis` tables); only the UI is missing.
- **Extinction/generation research reports** — `record_extinction()` writes a
  placeholder report; the full report content (spec sections 51/52) and the
  Ollama-driven population post-mortem analysis are not implemented.
- **Automatic post-extinction repopulation** — intentionally NOT automatic. Extinction
  is recorded; a human or scheduled job must run `bootstrap_population.py` after
  reviewing the report, per spec section 15's evolution pipeline.
- **Champion/challenger promotion wiring** — `evolution/champion.py` has tested
  promotion-decision logic, but nothing yet calls it against real walk-forward/OOS
  results to actually promote a strategy in the database.
- **Order-flow / open-interest features** — Hyperliquid's public API surface used here
  gives OHLCV + funding + open interest at the meta level; true tick-level order-flow
  imbalance is not implemented (the `order_flow` strategy family currently keys off
  volume spikes as a proxy).
- **Live trading safety runtime checks** — `Settings.live_safety_ok()` checks static
  config gates. Section 40's `MARKET_DATA_HEALTHY`/`RISK_CONFIG_VALID` runtime checks
  are enforced by the risk engine per-trade, but there is no separate startup-time
  health probe wired into the live path yet.

## Architecture

```mermaid
flowchart TD
    HL[Hyperliquid /info API] --> MDS[MarketDataService]
    MDS --> FE[Feature Engine]
    FE --> RD[Regime Detector]
    RD --> MC[Shared MarketContext]
    MC --> COUNCIL[AI Council: 8 analysts + consensus + judge]
    COUNCIL --> MC
    MC --> DL[Decision Loop: one pass per active agent]
    DNA[(Strategy DNA per agent)] --> DL
    DL --> RULE[Deterministic Rule Engine]
    RULE --> RISK[Risk Engine]
    RISK --> EXEC[Execution Engine: paper / shadow / live]
    EXEC --> PNL[PnL Engine]
    PNL --> AGENT[(Agent balance / equity / drawdown)]
    AGENT --> FIT[Fitness Engine]
    FIT --> EVO[Evolution Engine: mutation / crossover / Ollama proposals]
    EVO --> BT[Backtest -> Walk-forward -> OOS]
    BT --> DNA
    AGENT --> API[FastAPI]
    MC --> API
    API --> UI[static HTML page]
```

```mermaid
flowchart LR
    subgraph Deployment
        DB[(SQLite file: trading_lab.db)]
        API[backend: FastAPI, serves API + the static frontend]
        WORKER[worker: run_cycle.py]
    end
    API --> DB
    WORKER --> DB
    WORKER -->|REST| HL[Hyperliquid]
    WORKER -->|REST, external only| OLLAMA[Ollama API]
```

The API process and the trading worker are separate processes on purpose
(`app/main.py`'s docstring): restarting the dashboard must never interrupt a running
trading cycle.

## Project structure

```
backend/app/
  core/        config, logging, database
  models/      SQLAlchemy ORM (agents, strategies, trades, decisions, council, ...)
  schemas/     Pydantic contracts (StrategyDNA, MarketContext, council, API)
  market/      Hyperliquid client, feature engine, market data service
  strategies/  deterministic rule engine, initial-population factory
  risk/        risk engine
  execution/   paper/shadow/live adapters + router
  analytics/   PnL, fitness, professional-classifier
  agents/      lifecycle (create/death/extinction), decision loop
  council/     analyst prompts, consensus engine, orchestration
  evolution/   mutation, crossover, diversity, champion/challenger, Ollama researcher
  backtesting/ event-driven engine, splits, walk-forward
  services/    OllamaClient
  api/         FastAPI routes
  static/      the frontend — a single unstyled index.html served at "/"
backend/scripts/
  bootstrap_population.py   create/recreate a generation of agents
  run_cycle.py              the main trading-cycle worker (--once for a single pass)
backend/tests/    56 tests across DNA, lifecycle, risk, execution safety, council,
                  Ollama client failure modes, feature engine, fitness, backtesting,
                  and a full decision-loop integration test
run.sh            single entrypoint: sets up venv/migrations if needed, then runs the
                  worker and API as background services (systemd-style — restart on
                  crash, own log files, start/stop/restart/status/logs). No external
                  database — trading_lab.db is a plain SQLite file.
```

## Setup

### Run everything

```bash
./run.sh          # or: ./run.sh start
```

This is the only command you need. On first run it creates the backend virtualenv,
installs dependencies, applies migrations against the local SQLite file
(`backend/trading_lab.db`, created automatically), and bootstraps the initial agent
population if none exists. Then it starts the trading worker and the API (which also
serves the frontend at `/`) as **background services** — each under its own
restart-on-crash supervisor loop, like systemd's `Restart=always`, so a crashed process
comes back on its own a few seconds later instead of silently staying dead. The command
returns immediately; there's no foreground process to Ctrl-C, and no database server to
install or run.

```bash
./run.sh status    # is it running?
./run.sh logs      # tail -f both log files (backend/logs/worker.log, api.log)
./run.sh restart   # stop then start (e.g. after pulling new code)
./run.sh stop      # stop both services
```

Before first run, fill in `backend/.env` (copied automatically from `.env.example` if
missing) with `OLLAMA_BASE_URL` / `OLLAMA_API_KEY` / `OLLAMA_MODEL`.

### Manual / step-by-step backend setup

Only needed if you want to run pieces individually instead of `./run.sh`:

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # then fill in OLLAMA_BASE_URL / OLLAMA_API_KEY / OLLAMA_MODEL

alembic upgrade head   # creates ./trading_lab.db if it doesn't exist yet

python -m scripts.bootstrap_population
python -m scripts.run_cycle --once     # or omit --once to loop forever

uvicorn app.main:app --reload          # API + frontend at http://localhost:8000
```

Run tests (uses `DATABASE_URL` from `.env`, or point it at a disposable test DB):

```bash
DATABASE_URL="sqlite+aiosqlite:///./test_trading_lab.db" pytest
```

### Frontend

There is no separate frontend app or build step — `backend/app/static/index.html` is a
single plain HTML/JS file (no styling, no framework) that polls the API and is served
directly by FastAPI at `/`.

## Trading modes

```env
TRADING_MODE=paper   # default — never sends real orders (enforced by a test that
                      # patches httpx and asserts PaperExecutionAdapter never calls it)
TRADING_MODE=shadow   # computes real fills against live data but never sends them
TRADING_MODE=live     # requires LIVE_TRADING_ENABLED=true, LIVE_ACCOUNT_CONFIRMED=true,
                      # LOAD_AGENT_SNAPSHOT set, and Hyperliquid credentials configured —
                      # AND live_adapter.py implemented (see Known gaps). Missing any
                      # gate raises LiveSafetyGateError before any adapter is constructed.
```

## Agent lifecycle rules enforced in code

- Every agent starts with exactly `AGENT_STARTING_BALANCE` (default `$100`).
- Death (`equity <= 0`) is permanent; `mark_dead` is idempotent but never reversible.
- `best_milestone_multiple` (2x/3x/5x/...) only ratchets up, even if equity later falls.
- Agent identifiers (`GEN01-AG0001`) are never reused across generations.
- Population extinction is detected and recorded, but repopulation is a deliberate
  manual/scheduled step, not automatic.

## Security

- No secrets are hardcoded; everything sensitive comes from `.env` (gitignored).
- Structured logs redact any field named like an API key/private key.
- The frontend never receives `OLLAMA_API_KEY` or Hyperliquid credentials — it only
  talks to the backend's own REST API.

## Testing summary

74 backend tests, all passing against a real SQLite database (no mocked DB):
DNA validation/mutation/crossover, agent lifecycle and permanence, deterministic risk
decisions, paper-execution safety and idempotency, council consensus/judge logic,
Ollama client failure handling (timeout/429/malformed JSON/schema mismatch), feature
engine correctness and look-ahead prevention, fitness engine anti-overfitting behavior,
and event-driven backtesting (including a regression guard against look-ahead fills).
