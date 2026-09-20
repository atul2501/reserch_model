"""Hyperliquid LIVE execution adapter — spec sections 5/19/39/40.

STATUS: interface-only. This is intentionally NOT a working implementation.

Placing a real signed order on Hyperliquid requires EIP-712 wallet signing
of the exchange payload, nonce management, and careful handling of partial
fills/cancels against a real order book — getting this wrong risks real
capital. Per spec section 57 ("do not create fake implementations merely to
make the application appear complete"), this class defines the exact
interface the rest of the system already expects (ExecutionEngine), and
every method raises NotImplementedError with what remains to be built,
rather than silently pretending to place orders.

Before this can be implemented for real, the safety gates in
Settings.live_safety_ok() must already be enforced by the caller — this
class does not re-check them, it assumes the caller (ExecutionRouter) never
constructs a live adapter unless every gate in spec section 40 passed.

TODO(live-trading):
  - Implement Hyperliquid `/exchange` payload construction + EIP-712 signing
    using `hyperliquid_account_address` / `hyperliquid_private_key`.
  - Implement idempotent order submission keyed by client_order_id (Hyperliquid
    supports a `cloid` field for this).
  - Implement fill polling / websocket user-events subscription to resolve
    ExecutionResult asynchronously rather than assuming immediate fill.
  - Implement liquidation-distance and margin queries for the risk engine.
  - Add integration tests against Hyperliquid's testnet before any mainnet use.
"""
from __future__ import annotations

from app.execution.base import ExecutionEngine, ExecutionRequest, ExecutionResult
from app.models.enums import ExecutionVenue


class HyperliquidLiveExecutionAdapter(ExecutionEngine):
    venue = ExecutionVenue.LIVE

    def __init__(self, account_address: str, private_key: str) -> None:
        if not account_address or not private_key:
            raise ValueError("live adapter requires a configured account address and private key")
        self._account_address = account_address
        self._private_key = private_key

    async def submit_order(self, request: ExecutionRequest) -> ExecutionResult:
        raise NotImplementedError(
            "Live order execution is not implemented yet — see module docstring "
            "for the remaining work (EIP-712 signing, idempotent submission, "
            "fill resolution). Refusing to place a real order rather than "
            "fake a fill."
        )
