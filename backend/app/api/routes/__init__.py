from fastapi import APIRouter

from app.api.routes.agents import router as agents_router
from app.api.routes.leaderboard import router as leaderboard_router
from app.api.routes.market import router as market_router
from app.api.routes.population import router as population_router
from app.api.routes.system import router as system_router

api_router = APIRouter()
api_router.include_router(system_router)
api_router.include_router(market_router)
api_router.include_router(population_router)
api_router.include_router(agents_router)
api_router.include_router(leaderboard_router)
