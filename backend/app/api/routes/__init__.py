from fastapi import APIRouter

from app.core.security import viewer_required

from app.api.routes.adversarial import router as adversarial_router
from app.api.routes.agents import router as agents_router
from app.api.routes.champion_challenger import router as champion_challenger_router
from app.api.routes.correlation import router as correlation_router
from app.api.routes.leaderboard import router as leaderboard_router
from app.api.routes.market import router as market_router
from app.api.routes.population import router as population_router
from app.api.routes.positions import router as positions_router
from app.api.routes.reality_gap import router as reality_gap_router
from app.api.routes.regime_validation import router as regime_validation_router
from app.api.routes.council import router as council_router
from app.api.routes.evolution import router as evolution_router
from app.api.routes.shadow import router as shadow_router
from app.api.routes.status import router as status_router
from app.api.routes.system import router as system_router
from app.api.routes.trades import router as trades_router

api_router = APIRouter()
api_router.include_router(adversarial_router, dependencies=[viewer_required])
api_router.include_router(champion_challenger_router, dependencies=[viewer_required])
api_router.include_router(correlation_router, dependencies=[viewer_required])
api_router.include_router(system_router, dependencies=[viewer_required])
api_router.include_router(market_router, dependencies=[viewer_required])
api_router.include_router(population_router, dependencies=[viewer_required])
api_router.include_router(agents_router, dependencies=[viewer_required])
api_router.include_router(leaderboard_router, dependencies=[viewer_required])
api_router.include_router(trades_router, dependencies=[viewer_required])
api_router.include_router(positions_router, dependencies=[viewer_required])
api_router.include_router(reality_gap_router, dependencies=[viewer_required])
api_router.include_router(regime_validation_router, dependencies=[viewer_required])
api_router.include_router(council_router, dependencies=[viewer_required])
api_router.include_router(evolution_router, dependencies=[viewer_required])
api_router.include_router(shadow_router, dependencies=[viewer_required])
api_router.include_router(status_router, dependencies=[viewer_required])
