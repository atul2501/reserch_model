# Security, secrets, and the live-trading gate

## 1. Secret exposure — rotation is REQUIRED

`backend/.env` was committed to git (commits `bf1fdec`, `01f89ca`, `76d8031`, `a958fcd`) and the
repository has a GitHub remote (`origin`). The tracked file contained **real-looking Ollama API
keys and a Hyperliquid private key/wallet address** (values are not reproduced here).

Removing the file from the working tree does **not** remove it from history. Treat every value that
was ever in that file as compromised:

1. **Rotate now**: all Ollama API keys (`OLLAMA_API_KEY`, `OLLAMA_API_KEYS`); the Hyperliquid API/private key
   (and confirm whether the wallet holds funds — if it does, move them); any database password that
   appeared in an earlier `DATABASE_URL`.
2. `backend/.env` has been untracked (`git rm --cached`); `.gitignore` ignores `.env` and `.env.*`.
3. **Purge history** (this remediation deliberately did *not* rewrite history or force-push — that is your call).
   `scripts/purge_secrets_from_history.sh` lists the commits touching the secret-bearing paths (dry run by default) and,
   with `--execute`, prepares a cleaned *mirror clone* without pushing anything. The manual equivalent:

   ```bash
   pip install git-filter-repo
   git clone --mirror git@github.com:atul2501/reserch_model.git && cd reserch_model.git
   git filter-repo --invert-paths --path backend/.env
   git push --force --mirror     # coordinate with collaborators; everyone must re-clone
   ```
   Then ask GitHub support to purge cached views/forks if the repo was ever public.
4. Keep secrets outside the repo: `/etc/trading-lab/env` (root-owned, `0600`) loaded by systemd's
   `EnvironmentFile=`, or your platform's secrets manager. Never put keys in `.env.example`.
5. Logs are scrubbed (`core/logging.py`): secret-named keys, `Bearer …` tokens, `api_key=…` fragments and
   `0x` + 64-hex strings are redacted, including inside exception text. Ollama credentials are only ever
   identified by *index*.

## 2. API authentication & authorization

* `API_AUTH_REQUIRED=true` (default) — **fail closed**: with no `API_KEYS` configured every protected
  request is rejected. Create keys with `python -m scripts.hash_api_key <name> <role>`; only the
  SHA-256 is stored in the environment (`API_KEYS=name:role:sha256hex,...`). Comparison is constant time.
* Roles (ordered): `viewer` (dashboard reads), `researcher`, `operator` (kill switch, `/metrics`,
  `/api/system/ollama`), `admin`. Read-only dashboard access never grants control-plane rights.
* Keys travel in `X-API-Key` / `Authorization: Bearer` headers only — never URLs or cookies. The dashboard
  keeps the key in `sessionStorage` (cleared with the tab).
* CORS is restricted to `CORS_ORIGINS`, `GET/POST` and the two auth headers; `allow_credentials=false`.
* Default bind is `127.0.0.1`. Exposing the API is a deliberate deployment step: put it behind TLS
  (reverse proxy) and set `API_HOST` explicitly. *Note:* a developer's local `backend/.env` may still set
  `API_HOST=0.0.0.0` — change it.
* Security headers (`nosniff`, `frame-deny`, `no-referrer`, `no-store`) and HTML-escaping of every
  API-derived string in the dashboard.

### API hardening
* `/docs`, `/redoc` and `/openapi.json` are **off** unless `EXPOSE_API_DOCS=true`.
* A malformed `API_KEYS` stops the API at startup (never a 500 on every request); at request time it fails closed (401).
* Failed authentication is locked out per client (`API_AUTH_MAX_FAILURES` in `API_AUTH_FAILURE_WINDOW_SECONDS`, then
  429 + `Retry-After` for `API_AUTH_LOCKOUT_SECONDS`, even for a valid key); authenticated requests are rate-limited per
  principal (`API_RATE_LIMIT_PER_MINUTE`). In-process limits: also rate-limit at your reverse proxy.
* 401/403/lockouts are logged (never the key); kill-switch changes are an append-only `system_events` audit trail.
* Concurrent SSE streams are capped globally and per principal and expire after `API_SSE_MAX_AGE_SECONDS`.
* `Content-Security-Policy` (default-src none; inline script/style only), HSTS behind TLS, `nosniff`, frame-deny;
  every API-derived string in the dashboard is escaped (a test guards the known fields).
* Secrets are `SecretStr` (never in a repr/log); tracebacks are redacted **after** formatting, and stdlib/uvicorn
  loggers pass through the same scrubber. systemd units fail hard on a missing env file, are sandboxed
  (`ProtectHome`, `PrivateDevices`, no capabilities) and the API reads a separate env file that does **not** contain
  the wallet key or Ollama keys.

## 3. Live trading is blocked — and stays blocked

*Proven, not asserted:* `tests/test_no_live_orders.py` scans every module (docstrings and comments excluded) for order-sending, signing and wallet code, checks there is no signing dependency, records **every outbound HTTP request** during real paper cycles + a council and requires each to hit an allow-listed read endpoint (`/info`, `/api/chat`), and shows that even with every live gate open the adapter raises before any I/O.

* `TRADING_MODE=paper` is the default. `shadow` cannot send orders (read-only `l2Book`).
* The live adapter raises `NotImplementedError`; there is **no** production live-order path.
* Even the stub is unreachable unless *every* gate is set: `LIVE_TRADING_ENABLED`, `LIVE_ACCOUNT_CONFIRMED`,
  `LOAD_AGENT_SNAPSHOT`, wallet address, private key **and** `LIVE_PREREQUISITES_SIGNED_OFF`.
* Emergency stop: `POST /api/system/kill-switch {"active": true}` (operator) blocks all new entries
  in every mode; exits continue.

**Launch checklist — none of these is complete today:**

- [ ] Hyperliquid `/exchange` integration with EIP-712 signing, tested on the **testnet**
- [ ] Order/position **reconciliation** against the exchange (including unknown order state)
- [ ] Idempotency proven against real retries (exchange `cloid`)
- [ ] Emergency stop wired to cancel-all / flatten on the exchange (today it only halts new entries)
- [ ] Secrets rotated and in a secrets manager; history purged
- [ ] TLS + network policy in front of the API; audit logging of control-plane calls
- [ ] Extended shadow soak with measured expected-vs-actual within tolerance
