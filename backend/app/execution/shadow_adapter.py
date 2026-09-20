"""Shadow execution adapter (spec section 5/38).

Reads real market data and computes exactly what a live order would look
like, but never actually sends it — used to validate a challenger strategy
against live conditions before it is trusted with real capital. Internally
reuses the paper fill model since a shadow fill is, by definition, simulated.
"""
from __future__ import annotations

from app.core.logging import get_logger
from app.execution.base import ExecutionRequest, ExecutionResult
from app.execution.paper_adapter import PaperExecutionAdapter
from app.models.enums import ExecutionVenue

logger = get_logger(__name__)


class ShadowExecutionAdapter(PaperExecutionAdapter):
    venue = ExecutionVenue.SHADOW

    async def submit_order(self, request: ExecutionRequest) -> ExecutionResult:
        result = await super().submit_order(request)
        logger.info(
            "shadow_execution.simulated_fill",
            client_order_id=request.client_order_id,
            filled_price=result.filled_price,
            status=result.status.value,
        )
        return result
