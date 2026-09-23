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
3. **Purge history** (this remediation deliberately did *not* rewrite history or force-push — that is your call):

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

## 3. Live trading is blocked — and stays blocked

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
