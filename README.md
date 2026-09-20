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

This repository was built from zero in one focused implementation pass. Everything
described below as "built" has been exercised against a real PostgreSQL database and
(where applicable) the real Hyperliquid public API — not just written and assumed
correct. Everything under "Known gaps" is an honest TODO, not a stub pretending to be
finished (see `app/execution/live_adapter.py` for the canonical example of how this
codebase prefers "raises NotImplementedError with a clear reason" over a fake
implementation).

### What's built and verified

- **Config / logging / database** — Pydantic settings, structured JSON logging with
  secret redaction, async SQLAlchemy + Alembic. Migration applies and rolls back
  cleanly against Postgres 16 (verified, including a fix for a circular FK between
  `orders`/`decisions` and for Postgres enum types not being dropped on downgrade).
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
  `/api/agents`, `/api/agents/{id}`, `/api/leaderboard`. A React/TypeScript/Tailwind
  dashboard (dark, dense, table-first — not a consumer SaaS look) polls these and was
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
    API --> UI[React dashboard]
```

```mermaid
flowchart LR
    subgraph Deployment
        PG[(PostgreSQL)]
        API[backend: FastAPI]
        WORKER[worker: run_cycle.py]
        UI[frontend: React/Vite]
    end
    API --> PG
    WORKER --> PG
    WORKER -->|REST| HL[Hyperliquid]
    WORKER -->|REST, external only| OLLAMA[Ollama API]
    UI -->|REST, polling| API
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
backend/scripts/
  bootstrap_population.py   create/recreate a generation of agents
  run_cycle.py              the main trading-cycle worker (--once for a single pass)
backend/tests/    56 tests across DNA, lifecycle, risk, execution safety, council,
                  Ollama client failure modes, feature engine, fitness, backtesting,
                  and a full decision-loop integration test
frontend/src/     React/TS/Tailwind dashboard (Dashboard page, Panel/StatTile/StatusDot
                  components, polling hook, typed API client)
```

## Setup

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # then fill in OLLAMA_BASE_URL / OLLAMA_API_KEY / OLLAMA_MODEL
```

Create the database (adjust for your local Postgres):

```bash
createdb trading_lab   # or: psql -c "CREATE DATABASE trading_lab OWNER trading_lab;"
alembic upgrade head
```

Create the initial population and run one trading cycle:

```bash
python -m scripts.bootstrap_population
python -m scripts.run_cycle --once     # or omit --once to loop forever
```

Run the API:

```bash
uvicorn app.main:app --reload
```

Run tests (uses `DATABASE_URL` from `.env`, or point it at a disposable test DB):

```bash
DATABASE_URL="postgresql+asyncpg://trading_lab:trading_lab@localhost:5432/trading_lab_test" pytest
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_BASE_URL, defaults to http://localhost:8000
npm run dev
```

### Docker

```bash
docker compose up --build
```

Ollama is intentionally **not** in `docker-compose.yml` — this platform always calls
an external Ollama API (`OLLAMA_BASE_URL`), never a local container.

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

56 backend tests, all passing against a real PostgreSQL instance (no mocked DB):
DNA validation/mutation/crossover, agent lifecycle and permanence, deterministic risk
decisions, paper-execution safety and idempotency, council consensus/judge logic,
Ollama client failure handling (timeout/429/malformed JSON/schema mismatch), feature
engine correctness and look-ahead prevention, fitness engine anti-overfitting behavior,
and event-driven backtesting (including a regression guard against look-ahead fills).
